"""Phase 8B：真实 Verify 时延经验改变下一次受控 web 动作。"""
from copy import deepcopy
from dataclasses import replace
import argparse
import hashlib
import json
import math
import time
from uuid import uuid4

from .authorization import AuthorizationGate
from .contracts import PROJECT_ROOT, validate
from .credential_handling import redact_persistent
from .docker_executor import DockerBoundaryError, LocalDocker
from .executor import ExecutionOutcome
from .memory import RecoveryMemory
from .nexent_provider import NexentConfig, NexentRCAProvider
from .phase8_online import ScopedStartBackend
from .recovery_smoke import _scope, _web_stopped, _fresh, _wall_time, context, fault_recovery
from .strategies import check_offline_action, plan_candidates
from .trace_journal import TraceJournal
from .online_reports import ReportPersistenceError, replace_complete, save_pair

POLICY = {'version': 'phase8b-v1', 'latency_target_ms': 5000,
          'verified_success_bonus': .20, 'verified_over_target_penalty': -.35,
          'max_incidents': 2, 'max_actions_per_incident': 1,
          'verify_window_seconds': 30,
          'meaning': '成功仍为成功；超过预先固定的5秒目标另扣时延分，不推断替代动作更快'}


def check_online_action(action, observation):
    safety = check_offline_action(action, observation)
    if safety['allowed']:
        pair = action['action'], action['target']
        if pair in {('start_service', 'web'), ('restart_service', 'web')} and _web_stopped(observation):
            safety['reason'] = 'allowed_phase8b_stopped_web'
        elif pair != ('no_action', None):
            safety.update(allowed=False, reason='phase8b_scope_rejected')
    return safety


class OnlineMemory(RecoveryMemory):
    """只给完整真实成功事件附加可关联的原始时延；不注入或改写历史。"""
    def retrieve(self, failure_type, location, *, limit=3):
        items = super().retrieve(failure_type, location, limit=limit)
        events = {event['event_id']: event for event in self._read_events()} if self.path.exists() else {}
        for item in items:
            data = events[item['event_id']]['data']
            latency = data.get('online_latency', {})
            samples = data.get('verify_observations', [])
            value = latency.get('duration_ms')
            if (data.get('phase') == '8B' and data.get('real_model') is True
                    and data.get('real_observation') is True and data.get('recovery_verified') is True
                    and latency.get('source') == 'local_monotonic_executor_to_verify'
                    and type(value) in (int, float) and math.isfinite(value) and value >= 0
                    and latency.get('target_ms') == POLICY['latency_target_ms']
                    and len(samples) >= 2
                    and len({sample['observation_id'] for sample in samples}) == len(samples)
                    and latency.get('verify_observation_ids') == [sample['observation_id'] for sample in samples]
                    and all(sample[key] == data[key] for sample in samples for key in ('incident_id', 'trace_id'))
                    and all(sample['request']['status_code'] == 200 for sample in samples[-2:])):
                item['online_latency'] = deepcopy(latency)
        return items


def rank_online(core, memory):
    observation, diagnosis = core['observation'], core['diagnosis']
    history = memory.retrieve(diagnosis['failure_type'], diagnosis['location'], limit=3) if memory else []
    common = dict(diagnosis=diagnosis, observation=observation, rca=core['rca'], mode='reops',
                  candidate_guard=check_online_action)
    without = plan_candidates(**common)
    selected = plan_candidates(**common, history=history)
    basis = selected['decision_basis']
    indexed = {item['event_id']: item for item in history}
    for candidate in basis['candidates']:
        penalties = []
        for evidence in candidate['memory_evidence']:
            historical = indexed[evidence['event_id']]
            latency = historical.get('online_latency')
            if evidence['verified_success'] and latency and latency['duration_ms'] > POLICY['latency_target_ms']:
                penalties.append({'event_id': evidence['event_id'],
                    'incident_id': historical['incident_id'], 'trace_id': historical['trace_id'],
                    'duration_ms': latency['duration_ms'], 'target_ms': POLICY['latency_target_ms'],
                    'verify_observation_ids': latency['verify_observation_ids'],
                    'score_delta': POLICY['verified_over_target_penalty'],
                    'outcome_remains': 'recovered'})
        penalty = max(-.35, sum(item['score_delta'] for item in penalties)) if candidate['allowed'] else 0
        candidate.update(latency_evidence=penalties, latency_score_delta=penalty,
                         score=round(candidate['score'] + penalty, 3))
    winner = max((c for c in basis['candidates'] if c['allowed']), key=lambda c: (c['score'], c['strategy_id']))
    # 重新构造被选中动作，不沿用旧胜者的 action_id / strategy 字段。
    from .strategies import _action
    action = _action(diagnosis, winner['action'], winner['target'], winner['parameters'],
                     winner['prior_score'], winner['strategy_id'])
    action['decision_basis'] = basis
    basis.update(strategy='phase8b_online_latency_memory', selected_strategy=winner['strategy_id'],
        offline_only=False, online_scope='start_and_restart_stopped_web', policy=deepcopy(POLICY),
        without_memory_candidates=without['decision_basis']['candidates'],
        without_memory_selection=without['action'], history_event_ids=[item['event_id'] for item in history],
        memory_changed_selection=action['action'] != without['action'])
    action['reason'] = '真实成功/失败及Verify时延评分；独立Safety和本次动作授权拥有最终否决权'
    validate('recovery_action', action)
    core.update(recovery_action=action, safety=check_online_action(action, observation),
                would_execute=core['would_execute'] and core['diagnosis_validated']
                and action['action'] in {'start_service', 'restart_service'})
    return core


class ScopedWebBackend(ScopedStartBackend):
    def restart(self, observation):
        self.check()
        started = _wall_time()
        current = self.backend.observe(observation)
        _fresh(current, observation, seen={observation['observation_id']}, not_before=started)
        if not _web_stopped(current):
            raise DockerBoundaryError('restart_fault_changed_or_cleared')
        self.check()
        self.backend.restart('web', expected_container_id=self.scope['containers']['api'])
        return {'operation': 'restart', 'compose_service': 'api',
                'container_id': self.scope['containers']['api'], 'pre_observation': current}


class WebExecutor:
    def __init__(self, backend):
        if not isinstance(backend, ScopedWebBackend):
            raise DockerBoundaryError('phase8b_authorized_entry_required')
        self.backend = backend

    def __call__(self, action, observation):
        if not check_online_action(action, observation)['allowed'] or action['action'] not in {'start_service', 'restart_service'}:
            raise DockerBoundaryError('phase8b_executor_action_rejected')
        started = time.monotonic()
        operation = 'start' if action['action'] == 'start_service' else 'restart'
        proof = self.backend.start(observation) if operation == 'start' else self.backend.restart(observation)
        post = self.backend.observe(observation)
        return ExecutionOutcome('succeeded', 0, None, None, (time.monotonic()-started)*1000,
            post, {'action': action['action'], 'target': 'web', 'mode': 'real', 'executed': True,
                   'success': True, 'docker_status': operation+'_completed', 'operation_proof': proof})


def render(report):
    rows = ['# Phase 8B：Memory 改变实际恢复决策', '',
            f"验收通过：{report['acceptance_passed']}；模型调用：{report['model_calls']}。", '',
            '评分规则在两个incident前固定：成功+0.20；真实执行至两次fresh Verify耗时超过5秒，另扣0.35。成功事实不改写，5秒为Demo目标，非生产标定。', '']
    for number, incident in enumerate(report['incidents'], 1):
        basis = incident.get('recovery_action', {}).get('decision_basis', {})
        rows += [f"## Incident {number}：{incident['incident_id']}", '',
                 'Observation → RCA → candidates → 无Memory分数 → Memory evidence → 新分数 → 最终动作 → Executor → Verify → Memory。', '',
                 '|候选|无Memory|成功/失败经验增量|时延经验增量|新分数|Safety|', '|---|---:|---:|---:|---:|---|']
        cold = {c['strategy_id']: c['score'] for c in basis.get('without_memory_candidates', [])}
        for candidate in basis.get('candidates', []):
            rows.append(f"|{candidate['action']}|{cold.get(candidate['strategy_id'])}|{candidate['memory_score_delta']}|{candidate['latency_score_delta']}|{candidate['score']}|{candidate['reason']}|")
        rows += ['', f"最终动作：{incident.get('recovery_action', {}).get('action')}；Executor：{incident.get('execution_outcome')}；Verify：{incident.get('verification_status')}；Memory：{incident.get('event_id')}。",
                 f"命中历史：{basis.get('history_event_ids')}；实测执行至Verify：{incident.get('online_latency', {}).get('duration_ms')} ms。", '']
    rows += [f"实际动作改变：{report['actual_action_changed']}；第二次无Memory反事实仅评分：{report.get('second_without_memory_action')}；Safety否决证据：{report.get('safety_veto')}。", '',
             '仅证明本地固定评分策略受真实经验影响；未证明restart更快、因果性能优势或模型泛化。无来源签名、跨系统事务、硬deadline及Memory并发锁。', '',
             '## 完整机器证据', '', '```json', json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), '```']
    return '\n'.join(rows)+'\n'


def save_report(report, directory):
    try:
        value = redact_persistent(deepcopy(report))
        # render 的完整证据区不递归包含此前保存的摘要。
        value.pop('summary_markdown', None)
        value['summary_markdown'] = render(value)
    except Exception:
        raise ReportPersistenceError('json', 'serialize') from None
    return save_pair(value, directory, 'report.json', 'report.md')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    backend = LocalDocker()
    if not args.run:
        from .recovery_smoke import _healthy
        print(json.dumps({'mode': 'read-only', 'healthy': _healthy(backend.observe(context()))}))
        return 0
    directory = PROJECT_ROOT/'runtime/phase8b'
    if directory.exists():
        raise ValueError('phase8b_evidence_exists_no_automatic_repeat')
    config = replace(NexentConfig.from_env(), max_output_tokens=512)
    config.require_real_model()
    if config.api_base.rstrip('/') != 'http://aigw.dlut.edu.cn/v1' or config.model_id != 'DeepSeek-V3.1-W8A8':
        raise ValueError('phase8b_model_scope_rejected')
    directory.mkdir()
    # 运行前落盘政策；从真正空Memory开始，保留全部既有Phase7D/8文件。
    replace_complete(directory/'policy.json', json.dumps(POLICY, ensure_ascii=False,
                     allow_nan=False, indent=2), artifact='policy')
    memory = OnlineMemory(directory/'memory.jsonl')
    report = {'phase': '8B', 'policy': deepcopy(POLICY), 'incidents': [], 'model_calls': 0,
              'acceptance_passed': False, 'actual_action_changed': False,
              'authorization_delivery': '原终端挑战，按当前用户授权代录；原Gate/TTL/绑定/单次消费不变',
              'source_sha256': {str(p.relative_to(PROJECT_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (PROJECT_ROOT/'reops_agent').glob('*.py')}}
    def persist():
        save_report(report, directory)
    try:
        for number in (1, 2):
            ctx = context() | {'incident_id': f'incident-8b-{uuid4()}', 'trace_id': f'trace-8b-{uuid4()}'}
            incident = fault_recovery(backend, NexentRCAProvider(config),
                gate=AuthorizationGate(directory/'authorizations.sqlite3'),
                journal=TraceJournal(ctx, directory/'audit.jsonl'), memory=memory,
                model_identifier=config.model_id, execute_recovery=True, real_model=True,
                real_observation=True, phase8_online=True, phase8b=True)
            report['incidents'].append(incident)
            report['model_calls'] += incident['model_calls']
            persist()
            if not incident.get('acceptance_passed'):
                break
        if len(report['incidents']) == 2:
            first, second = report['incidents']
            report['actual_action_changed'] = (first['recovery_executed'] and second['recovery_executed']
                and first['recovery_action']['action'] != second['recovery_action']['action'])
            report['second_without_memory_action'] = second['recovery_action']['decision_basis']['without_memory_selection']
            historical = memory.retrieve(second['diagnosis']['failure_type'], second['diagnosis']['location'])
            report['memory_readback'] = historical
            # 在实际最终fresh健康Observation上，Memory推荐的动作也必须被否决；零额外执行。
            report['safety_veto'] = check_online_action(second['recovery_action'], second['post_observation'])
            report['acceptance_passed'] = (all(i['acceptance_passed'] for i in report['incidents'])
                and report['actual_action_changed']
                and report['second_without_memory_action'] == first['recovery_action']['action']
                and first['event_id'] in second['recovery_action']['decision_basis']['history_event_ids']
                and not report['safety_veto']['allowed'])
    except ReportPersistenceError:
        # 保存失败立即停止，不在 finally 重试保存，也不开第二个 incident。
        raise
    except BaseException:
        persist()
        raise
    else:
        persist()
    print(json.dumps({k:report[k] for k in ('acceptance_passed','model_calls','actual_action_changed')}))
    return 0 if report['acceptance_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

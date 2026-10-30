"""Phase 8 在线最小闭环：只新增已停止 web 的 start，沿用 7D 授权与 Verify。"""

import argparse
from copy import deepcopy
from dataclasses import replace
import json
import time
from uuid import uuid4

from .authorization import AuthorizationGate
from .contracts import PROJECT_ROOT, validate
from .credential_handling import redact_persistent
from .docker_executor import DockerBoundaryError, LocalDocker, now
from .executor import ExecutionOutcome
from .memory import RecoveryMemory
from .nexent_provider import NexentConfig, NexentRCAProvider
from .recovery_smoke import (_scope, _web_stopped, _fresh, _healthy, _wall_time,
                             context, fault_recovery)
from .strategies import check_offline_action, plan_candidates
from .trace_journal import TraceJournal
from .online_reports import ReportPersistenceError, save_pair


def check_online_action(action, observation):
    """独立白名单；当前 Demo 恢复只允许 start/web，不受历史或模型扩展。"""
    safety = check_offline_action(action, observation)
    pair = action['action'], action['target']
    if safety['allowed']:
        if pair == ('start_service', 'web') and _web_stopped(observation):
            safety['reason'] = 'allowed_phase8_stopped_web_start'
        elif pair == ('no_action', None):
            safety['reason'] = 'no_action'
        else:
            safety.update(allowed=False, reason='phase8_demo_scope_rejected')
    return safety


def rank_online(core, memory):
    """复用既有候选与评分；分别保留无 Memory、完整排名和真实 scope 后排名。"""
    observation, diagnosis, rca = core['observation'], core['diagnosis'], core['rca']
    history = memory.retrieve(diagnosis['failure_type'], diagnosis['location'], limit=3) if memory else []
    common = dict(diagnosis=diagnosis, observation=observation, rca=rca, mode='reops')
    without = plan_candidates(**common, candidate_guard=check_online_action)
    full_without = plan_candidates(**common)
    full_with = plan_candidates(**common, history=history)
    selected = plan_candidates(**common, history=history, candidate_guard=check_online_action)
    basis = selected['decision_basis']
    basis.update(strategy='phase8_online_multi_candidate', offline_only=False,
                 online_scope='only_start_service_web',
                 without_memory_candidates=without['decision_basis']['candidates'],
                 without_memory_selection=without['action'],
                 memory_changed_selection=selected['action'] != without['action'],
                 history_event_ids=[item['event_id'] for item in history],
                 unconstrained_with_memory=full_with['decision_basis']['candidates'],
                 unconstrained_without_memory=full_without['decision_basis']['candidates'],
                 unconstrained_with_memory_selection=full_with['action'],
                 unconstrained_without_memory_selection=full_without['action'])
    selected['reason'] = '已停止的 API 使用 start；严格 Demo scope 排除 restart 等候选'
    validate('recovery_action', selected)
    core.update(recovery_action=selected, safety=check_online_action(selected, observation),
                would_execute=core['would_execute'] and core['diagnosis_validated']
                    and selected['action'] == 'start_service')
    return core


class ScopedStartBackend:
    def __init__(self, backend, scope):
        self.backend, self.scope = backend, deepcopy(scope)

    def check(self):
        if _scope(self.backend) != self.scope:
            raise DockerBoundaryError('authorized_environment_changed')

    def start(self, observation):
        self.check()
        sample_started = _wall_time()
        current = self.backend.observe(observation)
        _fresh(current, observation, seen={observation['observation_id']}, not_before=sample_started)
        if not _web_stopped(current):
            raise DockerBoundaryError('start_fault_changed_or_cleared')
        self.check()
        return self.backend.start_web(expected_container_id=self.scope['containers']['api'])

    def observe(self, observation):
        self.check()
        return self.backend.observe(observation)


class StartExecutor:
    """固定 start 操作；裸 LocalDocker、其他动作及未知状态均拒绝。"""
    def __init__(self, backend):
        if not isinstance(backend, ScopedStartBackend):
            raise DockerBoundaryError('phase8_authorized_entry_required')
        self.backend = backend

    def __call__(self, action, observation):
        started = time.monotonic()
        if (action['action'], action['target']) != ('start_service', 'web') or not check_online_action(action, observation)['allowed']:
            raise DockerBoundaryError('phase8_executor_action_rejected')
        proof = self.backend.start(observation)
        # 不把此样本计作两次独立 Verify；由 7D 编排重新采样。
        post = self.backend.observe(observation)
        return ExecutionOutcome('succeeded', 0, None, None, (time.monotonic()-started)*1000,
            post, {'action': 'start_service', 'target': 'web', 'mode': 'real',
                   'executed': True, 'success': True, 'docker_status': 'start_completed',
                   'planned_operation': {'operation': 'start', 'compose_service': 'api'},
                   'operation_proof': proof})


def render_summary(report):
    basis = report.get('recovery_action', {}).get('decision_basis', {})
    rows = ['# Phase 8 在线最小闭环验收', '',
            f"验收通过：{report.get('acceptance_passed', False)}；incident：{report['incident_id']}。", '',
            '场景：仅停止 reops-lab 的 API；PostgreSQL/Redis 保持健康。仅新增 start_service(web)，实际命令为固定容器 ID 的 Docker start。', '',
            '| 候选 | scope/Safety | 先验 | Memory 增量 | 总分 |', '|---|---|---:|---:|---:|']
    for item in basis.get('candidates', []):
        rows.append(f"| {item['action']} | {item['reason']} | {item['prior_score']} | {item['memory_score_delta']} | {item['score']} |")
    rows += ['', f"最终选择：{report.get('recovery_action', {}).get('action')}。Memory 改变本次真实选择：{basis.get('memory_changed_selection', False)}。",
             f"未收窄 scope 时：无 Memory={basis.get('unconstrained_without_memory_selection')}；有 Memory={basis.get('unconstrained_with_memory_selection')}（仅计算，未执行）。",
             f"模型调用：{report.get('model_calls', 0)}；独立 Verify 样本：{len(report.get('verify_observations', []))}；恢复确认：{report.get('recovery_verified', False)}；Memory 写入：{report.get('memory_written', False)}；善后：{report.get('cleanup_outcome')}。", '',
             f"成功事件只读回放：{report.get('memory_readback', {}).get('summary', '未评估')}。此回放不调用模型、不执行 Docker。", '',
             'start/restart 区分：执行器映射、动作授权和命令审计明确为 start；已运行容器拒绝 start。停止场景两种命令都可能恢复，未声称 restart 会失败或做第二次在线对照。', '',
             '限制：一次在线样本；未证明模型泛化或 Memory 改变真实动作；无来源签名、跨系统事务或全链路硬 deadline。']
    return '\n'.join(rows) + '\n'


def save_report(report):
    """同份 JSON 包含 Markdown；不宣称两个文件原子事务。"""
    try:
        value = redact_persistent(deepcopy(report))
        value['summary_markdown'] = render_summary(value)
    except Exception:
        raise ReportPersistenceError('json', 'serialize') from None
    directory = (PROJECT_ROOT / 'runtime').resolve()
    if not directory.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError('phase8_output_outside_project')
    try:
        directory.mkdir(exist_ok=True)
    except OSError:
        raise ReportPersistenceError('json', 'directory') from None
    return save_pair(value, directory, 'phase8-online-report.json', 'phase8-online-acceptance.md')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    backend = LocalDocker()
    ctx = context() | {'incident_id': f'incident-8-{uuid4()}', 'trace_id': f'trace-8-{uuid4()}'}
    if not args.run:
        observation = backend.observe(ctx)
        print(json.dumps({'mode': 'read-only', 'baseline_healthy': _healthy(observation)}, ensure_ascii=True))
        return 0
    config = replace(NexentConfig.from_env(), max_output_tokens=512)
    config.require_real_model()
    if config.api_base.rstrip('/') != 'http://aigw.dlut.edu.cn/v1' or config.model_id != 'DeepSeek-V3.1-W8A8':
        raise ValueError('phase8_model_scope_rejected')
    report = fault_recovery(backend, NexentRCAProvider(config),
        gate=AuthorizationGate(PROJECT_ROOT/'runtime/phase8-authorizations.sqlite3'),
        journal=TraceJournal(ctx, PROJECT_ROOT/'runtime/phase8-audit.jsonl'),
        memory=RecoveryMemory(PROJECT_ROOT/'runtime/phase7d-memory.jsonl'),
        model_identifier=config.model_id, execute_recovery=True, real_model=True,
        real_observation=True, phase8_online=True)
    save_report(report)
    print(json.dumps({key: report.get(key) for key in ('acceptance_passed', 'model_calls', 'recovery_verified', 'error')}, ensure_ascii=True))
    return 0 if report.get('acceptance_passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())

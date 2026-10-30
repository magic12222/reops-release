"""Phase8同一pipeline的离线三方法比较及Memory消融。"""
from contextlib import ExitStack
import argparse
from copy import deepcopy
import json
import hashlib
import os
import platform
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

from .contracts import PROJECT_ROOT
from .benchmark_fixtures import strict_load, validate_case
from .memory import RecoveryMemory
from .offline_benchmark import observation, _forbidden
from .rca import RCAAgent
from .recovery import recover

FIXTURES=PROJECT_ROOT/'benchmarks/offline/strategy-scenarios.json'
ROBUSTNESS_FIXTURES=PROJECT_ROOT/'benchmarks/offline/strategy-robustness-scenarios.json'
MULTIROUND_FIXTURES=PROJECT_ROOT/'benchmarks/offline/strategy-multiround-scenarios.json'
RESOURCE_FIXTURES=PROJECT_ROOT/'benchmarks/offline/strategy-resource-scenarios.json'


class FixtureModel:
    offline_only=True
    def __init__(self,case):self.case,self.calls=case,0
    def complete(self,request,*,timeout_seconds):
        self.calls+=1
        if self.case.get('malformed'):return '{invalid'
        suggestions=self.case.get('suggestions')
        operation,target=(suggestions[min(self.calls-1,len(suggestions)-1)] if suggestions
                          else self.case.get('suggestion',['restart_service','web']))
        return json.dumps({'suspected_root_cause':'offline_fixture',
            'affected_component':self.case.get('affected_component','api' if target=='web' else target),
            'confidence':self.case.get('confidence',.97),
            'evidence':self.case.get('evidence',['offline fixture service evidence only']),
            'reasoning_summary':'fixture baseline',
            'suggested_action':{'action':operation,'target':target}})


def run_case(case,directory):
    validate_case(case)
    pre=observation(case['state'])
    if case.get('dependent_api_unhealthy'):
        pre['services']['api'].update(status='unhealthy',message='health probe unhealthy')
    pre['offline_signals']=deepcopy(case.get('signals',{}))
    pre['metrics'].update(deepcopy(case.get('metrics',{})))
    pre['offline_effects']=deepcopy(case.get('effects',{}))
    history=RecoveryMemory(directory/'memory.jsonl')
    seed=case.get('memory_seed')
    if seed=='failed_start':
        recover(pre,memory=history,offline_strategy='rule_based',execution_succeeds=False)
    elif seed=='verified_restart':
        recover(pre,memory=history,offline_strategy='llm_only',
                rca_agent=RCAAgent(FixtureModel({'suggestion':['restart_service','web']})))
    if case.get('memory_transform'):
        event=json.loads(history.path.read_text(encoding='utf-8').splitlines()[0])
        transform=case['memory_transform']
        if transform=='replay':
            for _ in range(20):history.remember(deepcopy(event))
        elif transform=='conflict':
            event['data']['observation']['offline_signals']={'context':'conflicting-copy'}
            history.remember(event)
        elif transform=='changed_context':
            pre['offline_signals']={'context':'new-context'}
        else:
            raise ValueError('unknown_memory_transform')
    methods={}
    for label,mode,memory in [('rule_based','rule_based',None),('llm_only','llm_only',None),
                              ('reops','reops',history),('reops_without_memory','reops',None)]:
        model=FixtureModel(case)
        result=recover(pre,offline_strategy=mode,rca_agent=RCAAgent(model) if mode!='rule_based' else None,
                       memory=memory,max_recovery_attempts=case.get('max_attempts',1))
        # Do not contaminate later baseline runs with current test results:
        # each baseline observes the same fixture; only ReOps consumes the seed.
        basis=result['recovery_action']['decision_basis']
        actual={'strategy':basis['selected_strategy'],'recovered':result['recovered'],
                'model_calls':model.calls,'action':result['recovery_action']['action'],
                'target':result['recovery_action']['target'],'safety_allowed':result['safety']['allowed'],
                'real_recovery_actions':result['real_recovery_actions'],
                'memory_evidence_count':sum(len(c['memory_evidence']) for c in basis['candidates']),
                'attempt_count':result['attempt_count'],'final_status':result['final_status'],
                'initial_failure_detected':result['attempts'][0]['diagnosis']['failure_detected'],
                'fixture_recovery_verified':result['agent_event']['data']['fixture_recovery_verified'],
                'strategy_sequence':[a['recovery_action']['decision_basis']['selected_strategy'] for a in result['attempts']],
                'fixture_action_count':sum(a['execution_result']['execution_status']!='skipped' for a in result['attempts']),
                'estimated_action_cost':round(sum(a['recovery_action']['estimated_cost']
                    for a in result['attempts'] if a['execution_result']['execution_status']!='skipped'),3)}
        checks={key:actual.get(key)==expected for key,expected in case['expected'][label].items()}
        checks.update(no_real_actions=actual['real_recovery_actions']==0,
                      fresh_verify=result['post_observation']['observation_id']!=pre['observation_id'],
                      no_false_recovery=not actual['recovered'] or case['expected'][label]['recovered'])
        attempts=result['attempts']
        actions=[(a['recovery_action']['action'],a['recovery_action']['target'])
                 for a in attempts if a['execution_result']['execution_status']!='skipped']
        checks.update(bounded_attempts=len(attempts)<=case.get('max_attempts',1),
                      no_failed_action_replay=len(actions)==len(set(actions)),
                      distinct_traces=len({a['agent_event']['trace_id'] for a in attempts})==len(attempts),
                      single_incident=all(a['agent_event']['incident_id']==pre['incident_id'] for a in attempts),
                      independent_post_samples=len({pre['observation_id'],*[a['post_observation']['observation_id']
                          for a in attempts]})==len(attempts)+1,
                      parent_chain=all(a['agent_event']['parent_event_id']==(
                          attempts[i-1]['agent_event']['event_id'] if i else None) for i,a in enumerate(attempts)),
                      fresh_replan=all(a['agent_event']['data']['observation']['observation_id']==
                          attempts[i-1]['post_observation']['observation_id'] for i,a in enumerate(attempts) if i))
        methods[label]={'actual':actual,'expected':case['expected'][label],'checks':checks,
                       'passed':all(checks.values()),'candidates':basis['candidates'],
                       'pipeline_result':_pipeline_result(result),
                       'attempts':[_pipeline_result(a) for a in attempts]}
    return {'case_id':case['id'],'suite':case.get('suite','design'),
            'failure_detected':result['attempts'][0]['diagnosis']['failure_detected'],
            'memory_seed':seed,'methods':methods,'passed':all(m['passed'] for m in methods.values())}


def run_benchmark():
    sources=_source_manifest()
    cases=[]
    for suite,path in [('design',FIXTURES),('robustness',ROBUSTNESS_FIXTURES),
                       ('multiround',MULTIROUND_FIXTURES),('resource',RESOURCE_FIXTURES)]:
        cases += [dict(case,suite=suite) for case in strict_load(path.read_text(encoding='utf-8'))]
    ids=[case['id'] for case in cases]
    if len(ids)!=len(set(ids)) or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',name) for name in ids):
        raise ValueError('duplicate_or_invalid_case_id')
    results=[]
    runtime=PROJECT_ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with ExitStack() as stack:
        for target in ('socket.socket.connect','socket.socket.connect_ex','socket.create_connection',
                       'subprocess.run','subprocess.Popen'):
            stack.enter_context(patch(target,side_effect=_forbidden))
        with tempfile.TemporaryDirectory(prefix='strategy-benchmark-',dir=runtime) as temp:
            for case in cases:
                directory=Path(temp)/case['id'];directory.mkdir()
                results.append(run_case(case,directory))
    metrics=_metrics(results)
    suites={name:_metrics([r for r in results if r['suite']==name]) for name in ('design','robustness','multiround','resource')}
    behavior=[{'case_id':r['case_id'],'suite':r['suite'],'methods':{
        label:{key:m[key] for key in ('actual','expected','checks')} for label,m in r['methods'].items()}}
        for r in results]
    if sources != _source_manifest():
        raise ValueError('benchmark_source_changed_during_run')
    provenance={'fixture_sha256':_hash_json(cases),'behavior_sha256':_hash_json(behavior),
        'python_version':platform.python_version(),**sources}
    report = {'report_schema_version':'1.0','mode':'offline-fixture-comparison','cases':results,
            'metrics':metrics,'suite_metrics':suites,'provenance':provenance,
            'case_count':len(results),'passed':sum(r['passed'] for r in results)}
    report['summary_markdown'] = render_summary(report)
    return report


def render_summary(report):
    """从同一次运行派生摘要，不复制轨迹或把夹具比较宣称真实模型性能。"""
    names={'rule_based':'规则基线','llm_only':'模型建议夹具','reops':'ReOps',
           'reops_without_memory':'ReOps（无Memory）'}
    lines=['# ReOps 离线策略比较', '',
           f"预期行为通过：{report['passed']}/{report['case_count']} 场景（每场景四种配置）。", '',
           '模型为固定响应夹具；没有真实API调用或恢复动作。恢复分母仅含初始明确故障，健康和模糊观测不计入。',
           '这些比例描述本组人工夹具，不能推广为真实模型性能；估计动作成本不代表API费用。', '',
           '| 配置 | 故障恢复 | 预期通过 | 误恢复 | 尝试 / 动作 |',
           '| --- | --- | --- | --- | --- |']
    for label,name in names.items():
        m=report['metrics'][label]
        lines.append(f"| {name} | {m['fixture_recovery_count']}/{m['fault_count']} | "
                     f"{m['expected_behavior_passed']}/{m['case_count']} | {m['false_recovery_count']} | "
                     f"{m['fixture_attempt_count']} / {m['fixture_action_count']} |")
    lines += ['', '| 场景组 | 规则恢复 | 模型夹具恢复 | ReOps恢复 | 无Memory恢复 |',
              '| --- | --- | --- | --- | --- |']
    for suite,metrics in report['suite_metrics'].items():
        values=[f"{metrics[label]['fixture_recovery_count']}/{metrics[label]['fault_count']}" for label in names]
        lines.append('| '+suite+' | '+' | '.join(values)+' |')
    differences=[]; failures=[]
    for case in report['cases']:
        methods=case['methods']
        current=methods['reops']['actual']; ablated=methods['reops_without_memory']['actual']
        if (current['strategy_sequence'],current['recovered']) != (ablated['strategy_sequence'],ablated['recovered']):
            differences.append(f"- {case['case_id']}：ReOps {' → '.join(current['strategy_sequence'])}"
                               f"（恢复={current['recovered']}），无Memory {' → '.join(ablated['strategy_sequence'])}"
                               f"（恢复={ablated['recovered']}）。")
        for label,method in methods.items():
            failed=[key for key,value in method['checks'].items() if not value]
            if failed:
                failures.append(f"- {case['case_id']} / {names[label]}：{', '.join(failed)}。")
    lines += ['', 'Memory消融产生行为差异的场景：', '', *(differences or ['无。']), '',
              '失败检查：', '', *(failures or ['无。']), '',
              f"fixture SHA256：{report['provenance']['fixture_sha256']}",
              f"行为 SHA256：{report['provenance']['behavior_sha256']}", '',
              '每场景的expected、actual、checks、候选评分及各attempt正式pipeline保存在同一JSON报告中。']
    return '\n'.join(lines)+'\n'


def _hash_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                    ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()


def _source_manifest():
    return {'source_sha256':{
        str(path.relative_to(PROJECT_ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((PROJECT_ROOT/'reops_agent').glob('*.py'))},
        'schema_sha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((PROJECT_ROOT/'shared').glob('*.schema.json'))}}


def _metrics(results):
    metrics={}
    for label in ('rule_based','llm_only','reops','reops_without_memory'):
        faults=[r for r in results if r['failure_detected']]
        verified=sum(r['methods'][label]['actual']['recovered'] for r in faults)
        metrics[label]={'fixture_recovery_count':verified,'fault_count':len(faults),
            'fixture_recovery_rate':verified/len(faults) if faults else None,
            'expected_behavior_passed':sum(r['methods'][label]['passed'] for r in results),
            'case_count':len(results),'fixture_model_calls':sum(r['methods'][label]['actual']['model_calls'] for r in results),
            'real_model_calls':0,'real_recovery_actions':0,'token_api_cost':None}
        metrics[label]['false_recovery_count']=sum(
            r['methods'][label]['actual']['recovered'] and not r['methods'][label]['expected']['recovered']
            for r in results)
        metrics[label].update(fixture_attempt_count=sum(r['methods'][label]['actual']['attempt_count'] for r in results),
            fixture_action_count=sum(r['methods'][label]['actual']['fixture_action_count'] for r in results),
            estimated_action_cost=round(sum(r['methods'][label]['actual']['estimated_action_cost'] for r in results),3),
            max_attempts_reached_count=sum(r['methods'][label]['actual']['final_status']=='max_attempts_reached' for r in results))
    return metrics


def _pipeline_result(result):
    return {key:result[key] for key in ('diagnosis','recovery_action','execution_result',
                                     'post_observation','verification_result','agent_event')}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',action='store_true',help='输出本次运行的中文Markdown摘要')
    args=parser.parse_args(argv)
    report=run_benchmark()
    save_report(report)
    if args.summary:
        if hasattr(sys.stdout,'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(report['summary_markdown'],end='')
    else:
        print(json.dumps({k:report[k] for k in ('mode','case_count','passed','metrics')},ensure_ascii=True,indent=2))
    return 0 if report['passed']==report['case_count'] else 1


def save_report(report):
    """完整同步后原子替换固定runtime报告；失败保留旧报告。"""
    runtime=(PROJECT_ROOT/'runtime').resolve()
    if not runtime.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError('benchmark_output_outside_project')
    runtime.mkdir(exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json.tmp',
                                         prefix='strategy-report-',dir=runtime,delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
            stream.flush();os.fsync(stream.fileno())
        temporary.replace(runtime/'strategy-benchmark.json')
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()


if __name__=='__main__':raise SystemExit(main())

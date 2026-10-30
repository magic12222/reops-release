"""Phase8显式离线候选：安全合格后评分，历史不能生成动作。"""
from copy import deepcopy
from .b_clock import utc_now
import math
from uuid import uuid4

from .contracts import validate
from .safety import check_action
from .advisory import _contradictory_metric_evidence

MODES = frozenset({'rule_based', 'llm_only', 'reops'})


def _unique_history(history):
    """重复事件只投一票；同 ID 内容冲突时整组弃用，不猜测哪条可信。"""
    events = {}
    conflicts = set()
    for item in history:
        if not isinstance(item, dict):
            continue
        event_id = item.get('event_id')
        if not isinstance(event_id, str) or not event_id.strip():
            continue
        if event_id in events and events[event_id] != item:
            conflicts.add(event_id)
        else:
            events[event_id] = item
    return [item for key, item in events.items() if key not in conflicts]


def _matching_history(item, diagnosis, signals, signature):
    historical = item.get('executed_action')
    old_diagnosis = item.get('diagnosis')
    old_observation = item.get('observation')
    if not all(isinstance(value, dict) for value in (historical, old_diagnosis, old_observation)):
        return False
    if type(item.get('recovered')) is not bool:
        return False
    status = item.get('verification_status')
    if not isinstance(status, str) or status not in {'recovered', 'not_recovered', 'inconclusive'}:
        return False
    execution_status = item.get('execution_status')
    if not isinstance(execution_status, str):
        return False
    if item['recovered'] != (status == 'recovered'):
        return False
    if item['recovered'] and item.get('execution_status') != 'succeeded':
        return False
    return (item.get('failure_type') == diagnosis['failure_type']
            and item.get('location') == diagnosis['location']
            and old_diagnosis.get('root_cause') == diagnosis['root_cause']
            and old_observation.get('offline_signals', {}) == signals
            and (historical.get('action'), historical.get('target'), historical.get('parameters')) == signature
            and item.get('execution_status') in {'succeeded', 'failed'})


def _commands(value):
    if isinstance(value, dict):
        return any(k.lower() in {'command', 'shell', 'script'} or _commands(v) for k,v in value.items())
    return isinstance(value, list) and any(_commands(v) for v in value)


def _component(target, observation):
    return 'api' if target == 'web' and 'api' in observation['services'] else target


def _stopped(name, observation):
    service = observation['services'].get(name, {})
    return (service.get('status') == 'unhealthy' and service.get('message') == 'stopped'
            and type(observation['metrics'].get(name+'_up')) in (int,float)
            and observation['metrics'][name+'_up'] == 0)


def _dependencies_healthy(observation):
    return all(observation['services'].get(n,{}).get('status') == 'healthy'
               and type(observation['metrics'].get(n+'_up')) in (int,float)
               and observation['metrics'][n+'_up'] == 1 for n in ('postgres','redis'))


def _resource_assessment(observation):
    """显式离线资源证据；运行中的api压力不能靠restart掩盖。"""
    signal = observation.get('offline_signals', {}).get('resource_pressure')
    if signal is None or observation['metrics'].get('api_up') != 1:
        return {'status':'none','sample_ids':[]}
    result = {'status':'insufficient','sample_ids':[]}
    if (not isinstance(signal, dict) or signal.get('component') != 'api'
            or not isinstance(signal.get('metric'),str) or signal['metric'] not in {'cpu','memory'}):
        return result
    ratio = observation['metrics'].get('api_'+signal['metric']+'_ratio')
    samples = signal.get('samples')
    if (type(ratio) not in (int,float) or not math.isfinite(ratio) or not 0 <= ratio <= 1
            or not isinstance(samples,list) or len(samples) != 2):
        return result
    for sample in samples:
        if (not isinstance(sample,dict) or not isinstance(sample.get('sample_id'),str)
                or not sample['sample_id'].strip() or type(sample.get('value')) not in (int,float)
                or not math.isfinite(sample['value']) or not 0 <= sample['value'] <= 1):
            return result
    ids = [s['sample_id'] for s in samples]
    if len(set(ids)) != 2:
        return result
    result['sample_ids'] = ids
    if ratio != samples[-1]['value'] or not all(s['value'] >= .95 for s in samples):
        result['status'] = 'conflicting'
    elif signal.get('persistent') is True:
        result['status'] = 'confirmed'
    return result


def resource_recovery_check(before, after):
    """业务正常之外，显式资源故障还须有低压力指标和已清除的压力信号。"""
    signal = before.get('offline_signals', {}).get('resource_pressure')
    required = _resource_assessment(before)['status'] != 'none'
    if not required:
        return {'required':False,'passed':True}
    if not isinstance(signal, dict) or not isinstance(signal.get('metric'),str) or signal['metric'] not in {'cpu','memory'}:
        return {'required':True,'passed':False}
    value = after['metrics'].get('api_'+signal['metric']+'_ratio')
    passed = (type(value) in (int,float) and math.isfinite(value) and 0 <= value < .95
              and _resource_assessment(after)['status']=='none')
    return {'required':True,'passed':passed}


def check_offline_action(action, observation, failed_actions=(), *, attempt_number=1, retry_limit=5):
    validate('recovery_action', action)
    validate('observation', observation)
    pair = action['action'],action['target']
    resource = _resource_assessment(observation)
    reason = None
    if _commands(action):
        reason = 'command_payload_rejected'
    elif any(action[k] != observation[k] for k in ('incident_id','trace_id')):
        reason = 'correlation_mismatch'
    elif observation.get('observation_conflicts') and pair not in {('no_action',None),('retry','web')}:
        reason = 'observation_conflict'
    elif type(attempt_number) is not int or type(retry_limit) is not int or not 1 <= attempt_number <= retry_limit <= 5:
        reason = 'retry_limit_exceeded'
    elif action['requires_approval'] or action['risk'] > .2:
        reason = 'policy_rejected'
    elif pair in failed_actions:
        reason = 'previously_failed_action'
    elif resource['status'] != 'none' and pair in {('restart_service','web'),('reconfigure','api')}:
        reason = 'resource_pressure_requires_manual_review' if resource['status']=='confirmed' else 'resource_evidence_requires_observation'
    elif action['action'] in {'restart_service','no_action'}:
        return check_action(action, observation, failed_actions, attempt_number=attempt_number, retry_limit=retry_limit)
    elif action['action'] == 'start_service' and action['target'] in {'web','postgres','redis'} and not action['parameters']:
        component = _component(action['target'],observation)
        if not _stopped(component,observation): reason = 'start_requires_stopped_evidence'
        elif action['target'] == 'web' and not _dependencies_healthy(observation): reason = 'dependency_not_healthy'
    elif pair == ('reconfigure','api') and action['parameters'] == {'profile':'normal'}:
        signals=observation.get('offline_signals',{})
        if observation['services'].get('api',{}).get('status') not in {'unhealthy','degraded'}:
            reason = 'target_failure_evidence_missing'
        elif (signals.get('database_profile') != 'bad_password' or not _dependencies_healthy(observation)
                or observation['metrics'].get('api_up') != 1):
            reason = 'configuration_evidence_missing'
    elif pair == ('retry','web') and not action['parameters']:
        signals=observation.get('offline_signals',{})
        if not (observation.get('observation_conflicts') or signals.get('transient') is True or resource['status'] in {'insufficient','conflicting'}
                or any(s['status']=='unknown' for s in observation['services'].values())):
            reason = 'reobserve_evidence_missing'
    else:
        reason = 'offline_candidate_not_whitelisted'
    return {'allowed':reason is None,'reason':reason or 'allowed_offline_only','action':pair[0],'target':pair[1]}


def _action(diagnosis, operation, target, parameters, prior, strategy):
    value={key:diagnosis[key] for key in ('schema_version','incident_id','trace_id')}
    value.update(action_id=f'action-{uuid4()}',diagnosis_id=diagnosis['diagnosis_id'],
        timestamp=utc_now().isoformat(),action=operation,target=target,
        parameters=parameters,reason='离线候选：'+strategy,expected_success=prior,
        estimated_cost=0 if operation in {'retry','no_action'} else .2,
        risk=0 if operation in {'retry','no_action'} else .2,requires_approval=False,
        decision_basis={'strategy':'offline_multi_candidate','selected_strategy':strategy})
    if 'case_id' in diagnosis:value['case_id']=diagnosis['case_id']
    validate('recovery_action',value)
    return value


def plan_candidates(diagnosis, observation, *, history=(), rca=None, mode='reops', failed_actions=(),
                    attempt_number=1, retry_limit=5, candidate_guard=None):
    if mode not in MODES:raise ValueError('unknown_offline_strategy_mode')
    history = _unique_history(history) if mode == 'reops' else ()
    signals=observation.get('offline_signals',{})
    resource = _resource_assessment(observation)
    specs=[]
    if diagnosis['failure_detected']:
        for name,target in (('postgres','postgres'),('redis','redis'),('api','web')):
            if _stopped(name,observation):
                specs.append(('start_service',target,{},.85,'start_'+target))
        if signals.get('database_profile')=='bad_password':
            specs.append(('reconfigure','api',{'profile':'normal'},.9,'restore_db_profile'))
        for name,target in (('postgres','postgres'),('api','web')):
            if observation['services'].get(name,{}).get('status') in {'unhealthy','degraded'}:
                specs.append(('restart_service',target,{},.70,'restart_'+target))
    if observation.get('observation_conflicts') or signals.get('transient') is True or any(s['status']=='unknown' for s in observation['services'].values()):
        specs.append(('retry','web',{},.88 if signals.get('transient') is True else .4,'reobserve'))
    elif resource['status'] in {'insufficient','conflicting'}:
        specs.append(('retry','web',{},.92,'reobserve'))
    specs.append(('no_action',None,{},0,'no_action'))
    candidates=[]
    for operation,target,parameters,prior,strategy in specs:
        action=_action(diagnosis,operation,target,parameters,prior,strategy)
        safety=check_offline_action(action,observation,failed_actions,attempt_number=attempt_number,retry_limit=retry_limit)
        if safety['allowed'] and candidate_guard is not None:
            safety = candidate_guard(action, observation)
        score=prior; evidence=[]
        if mode=='reops' and safety['allowed']:
            for item in history:
                if not _matching_history(item, diagnosis, signals, (operation,target,parameters)):
                    continue
                verified=(item.get('recovered') is True and item.get('verification_status')=='recovered'
                          and item.get('execution_status')=='succeeded')
                delta=.20 if verified else -.35
                evidence.append({'event_id':item['event_id'],'verified_success':verified,'score_delta':delta})
            # 历史数量不能无限压倒当前证据；保留逐事件原始票与实际应用的总分。
            memory_delta = max(-.35, min(.20, sum(e['score_delta'] for e in evidence)))
            score += memory_delta
        else:
            memory_delta = 0
        model_match=False
        if (rca and rca.get('source')=='provider' and rca.get('fallback_reason') is None
                and rca['result']['confidence']>=.7 and any(len(s.strip())>=8 for s in rca['result']['evidence'])):
            recommendation=rca['result']['suggested_action']
            affected=rca['result']['affected_component']
            affected='api' if affected=='web' else affected
            model_match=((recommendation['action'],recommendation['target'])==(operation,target)
                and (operation=='no_action' or affected==_component(target,observation))
                and not _contradictory_metric_evidence(rca['result']['evidence'],observation))
            if mode=='reops' and model_match and safety['allowed']:score+=.1
        candidates.append({'strategy_id':strategy,'action':action,'safety':safety,'prior_score':prior,
                           'score':round(score,3),'memory_evidence':evidence,
                           'memory_score_delta':round(memory_delta,3),'model_match':model_match})
    eligible=[c for c in candidates if c['safety']['allowed']]
    if mode=='llm_only':
        eligible=[c for c in eligible if c['model_match']]
    selected=max(eligible,key=lambda c:(c['score'],c['strategy_id'])) if eligible else candidates[-1]
    action=deepcopy(selected['action'])
    action['decision_basis'].update(mode=mode,offline_only=True,resource_assessment=resource,candidates=[{
        'strategy_id':c['strategy_id'],'action':c['action']['action'],'target':c['action']['target'],
        'parameters':c['action']['parameters'],'allowed':c['safety']['allowed'],'reason':c['safety']['reason'],
        'prior_score':c['prior_score'],'score':c['score'],'memory_evidence':c['memory_evidence'],
        'memory_score_delta':c['memory_score_delta'],
        'model_match':c['model_match']} for c in candidates])
    validate('recovery_action',action)
    return action


def simulate_candidate(action, observation, *, succeeds=True):
    from .executor import ExecutionOutcome
    post=deepcopy(observation)
    started=utc_now().isoformat()
    post.update(observation_id=f'obs-strategy-{uuid4()}',timestamp=started)
    if not check_offline_action(action,observation)['allowed']:raise ValueError('offline_execution_policy_rejected')
    strategy=action['decision_basis']['selected_strategy']
    signatures={'reobserve':('retry','web',{}),'restore_db_profile':('reconfigure','api',{'profile':'normal'}),
                'no_action':('no_action',None,{})}
    for target in ('web','postgres','redis'):
        signatures['start_'+target]=('start_service',target,{})
    for target in ('web','postgres'):
        signatures['restart_'+target]=('restart_service',target,{})
    if signatures.get(strategy)!=(action['action'],action['target'],action['parameters']):
        raise ValueError('offline_strategy_signature_mismatch')
    effect=observation.get('offline_effects',{}).get(strategy,{}) if succeeds and action['action']!='no_action' else {}
    if effect:
        for name,status in effect.get('services',{}).items():
            if name in post['services']:post['services'][name].update(status=status,message='offline strategy fixture')
        post['metrics'].update(effect.get('metrics',{}))
        if 'business_status' in effect:post['request']['status_code']=effect['business_status']
        if 'signals' in effect:post['offline_signals']=deepcopy(effect['signals'])
    status='skipped' if action['action']=='no_action' else 'succeeded' if succeeds else 'failed'
    validate('observation',post)
    details={'mode':'offline_mock','executed':status!='skipped','success':status=='succeeded',
             'action':action['action'],'target':action['target'],'started_at':started,'finished_at':started,
             'real_side_effects':False,'selected_strategy':strategy}
    return ExecutionOutcome(status,0 if status=='succeeded' else 1 if status=='failed' else None,
                            None,None,0.0,post,details)

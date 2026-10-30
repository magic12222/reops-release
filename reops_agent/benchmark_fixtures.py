"""离线策略fixtures的输入契约；不修改shared，也不产生外部动作。"""
import json
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

METHODS = ('rule_based','llm_only','reops','reops_without_memory')
STRATEGIES = ('no_action','reobserve','restore_db_profile','start_web','start_postgres',
              'start_redis','restart_web','restart_postgres')
EXPECTED = {'type':'object','required':['strategy','recovered'],'additionalProperties':False,
    'properties':{'strategy':{'enum':list(STRATEGIES)},'recovered':{'type':'boolean'},
        'strategy_sequence':{'type':'array','minItems':1,'maxItems':5,'items':{'enum':list(STRATEGIES)}},
        'attempt_count':{'type':'integer','minimum':1,'maximum':5},
        'fixture_action_count':{'type':'integer','minimum':0,'maximum':5},
        'memory_evidence_count':{'type':'integer','minimum':0},
        'model_calls':{'type':'integer','minimum':0,'maximum':5},
        'final_status':{'enum':['healthy','recovered','no_safe_candidate','max_attempts_reached','safety_rejected']}}}
SUGGESTION = {'type':'array','prefixItems':[{'type':'string','minLength':1},{'type':['string','null']}],
              'minItems':2,'maxItems':2}
SCHEMA = {'type':'object','required':['id','state','effects','expected'],'additionalProperties':False,
    'properties':{'id':{'type':'string','pattern':'^[a-z][a-z0-9_]{0,63}$'},
        'state':{'enum':['healthy','api_down','postgres_down','redis_abnormal','health_failure',
                         'configuration_failure','resource_failure','ambiguous']},
        'suite':{'enum':['design','robustness','multiround','resource']},
        'signals':{'type':'object'},'metrics':{'type':'object','additionalProperties':{'type':'number'}},
        'effects':{'type':'object','additionalProperties':False,'properties':{
            strategy:{'type':'object','additionalProperties':False,'properties':{
                'services':{'type':'object','additionalProperties':False,'properties':{
                    name:{'enum':['healthy','unhealthy','degraded','unknown']} for name in ('api','postgres','redis')}},
                'metrics':{'type':'object','additionalProperties':{'type':'number'}},
                'business_status':{'type':['integer','null']},'signals':{'type':'object'}}}
            for strategy in STRATEGIES}},
        'expected':{'type':'object','required':list(METHODS),'additionalProperties':False,
                    'properties':{method:EXPECTED for method in METHODS}},
        'suggestion':SUGGESTION,'suggestions':{'type':'array','minItems':1,'maxItems':5,'items':SUGGESTION},
        'max_attempts':{'type':'integer','minimum':1,'maximum':5},
        'confidence':{'type':'number','minimum':0,'maximum':1},
        'evidence':{'type':'array','items':{'type':'string'},'minItems':1},
        'affected_component':{'type':['string','null']},
        'malformed':{'type':'boolean'},'dependent_api_unhealthy':{'type':'boolean'},
        'memory_seed':{'enum':['failed_start','verified_restart']},
        'memory_transform':{'enum':['replay','conflict','changed_context']}},
    'allOf':[{'if':{'required':['memory_transform']},'then':{'required':['memory_seed']}},
             {'if':{'required':['memory_seed']},'then':{'properties':{'state':{'not':{'enum':['healthy','ambiguous']}}}}}]}
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def validate_case(case):
    try:
        # JSON roundtrip rejects nonfinite constants even in extension signals.
        json.dumps(case, allow_nan=False)
        VALIDATOR.validate(case)
        maximum=case.get('max_attempts',1)
        for expected in case['expected'].values():
            if expected.get('attempt_count',1)>maximum or len(expected.get('strategy_sequence',[]))>maximum:
                raise ValueError('expected_attempt_budget_mismatch')
    except (ValueError, TypeError, ValidationError):
        raise ValueError('invalid_strategy_fixture') from None


def strict_load(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate_strategy_fixture_field')
            result[key]=value
        return result
    def constant(value):raise ValueError('nonfinite_strategy_fixture')
    try:
        result=json.loads(text,object_pairs_hook=unique,parse_constant=constant)
        if not isinstance(result,list) or not result:raise ValueError('empty_strategy_fixture_suite')
        for case in result:validate_case(case)
        return result
    except (ValueError, TypeError):
        raise ValueError('invalid_strategy_fixture_suite') from None

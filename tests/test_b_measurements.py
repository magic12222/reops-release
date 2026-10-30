"""J-01 原始传输证据、关闭/迟到、恢复计时和 incident 分母；全部离线。"""

from copy import deepcopy
import json
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock, patch

import httpx
import pytest

from reops_agent.measurements import AttemptMeasurement, CURRENT, measured_transport, strict_usage, summarize_incidents
from reops_agent.nexent_provider import NexentConfig, NexentRCAProvider
from reops_agent.rca import RCAAgent
from reops_agent.recovery_smoke import _SingleModelCall
from test_recovery_smoke import observation, provider, run, rig


def meter(clock=None):
    return AttemptMeasurement(observation(), source="offline_fixture", clock=clock)


def test_rca_timeout_freezes_model_measurements_before_planning():
    from threading import Event
    from reops_agent import diagnose
    from reops_agent.advisory import BoundedProvider
    entered, release, finished = Event(), Event(), Event()
    measurement = meter()
    class Delayed:
        def complete(self, request, *, timeout_seconds):
            entered.set()
            release.wait(2)
            try:
                return provider().complete({}, timeout_seconds=1)
            finally:
                finished.set()
    wrapped = BoundedProvider(_SingleModelCall(Delayed(), measurement))
    pre = observation()
    try:
        result = RCAAgent(wrapped, timeout_seconds=.05).analyze(pre, diagnose(pre))
        assert entered.is_set() and result["fallback_reason"] == "provider_timeout"
        assert measurement.model_closed and measurement.budget_timeouts == 1
        before = measurement.close()
    finally:
        release.set()
    assert finished.wait(2)
    assert measurement.close() == before
    assert before["text_successes"] == before["rca_schema_successes"] == 0


@pytest.mark.parametrize("value", (None, {}, {"prompt_tokens":True,"completion_tokens":1},
    {"prompt_tokens":-1,"completion_tokens":2}, {"prompt_tokens":1.2,"completion_tokens":2},
    {"prompt_tokens":1,"completion_tokens":2,"total_tokens":8},
    {"prompt_tokens":1,"completion_tokens":2,"total_tokens":True}))
def test_bad_or_missing_usage_is_not_a_measurement(value):
    assert strict_usage(value) is None


def fake_model(config, timeout, measurement, body, *, sse=False, status=200):
    transport = httpx.MockTransport(lambda request: httpx.Response(status,
        headers={"content-type": "text/event-stream" if sse else "application/json"}, content=body))
    client = httpx.Client(transport=measured_transport(transport, measurement), trust_env=False)
    class Model:
        def __call__(self, *args, **kwargs):
            response = client.post("https://offline.invalid/v1/chat/completions", json={})
            response.raise_for_status()
            # SDK 的估算字段故意存在；生产 provider 不允许将其冒充原始 usage。
            return SimpleNamespace(content=provider().complete({},timeout_seconds=1),
                                   tool_calls=None, token_usage={"input_tokens":99999,"output_tokens":99999})
    model = Model()
    model.client = client
    return model


@pytest.mark.parametrize("sse", (False, True))
def test_nexent_string_interface_and_raw_server_usage(sse):
    measurement = meter()
    usage = {"prompt_tokens":3,"completion_tokens":5,"total_tokens":8}
    raw = json.dumps({"usage":usage}).encode()
    body = b"data: " + raw + b"\n\ndata: [DONE]\n\n" if sse else raw
    config = NexentConfig("https://offline.invalid/v1","offline-model","offline-test-key",enable_real_model=True)
    wrapped = _SingleModelCall(NexentRCAProvider(config), measurement)
    pre = observation()
    from reops_agent import diagnose
    def factory(config, timeout):
        assert CURRENT.get() is measurement
        return fake_model(config, timeout, measurement, body, sse=sse)
    with patch("reops_agent.nexent_provider._create_model", side_effect=factory):
        rca = RCAAgent(wrapped).analyze(pre, diagnose(pre), [])
    measurement.close_model(rca)
    result = measurement.close()
    assert result["provider_attempts"] == result["http_requests"] == result["http_successes"] == 1
    assert result["text_successes"] == result["rca_schema_successes"] == 1
    assert result["usage"] == {"input_tokens":3,"output_tokens":5,"source":"server_usage"}
    assert result["cost"] is None and result["requests"][0]["request_id"]
    assert CURRENT.get() is None


def test_production_sdk_factory_installs_scoped_transport():
    from reops_agent.nexent_provider import _create_model
    from reops_agent.measurements import measurement_scope
    paths=("nexent","nexent.core","nexent.core.models","nexent.core.models.retry",
           "nexent.core.utils","nexent.core.utils.observer","nexent.monitor")
    modules={path:ModuleType(path) for path in paths}
    constructor=Mock()
    modules["nexent.core.models"].OpenAIModel=constructor
    modules["nexent.core.models.retry"].ModelRetryConfig=Mock()
    modules["nexent.core.utils.observer"].MessageObserver=Mock()
    modules["nexent.monitor"].get_monitoring_manager=lambda:SimpleNamespace(is_enabled=False)
    raw=httpx.MockTransport(lambda request:httpx.Response(200,json={"usage":{
        "prompt_tokens":1,"completion_tokens":2}}))
    measurement=meter();measurement.begin_model(2)
    config=NexentConfig("https://offline.invalid/v1","offline-model","offline-test-key",enable_real_model=True)
    with patch.dict("sys.modules",modules),patch("httpx.HTTPTransport",return_value=raw),measurement_scope(measurement):
        _create_model(config,1)
        client=constructor.call_args.kwargs["client_kwargs"]["http_client"]
        client.get("https://offline.invalid");client.close()
    assert measurement.close()["usage"]["input_tokens"]==1


@pytest.mark.parametrize("body", (b'{}', b'{"usage":{"prompt_tokens":true,"completion_tokens":2}}',
    b'{"usage":{"prompt_tokens":1,"prompt_tokens":3,"completion_tokens":2}}'))
def test_transport_without_reliable_usage_remains_null(body):
    measurement = meter()
    measurement.begin_model(1)
    model = fake_model(None,None,measurement,body)
    model()
    model.client.close()
    result = measurement.close()
    assert result["http_requests"] == result["http_successes"] == 1
    assert result["usage"] is None


def test_split_sse_repeated_usage_is_not_double_counted():
    measurement=meter();measurement.begin_model(1)
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            raw=b'data: {"usage":{"prompt_tokens":2,"completion_tokens":4}}\n\n'
            yield raw[:16]
            yield raw[16:]+raw+b'data: [DONE]\n\n'
    with httpx.Client(transport=measured_transport(httpx.MockTransport(lambda request:
        httpx.Response(200,headers={"content-type":"text/event-stream"},stream=Chunks())),measurement)) as client:
        client.get("https://offline.invalid")
    assert measurement.close()["usage"]["input_tokens"]==2


def test_conflicting_sse_usage_and_incomplete_stream_are_unknown():
    for raw in (b'data: {"usage":{"prompt_tokens":2,"completion_tokens":4}}\n\n',
                b'data: {"usage":{"prompt_tokens":2,"completion_tokens":4}}\n\n'
                b'data: {"usage":{"prompt_tokens":3,"completion_tokens":4}}\n\ndata: [DONE]\n\n'):
        measurement=meter();measurement.begin_model(1)
        model=fake_model(None,None,measurement,raw,sse=True)
        model();model.client.close()
        assert measurement.close()["usage"] is None


def test_transport_timeout_is_distinct_from_outer_budget_and_null_usage():
    measurement=meter();measurement.begin_model(1)
    def timeout(request):
        raise httpx.ReadTimeout("must-not-be-recorded",request=request)
    with httpx.Client(transport=measured_transport(httpx.MockTransport(timeout),measurement)) as client:
        with pytest.raises(httpx.ReadTimeout):client.get("https://offline.invalid")
    measurement.close_model({"source":"rule_based","fallback_reason":"provider_error"})
    result=measurement.close()
    assert result["timeouts"]=={"provider_budget":0,"transport":1}
    assert result["http_requests"]==1 and result["http_successes"]==0 and result["usage"] is None
    assert "must-not-be-recorded" not in json.dumps(result)


def test_retries_count_each_request_and_missing_usage_prevents_partial_total():
    measurement=meter();measurement.begin_model(1)
    replies=iter((httpx.Response(500,content=b'{}'),httpx.Response(200,json={"usage":{
        "prompt_tokens":2,"completion_tokens":3}})))
    with httpx.Client(transport=measured_transport(httpx.MockTransport(lambda request:next(replies)),measurement)) as client:
        client.get("https://offline.invalid");client.get("https://offline.invalid")
    result=measurement.close()
    assert result["http_requests"]==2 and result["http_successes"]==1
    assert result["usage"] is None and result["requests"][1]["usage"]["input_tokens"]==2


def test_closed_attempt_cannot_accept_late_or_foreign_results():
    measurement=meter();measurement.begin_model(1);measurement.bind_transport()
    key=measurement.request_started()
    measurement.close_model({"source":"rule_based","fallback_reason":"provider_timeout"})
    first=measurement.close()
    measurement.response_finished(key,200,{"input_tokens":9,"output_tokens":8})
    measurement.text_returned("late text")
    assert measurement.close()==first and first["timeouts"]["provider_budget"]==1
    assert first["text_successes"]==first["rca_schema_successes"]==0
    other=meter();other.begin_model(1);other.bind_transport()
    other.response_finished(key,200,{"input_tokens":9,"output_tokens":8})
    assert other.close()["http_requests"]==0


@pytest.mark.parametrize("bad", (True,float("nan"),float("inf"),-1))
def test_invalid_clock_is_missing_not_a_zero_latency(bad):
    measurement=meter(lambda:bad)
    measurement.command_started("start");measurement.recovered(True,["obs-a","obs-b"])
    result=measurement.close()
    assert result["recovery_latency_ms"] is None and result["recovery_timing"]["start"] is None
    json.dumps(result,allow_nan=False)


def test_exact_new_latency_boundary_and_close_before_audit(rig, monkeypatch):
    from reops_agent.measurements import CURRENT
    times=iter((10,15))
    original=AttemptMeasurement.command_started
    def command(self,operation):
        self.clock=lambda:next(times)
        self.last_clock=None
        return original(self,operation)
    monkeypatch.setattr(AttemptMeasurement,"command_started",command)
    previous=rig[1].restart
    def restart(*args,**kwargs):
        CURRENT.get().command_started("restart")
        return previous(*args,**kwargs)
    rig[1].restart=restart
    record=rig[3].record
    def audit(stage,step,status,data):
        if step=="verify":
            assert times.__length_hint__()==0  # 终点在 Verify audit 之前捕获。
        return record(stage,step,status,data)
    rig[3].record=audit
    report=run(rig,execute_recovery=True)
    result=report["measurements"]
    assert report["recovery_verified"] is True and result["recovery_latency_ms"]==5000
    assert len(set(result["recovery_timing"]["verify_observation_ids"]))==2
    assert result["source"]=="offline_fixture" and result["closed"] is True


def test_no_command_hook_or_denied_action_does_not_fabricate_latency(rig):
    report=run(rig,execute_recovery=True)
    assert report["recovery_verified"] and report["measurements"]["recovery_latency_ms"] is None
    assert report["measurements"]["provider_attempts"]==report["model_calls"]==1
    assert report["measurements"]["http_requests"] is None


def test_model_authorization_denied_counts_zero_attempts(rig):
    rig[2].confirm=lambda *args:None
    report=run(rig,execute_recovery=True)
    assert report["measurements"]["provider_attempts"]==0
    assert report["measurements"]["http_requests"] is None


def test_invalid_json_is_text_success_but_not_schema_success(rig):
    report=run(rig,model=Mock(complete=Mock(return_value="not JSON")))
    assert report["measurements"]["text_successes"]==1
    assert report["measurements"]["rca_schema_successes"]==0


def sample(incident="i",trace="t",**changes):
    result={"incident_id":incident,"trace_id":trace,"phase":"8","fault_injection_attempted":True,
        "incident_started": True,
        "recovery_verified":False,"execution_outcome":"failed"}
    result.update(changes)
    result["recovery_executed"] = result["execution_outcome"] == "succeeded"
    return result


def test_expired_transport_completion_is_ignored_even_before_close():
    values=iter((10,10.1,12))
    measurement=meter(lambda:next(values));measurement.begin_model(1);measurement.bind_transport()
    key=measurement.request_started()
    measurement.response_finished(key,200,{"input_tokens":9,"output_tokens":8})
    result=measurement.close()
    assert result["http_successes"]==0 and result["usage"] is None
    assert result["timeouts"]["transport"] is None


def test_raw_stream_gzip_is_decoded_without_changing_sdk_bytes():
    import gzip
    body=gzip.compress(b'{"usage":{"prompt_tokens":2,"completion_tokens":4}}')
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:8]
            yield body[8:]
    measurement=meter();measurement.begin_model(1)
    with httpx.Client(transport=measured_transport(httpx.MockTransport(lambda request:
        httpx.Response(200,headers={"content-encoding":"gzip","content-type":"application/json"},stream=Chunks())),measurement)) as client:
        response=client.get("https://offline.invalid")
        assert response.json()["usage"]["prompt_tokens"]==2
    assert measurement.close()["usage"]["output_tokens"]==4


def test_fixed_docker_command_hook_follows_identity_checks(monkeypatch):
    from reops_agent.docker_executor import LocalDocker
    from reops_agent.measurements import measurement_scope
    measurement=meter(lambda:10)
    monkeypatch.setattr("reops_agent.docker_executor.find_docker",lambda:"offline-docker")
    calls=[]
    def runner(command,**kwargs):
        assert measurement.command_start==10
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout="",stderr="")
    backend=LocalDocker(runner)
    backend.container=Mock(return_value=("a"*64,{"Running":False,"Status":"exited"}))
    with measurement_scope(measurement):
        backend.restart("web",expected_container_id="a"*64)
    assert calls==[["offline-docker","restart","--time","10","a"*64]]
    assert measurement.close()["recovery_latency_ms"] is None


def test_clock_rollback_and_multiple_commands_never_create_success_latency():
    for values in ((20,10),(10,11)):
        values=iter(values);measurement=meter(lambda:next(values))
        measurement.command_started("start")
        if values.__length_hint__():
            measurement.command_started("restart")
        measurement.recovered(True,["a","b"])
        assert measurement.close()["recovery_latency_ms"] is None


def test_single_command_clock_rollback_is_not_a_measured_success():
    values=iter((20,10));measurement=meter(lambda:next(values))
    measurement.command_started("start");measurement.recovered(True,["a","b"])
    result=measurement.close()
    assert result["recovery_latency_ms"] is None and result["recovery_timing"]["clock_valid"] is False


def test_success_latency_requires_complete_same_clock_proof():
    values=iter((10,11));measurement=meter(lambda:next(values))
    measurement.command_started("start");measurement.recovered(True,["a","b"])
    data=measurement.close()
    report=sample(data["incident_id"],data["trace_id"],recovery_verified=True,
                  execution_outcome="succeeded",measurements=data)
    result=summarize_incidents([report],{report["incident_id"]:True})
    assert result["latency_valid"]==1 and result["mean_success_latency_ms"]==1000
    broken=deepcopy(report);broken["measurements"]["recovery_timing"]["clock_id"]="another-process"
    result=summarize_incidents([broken],{report["incident_id"]:True})
    assert result["latency_missing"]==1 and result["mean_success_latency_ms"] is None


def test_summary_does_not_parse_historical_or_malformed_measurement_as_zero():
    report=sample(recovery_verified=True,execution_outcome="succeeded",measurements=[])
    result=summarize_incidents([report],{"i":True})
    assert result["latency_missing"]==1 and result["mean_success_latency_ms"] is None


def test_missing_started_proof_and_invalid_success_do_not_enter_statistics():
    legacy=sample(incident_started=None)
    result=summarize_incidents([legacy],{"i":True})
    assert result["eligible"]==0 and result["missing"]==1 and result["success_rate"] is None
    impossible=sample(recovery_verified=True,execution_outcome="not_run")
    result=summarize_incidents([impossible],{"i":True})
    assert result["conflict"]==1 and result["succeeded"]==0


def test_incident_denominator_dedup_retry_and_missing_values():
    first=sample()
    second=sample(trace="retry",recovery_verified=True,execution_outcome="succeeded")
    denied=sample("denied",execution_outcome="not_run")
    unknown=sample("unknown",execution_outcome="unknown")
    queued=sample("queued",fault_injection_attempted=False,incident_started=False)
    result=summarize_incidents([first,first,second,denied,unknown,queued],
        {"i":True,"denied":True,"unknown":True,"queued":True,"missing":True,"excluded":False})
    assert result["eligible"]==result["valid"]==3 and result["succeeded"]==1
    assert result["denied"]==result["unknown"]==result["missing"]==1
    assert result["success_rate"] is None  # 事前清单有缺失，不能只报已知子集成绩。
    assert result["latency_missing"]==1 and result["mean_success_latency_ms"] is None


def test_conflicting_same_trace_and_mixed_groups_are_not_hidden():
    result=summarize_incidents([sample(),sample(recovery_verified=True)],{"i":True})
    assert result["conflict"]==1 and result["valid"]==0 and result["success_rate"] is None
    with pytest.raises(ValueError,match="groups"):
        summarize_incidents([sample(),sample("other",phase="8B")],{"i":True,"other":True})
    with pytest.raises(ValueError):summarize_incidents([],{"i":1})


@pytest.mark.parametrize("outcome", [None, "unknown", "invalid", False])
def test_missing_or_invalid_execution_remains_unknown_across_retry(outcome):
    first = sample(execution_outcome=outcome)
    if outcome is None:
        first.pop("execution_outcome")
    success = sample(trace="retry", execution_outcome="succeeded", recovery_verified=True)
    for reports in ([first], [first, success], [success, first]):
        result = summarize_incidents(reports, {"i": True})
        assert result["unknown"] == 1 and result["failed"] == result["succeeded"] == 0
        assert result["latency_valid"] == result["latency_missing"] == 0


@pytest.mark.parametrize("status", [None, "inconclusive", "not_run", "not_recovered"])
def test_command_success_requires_explicit_verify_failure_to_count_failed(status):
    report = sample(execution_outcome="succeeded", verification_status=status)
    result = summarize_incidents([report], {"i": True})
    assert result["failed"] == (status == "not_recovered")
    assert result["unknown"] == (status != "not_recovered")


def test_conflict_suppresses_rate_even_with_other_success_and_preserves_denominator():
    success = sample("success", execution_outcome="succeeded", recovery_verified=True)
    a, b = sample(), sample(verification_status="not_recovered")
    for reports in ([a, b, success], [success, b, a]):
        result = summarize_incidents(reports, {"i": True, "success": True})
        assert result["eligible"] == 2 and result["valid"] == result["conflict"] == 1
        assert result["succeeded"] == 1 and result["success_rate"] is None


def test_complete_plan_keeps_known_denied_unknown_and_failure_in_denominator():
    reports = [sample("ok", execution_outcome="succeeded", recovery_verified=True),
               sample("failure"), sample("denied", execution_outcome="not_run"),
               sample("unknown", execution_outcome="unknown")]
    result = summarize_incidents(reports, {report["incident_id"]: True for report in reports})
    assert result["eligible"] == result["valid"] == 4
    assert result["succeeded"] == result["failed"] == result["denied"] == result["unknown"] == 1
    assert result["success_rate"] == .25


def test_conflicting_start_proof_is_order_independent():
    yes, no = sample(), sample(incident_started=False)
    for reports in ([yes, no], [no, yes]):
        result = summarize_incidents(reports, {"i": True})
        assert result["eligible"] == result["conflict"] == 1
        assert result["valid"] == 0 and result["success_rate"] is None

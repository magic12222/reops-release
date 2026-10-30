"""使用既有诊断流程验证执行后的 Observation。"""

from datetime import datetime
from .b_clock import utc_now
from typing import Any

from .pipeline import diagnose
from .contracts import validate
from jsonschema.exceptions import ValidationError


def post_observation_error(before, after):
    """通用闭环的关联/新ID/时间顺序；离线历史不施加当前墙钟限制。"""
    try:
        validate('observation',after)
        if any(after[key] != before[key] for key in ('incident_id','trace_id')):
            return 'post_observation_correlation_mismatch'
        if after['observation_id'] == before['observation_id']:
            return 'post_observation_id_reused'
        if after['observation_id'].startswith('obs-unavailable-'):
            return 'post_observation_synthetic'
        timestamps=[datetime.fromisoformat(value['timestamp'].replace('Z','+00:00'))
                    for value in (before,after)]
        if any(value.utcoffset() is None for value in timestamps):
            return 'post_observation_timezone_missing'
        if timestamps[1] < timestamps[0]:
            return 'post_observation_time_reversed'
    except (ValidationError,ValueError,TypeError,KeyError):
        return 'post_observation_invalid'
    return None


def verify(observation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    verification_diagnosis = diagnose(observation)
    fault_cleared = not verification_diagnosis["failure_detected"]
    status_code = observation["request"].get("status_code")
    business_request_passed = status_code is not None and 200 <= status_code < 400
    services_healthy = all(
        service["status"] == "healthy" for service in observation["services"].values()
    )
    health_check_passed = services_healthy and business_request_passed
    recovered = fault_cleared and health_check_passed
    evidence = list(verification_diagnosis["evidence"])
    evidence.append("Verify 未检测到故障" if fault_cleared else "Verify 仍检测到故障")
    evidence.append("服务健康与请求成功证据齐全" if health_check_passed
                    else "服务健康或请求成功证据不足，不确认恢复")
    verification = {
        "status": "recovered" if recovered else "not_recovered",
        "checked_at": utc_now().isoformat(),
        "health_check_passed": health_check_passed,
        "fault_cleared": fault_cleared,
        "business_request_passed": business_request_passed,
        "evidence": evidence,
    }
    return verification_diagnosis, verification, recovered

"""Phase 7D 只读就绪审计；不创建 provider，不注入或恢复，不输出配置值。"""

import json

from .docker_executor import DockerBoundaryError, LocalDocker
from .model_preflight import preflight
from .nexent_provider import NexentConfig
from .recovery_smoke import _fresh, _healthy, _scope, context


def model_readiness():
    report = preflight()
    try:
        config = NexentConfig.from_env()
        report["phase7d_model_scope_valid"] = (
            config.api_base.rstrip("/") == "http://aigw.dlut.edu.cn/v1"
            and config.model_id == "DeepSeek-V3.1-W8A8")
    except Exception:
        report["phase7d_model_scope_valid"] = False
    return report


def audit(*, backend=None, model_check=model_readiness):
    report = {"phase": "7D", "mode": "read-only", "model_calls": 0,
              "recovery_actions": 0, "engine_accessible": False, "scope_valid": False,
              "observation_valid": False, "baseline_healthy": False,
              "local_preconditions_ready": False, "online_acceptance_passed": False,
              "fresh_human_authorizations_required": True}
    model = model_check()
    report["model"] = {key: model[key] for key in (
        "base_url_configured", "model_configured", "credential_present", "real_model_enabled",
        "configuration_valid", "nexent_import_ok", "sdk_telemetry_disabled", "local_configuration_ready",
        "phase7d_model_scope_valid")}
    backend = backend or LocalDocker()
    try:
        backend.check_local()
        report["engine_accessible"] = True
        _scope(backend)
        report["scope_valid"] = True
        observation = backend.observe(context())
        _fresh(observation, observation)
        report.update(observation_valid=True, baseline_healthy=_healthy(observation),
            services={name: observation["services"].get(name, {}).get("status")
                      for name in ("api", "postgres", "redis")},
            business_status=observation["request"].get("status_code"))
        report["local_preconditions_ready"] = (report["baseline_healthy"]
            and model["local_configuration_ready"] and model["phase7d_model_scope_valid"])
    except DockerBoundaryError as error:
        # Fixed internal boundary categories only; never dump raw exception text.
        known = {"docker_engine_unavailable", "docker_unavailable", "docker_timeout_state_uncertain",
                 "remote_docker_forbidden", "test_service_missing_or_ambiguous", "container_ownership_mismatch",
                 "test_api_port_binding_mismatch", "phase7d_scope_rejected", "compose_mapping_mismatch"}
        report["docker_error"] = str(error) if str(error) in known else "docker_boundary_rejected"
    except Exception:
        report["docker_error"] = "readiness_observation_failed"
    return report


def main():
    report = audit()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["local_preconditions_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

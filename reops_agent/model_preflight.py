"""离线模型接入检查：不创建模型、不请求网络、不读取 .env。"""

import argparse
import importlib
import json
import os
from urllib.parse import urlsplit

from .nexent_provider import NexentConfig, _private_sdk_logs


def preflight(env=None, *, resources_confirmed=False, credential_confirmed=False,
              quota_confirmed=False):
    env = os.environ if env is None else env
    present = lambda name: bool(env.get(name, "").strip())
    try:
        dlut_gateway = urlsplit(env.get("NEXENT_API_BASE", "")).hostname == "aigw.dlut.edu.cn"
    except ValueError:
        dlut_gateway = False
    resource_status = "confirmed_by_operator" if resources_confirmed else "UNVERIFIED"
    result = {
        "provider": "nexent",
        "provider_configured": present("NEXENT_API_BASE") and present("NEXENT_MODEL_ID"),
        "base_url_configured": present("NEXENT_API_BASE"),
        "model_configured": present("NEXENT_MODEL_ID"),
        "credential_present": present("NEXENT_API_KEY"),
        "credential_source": "process_environment:NEXENT_API_KEY" if present("NEXENT_API_KEY") else "missing",
        "real_model_enabled": env.get("REOPS_ENABLE_REAL_MODEL") == "1",
        "configuration_valid": False,
        "configuration_error": None,
        "nexent_import_ok": False,
        "sdk_telemetry_disabled": False,
        "network_check": "skipped",
        "network_check_skipped": True,
        "real_inference_performed": False,
        "model_service_endpoint": resource_status,
        "model_service_resource": resource_status,
        "huawei_endpoint": "not_applicable" if dlut_gateway else resource_status,
        "huawei_model_resource": "not_applicable" if dlut_gateway else resource_status,
        "credential_validity": "confirmed_by_operator" if credential_confirmed else ("unknown" if present("NEXENT_API_KEY") else "missing"),
        "competition_quota": "confirmed_by_operator" if quota_confirmed else "UNVERIFIED",
        "ready_for_real_model_smoke": False,
    }
    try:
        NexentConfig.from_env(env)
        result["configuration_valid"] = True
    except Exception:
        # 只记录类别，不记录异常/URL/Key/model 值。
        result["configuration_error"] = "invalid_or_missing_configuration"
    try:
        with _private_sdk_logs():
            models = importlib.import_module("nexent.core.models")
            retry = importlib.import_module("nexent.core.models.retry")
            observer = importlib.import_module("nexent.core.utils.observer")
            monitor = importlib.import_module("nexent.monitor")
            result["sdk_telemetry_disabled"] = not monitor.get_monitoring_manager().is_enabled
            result["nexent_import_ok"] = all(callable(value) for value in (
                models.OpenAIModel, retry.ModelRetryConfig, observer.MessageObserver))
    except Exception:
        pass
    result["local_configuration_ready"] = (result["configuration_valid"] and result["nexent_import_ok"]
                                           and result["sdk_telemetry_disabled"])
    result["ready_for_real_model_smoke"] = bool(
        result["local_configuration_ready"] and result["real_model_enabled"]
        and resources_confirmed and credential_confirmed and quota_confirmed)
    return result


def add_confirmation_arguments(parser):
    parser.add_argument("--resources-confirmed", action="store_true", help="人工已确认当前 endpoint/model 权限")
    parser.add_argument("--credential-confirmed", action="store_true", help="人工已确认模型服务凭据有效")
    parser.add_argument("--quota-confirmed", action="store_true", help="人工已确认当前资源额度适用且足够")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_confirmation_arguments(parser)
    args = parser.parse_args(argv)
    result = preflight(**vars(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["local_configuration_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

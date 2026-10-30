from infra.monitoring.observer import identifier, now

CASES = {
    "F01": {"component": "postgres", "root_cause": "service_down", "recovery": "start_service"},
    "F02": {"component": "api", "root_cause": "bad_database_password", "recovery": "reconfigure"},
    "F03": {"component": "redis", "root_cause": "service_down", "recovery": "start_service"},
}


def inject_fault(tools, fault_id, context):
    if fault_id not in CASES:
        raise ValueError("Supported fault IDs: F01, F02, F03")
    case = CASES[fault_id]
    output = tools.set_database_profile("bad_password") if fault_id == "F02" else tools.stop_service(case["component"])
    return {"injection_id": identifier("injection"), "fault_id": fault_id, **context,
            "timestamp": now(), "status": "injected" if output["exit_code"] == 0 else "failed",
            "ground_truth": dict(case), "execution": output}

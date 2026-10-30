"""A+B host: default read-only target check; --watch and --execute are explicit."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from threading import Thread
import time

import uvicorn

from reops_agent.contracts import PROJECT_ROOT
from reops_agent.nexent_provider import NexentConfig, NexentRCAProvider
from .a_monitor import TargetMonitor
from .b_service import WorkbenchHost, create_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Explicitly monitor and process new A samples")
    parser.add_argument("--execute", action="store_true", help="Request original per-action human authorization when a fault occurs")
    parser.add_argument("--model", action="store_true", help="Use existing configured Nexent model, original model Gate still required")
    parser.add_argument("--serve", action="store_true", help="Serve existing read-only snapshot in this same process")
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--directory", type=Path, default=PROJECT_ROOT / "runtime/workbench-b")
    args = parser.parse_args(argv)
    if args.execute and not args.watch:
        parser.error("--execute requires --watch")
    if not 1024 <= args.port <= 65535:
        parser.error("port must be within 1024..65535")
    if not args.watch and not args.serve:
        monitor = TargetMonitor()
        try:
            monitor.select()
            print(monitor.read_targets().model_dump_json(indent=2))
            return 0
        except Exception:
            print(json.dumps({"status": "not_connected", "error": "a_target_unavailable_check_docker_and_ownership"}))
            return 2
        finally:
            monitor.close()
    provider, model = None, "unknown"
    if args.model:
        try:
            config = replace(NexentConfig.from_env(), max_output_tokens=512)
            config.require_real_model()
            provider, model = NexentRCAProvider(config), config.model_id
        except Exception:
            print(json.dumps({"status": "not_connected", "error": "model_configuration_unavailable_or_disabled"}))
            return 2
    host = WorkbenchHost(args.directory, provider=provider, model=model, execute=args.execute)
    server, thread = None, None
    try:
        host.start(watching=args.watch)
        if args.serve:
            server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=args.port, workers=1))
            thread = Thread(target=server.run, name="reops-ab-readonly-api", daemon=True)
            thread.start()
        print(json.dumps({"target_id": "reops-lab-api", "watching": args.watch,
                          "execution_intent": args.execute, "model_configured": provider is not None,
                          "snapshot_port": args.port if args.serve else None}), flush=True)
        while server is None or thread.is_alive():
            if args.watch:
                incident_id = host.tick()
                if incident_id:
                    print(json.dumps({"incident_id": incident_id, "persisted": True}), flush=True)
            time.sleep(.2)
    except KeyboardInterrupt:
        return 0
    except Exception:
        print(json.dumps({"status": "not_connected", "error": "ab_host_unavailable_check_target_ownership"}))
        return 2
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=5)
        host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

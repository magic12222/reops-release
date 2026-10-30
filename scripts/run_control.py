"""Start the host control plane on loopback only, with one worker."""
import os

import uvicorn

from tools.system_tools import ROOT


def load_local_token():
    path = ROOT / ".env"
    if path.exists() and not os.getenv("REOPS_CONTROL_TOKEN"):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "REOPS_CONTROL_TOKEN":
                os.environ[key.strip()] = value.strip().strip("\"'")


def main():
    load_local_token()
    if not os.getenv("REOPS_CONTROL_TOKEN"):
        raise SystemExit("Run python -m scripts.init_local first or set REOPS_CONTROL_TOKEN")
    uvicorn.run("infra.monitoring.control:create_app", factory=True, host="127.0.0.1", port=8010, workers=1)


if __name__ == "__main__":
    main()

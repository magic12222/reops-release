"""检查完整 Git index：仅输出文件/行号/类别，绝不输出匹配内容。"""

import json
import os
import re
import subprocess


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    patterns = {
        "api_key_pattern": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        "github_token_pattern": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        "private_key_header": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    # 只比较当前实际敏感环境值，不显示其内容或来源变量值。
    values = {value for name, value in os.environ.items() if len(value) >= 8 and
              name.endswith(("_API_KEY", "_TOKEN", "_PASSWORD", "_SECRET"))}
    findings = []
    checked = 0
    for path in filter(None, paths):
        if (path == ".env" or path.startswith(".env.") and path != ".env.example"
                or any(part in path.split("/") for part in ("node_modules", ".venv", ".venv-nexent", ".pnpm-store"))):
            findings.append({"file": path, "rule": "forbidden_tracked_path"})
        data = subprocess.check_output(["git", "show", ":" + path])
        if b"\0" in data:
            continue
        checked += 1
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            rules = [name for name, pattern in patterns.items() if pattern.search(line)]
            if any(value in line for value in values):
                rules.append("configured_secret_value")
            findings.extend({"file": path, "line": number, "rule": rule} for rule in rules)
    print(json.dumps({"scanned_index_files": checked, "finding_count": len(findings),
                      "findings": findings}, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

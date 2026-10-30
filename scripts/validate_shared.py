"""Validate ReOps shared JSON Schemas and every example file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = PROJECT_ROOT / "shared"
EXAMPLES_DIR = SHARED_DIR / "examples"

EXAMPLE_SCHEMAS = {
    "healthy_observation.example.json": "observation.schema.json",
    "observation.example.json": "observation.schema.json",
    "recovered_observation.example.json": "observation.schema.json",
    "diagnosis.example.json": "diagnosis.schema.json",
    "recovery_action.example.json": "recovery_action.schema.json",
    "recovery_result.example.json": "recovery_result.schema.json",
    "agent_events.example.json": "agent_event.schema.json",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def format_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )


def main() -> int:
    failures = 0
    schemas: dict[str, dict[str, Any]] = {}

    for schema_path in sorted(SHARED_DIR.glob("*.schema.json")):
        try:
            schema = load_json(schema_path)
            Draft202012Validator.check_schema(schema)
            schemas[schema_path.name] = schema
            print(f"PASS schema  {schema_path.relative_to(PROJECT_ROOT)}")
        except (OSError, json.JSONDecodeError, SchemaError) as error:
            failures += 1
            print(f"FAIL schema  {schema_path.relative_to(PROJECT_ROOT)}: {error}")

    discovered = {path.name for path in EXAMPLES_DIR.glob("*.json")}
    unmapped = discovered - EXAMPLE_SCHEMAS.keys()
    missing = EXAMPLE_SCHEMAS.keys() - discovered

    for filename in sorted(unmapped):
        failures += 1
        print(f"FAIL example shared/examples/{filename}: no schema mapping")
    for filename in sorted(missing):
        failures += 1
        print(f"FAIL example shared/examples/{filename}: file is missing")

    for filename, schema_name in EXAMPLE_SCHEMAS.items():
        example_path = EXAMPLES_DIR / filename
        if not example_path.exists() or schema_name not in schemas:
            continue
        try:
            document = load_json(example_path)
            instances = document if filename == "agent_events.example.json" else [document]
            validator = Draft202012Validator(
                schemas[schema_name], format_checker=FormatChecker()
            )
            for index, instance in enumerate(instances):
                errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
                if errors:
                    failures += 1
                    suffix = f"[{index}]" if len(instances) > 1 else ""
                    for error in errors:
                        print(
                            f"FAIL example shared/examples/{filename}{suffix} "
                            f"at {format_path(error)}: {error.message}"
                        )
                else:
                    suffix = f"[{index}]" if len(instances) > 1 else ""
                    print(f"PASS example shared/examples/{filename}{suffix}")
        except (OSError, json.JSONDecodeError) as error:
            failures += 1
            print(f"FAIL example shared/examples/{filename}: {error}")

    if failures:
        print(f"\nFAIL: {failures} validation problem(s)")
        return 1

    print("\nPASS: all shared schemas and examples are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())

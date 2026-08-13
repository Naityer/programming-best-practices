#!/usr/bin/env python3
"""Plan an authorized test-generation and strength-validation workflow."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from detect_project import detect
from plan_audit import create_plan


def create_test_pipeline(
    root: Path,
    target: str,
    oracle_type: str,
    *,
    oracle_source: str | None = None,
    oracle_rule: str | None = None,
) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    if oracle_type == "specification" and not oracle_source:
        raise ValueError("specification oracle requires --oracle-source")
    if oracle_type == "property" and not oracle_rule:
        raise ValueError("property oracle requires --oracle-rule")
    inventory = detect(root)
    ecosystems = {item["name"] for item in inventory["ecosystems"]}
    generator: dict[str, Any]
    if "python" in ecosystems:
        executable = inventory["tools"].get("pynguin", {}).get("command")
        module = target.removesuffix(".py").replace("/", ".").replace("\\", ".")
        generator = {
            "tool": "pynguin", "status": "planned" if executable else "unavailable",
            "argv": [executable, "--project-path", str(root), "--module-name", module, "--output-path", "{artifact}/generated-tests"] if executable else [],
            "reason": "" if executable else "Pynguin is unavailable.",
        }
    elif "jvm" in ecosystems:
        executable = inventory["tools"].get("randoop", {}).get("command")
        generator = {
            "tool": "randoop", "status": "planned" if executable else "unavailable",
            "argv": [executable, "gentests", f"--testclass={target}", "--junit-output-dir={artifact}/generated-tests"] if executable else [],
            "reason": "" if executable else "Randoop is unavailable; EvoSuite/UnitTestBot require repository-specific setup.",
        }
    else:
        generator = {
            "tool": "manual/property-generator", "status": "unavailable", "argv": [],
            "reason": "No stable generic CLI generator is configured for this ecosystem; generate specification/property tests with semantic review.",
        }

    deep_plan = create_plan(root, "deep", f"target:{target}")
    validation = [
        check for check in deep_plan["checks"]
        if check["category"] in {"tests", "coverage", "test-strength"}
    ]
    return {
        "schema_version": "1.0.0",
        "root": str(root),
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authorization_required": {
            "test_generation": True,
            "generated_code_execution": True,
            "network": any(check.get("network") for check in validation),
            "project_effects": any(check.get("workspace_effects") != "none" for check in validation),
        },
        "oracle": {"type": oracle_type, "source": oracle_source, "rule": oracle_rule},
        "stages": [
            {
                "id": "generate",
                "purpose": "Generate candidate tests in an isolated artifact directory.",
                **generator,
                "generated_code": True,
                "workspace_effects": "none",
            },
            {
                "id": "semantic-review",
                "purpose": "Reject implementation-coupled, redundant, flaky, unsafe, or unsupported assertions and confirm the declared oracle.",
                "status": "manual-gate",
            },
            {
                "id": "integration",
                "purpose": "Copy only approved tests into the repository when the user authorized source changes.",
                "status": "manual-gate",
            },
            {
                "id": "validate-strength",
                "purpose": "Run native tests, branch coverage, and mutation testing.",
                "status": "planned",
                "checks": validation,
            },
        ],
        "safety": [
            "Use a disposable sandbox/container without production credentials.",
            "Deny network access unless the target genuinely requires it and the user approves.",
            "Do not execute generated tests before semantic review and explicit approval.",
            "Label regression assertions as observed behavior, not specification truth.",
            "Keep all generator output outside the repository until the integration gate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--target", required=True)
    parser.add_argument("--oracle-type", choices=("regression", "specification", "property"), required=True)
    parser.add_argument("--oracle-source")
    parser.add_argument("--oracle-rule")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = create_test_pipeline(
            args.root, args.target, args.oracle_type,
            oracle_source=args.oracle_source, oracle_rule=args.oracle_rule,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


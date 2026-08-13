from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

run_audit = load_module("run_audit", SKILL / "scripts" / "run_audit.py")


def plan(root: Path, argv: list[str], **overrides):
    check = {
        "id": "test.check", "tool": "python", "category": "correctness",
        "status": "planned", "argv": argv, "timeout_seconds": 5, "required": True,
        "output_format": "text", "workspace_effects": "none", "network": False,
        "generated_code": False, "reason": "", "environment": {}, "depends_on": [], "cwd": ".",
    }
    check.update(overrides)
    return {
        "root": str(root), "profile": "fast", "scope": "repository",
        "inventory": {"tools": {"python-runtime": {"status": "available", "command": sys.executable}}},
        "checks": [check],
    }


class RunAuditTests(unittest.TestCase):
    def test_executes_without_shell_and_captures_output(self) -> None:
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as parent:
            root = Path(project)
            output = Path(parent) / "run"
            result = run_audit.execute_plan(plan(root, [sys.executable, "-c", "print('ok')"]), output)
            self.assertEqual("passed", result["checks"][0]["status"])
            self.assertEqual("ok", Path(result["checks"][0]["stdout"]).read_text().strip())
            self.assertIn("Python", result["checks"][0]["version"])

    def test_blocks_network_workspace_and_generated_code_independently(self) -> None:
        variants = [
            {"network": True, "reason_text": "Network"},
            {"workspace_effects": "cache", "reason_text": "Project effects"},
            {"generated_code": True, "reason_text": "Generated-code"},
        ]
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as parent:
                root = Path(project)
                reason = variant.pop("reason_text")
                result = run_audit.execute_plan(
                    plan(root, [sys.executable, "-c", "print('never')"], **variant),
                    Path(parent) / "run",
                )
                self.assertEqual("skipped", result["checks"][0]["status"])
                self.assertIn(reason, result["checks"][0]["reason"])

    def test_timeout_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as parent:
            root = Path(project)
            result = run_audit.execute_plan(
                plan(root, [sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=1),
                Path(parent) / "run",
            )
            self.assertEqual("timed_out", result["checks"][0]["status"])
            self.assertFalse(result["complete"])

    def test_refuses_output_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            with self.assertRaises(ValueError):
                run_audit.execute_plan(plan(root, [sys.executable, "-c", "pass"]), root / "audit-output")

    def test_dependency_failure_skips_dependent_check(self) -> None:
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as parent:
            root = Path(project)
            data = plan(root, [sys.executable, "-c", "raise SystemExit(2)"])
            second = dict(data["checks"][0])
            second.update(id="test.after", argv=[sys.executable, "-c", "print('never')"], depends_on=["test.check"])
            data["checks"].append(second)
            result = run_audit.execute_plan(data, Path(parent) / "run")
            self.assertEqual("failed", result["checks"][0]["status"])
            self.assertEqual("skipped", result["checks"][1]["status"])


if __name__ == "__main__":
    unittest.main()


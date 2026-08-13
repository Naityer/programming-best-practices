from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tests.helpers import SKILL, load_module

scripts = SKILL / "scripts"
import sys
sys.path.insert(0, str(scripts))
plan_audit = load_module("plan_audit", scripts / "plan_audit.py")


class PlanAuditTests(unittest.TestCase):
    def test_profiles_are_monotonic_and_deep_contains_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            fast = plan_audit.create_plan(root, "fast")
            standard = plan_audit.create_plan(root, "standard")
            deep = plan_audit.create_plan(root, "deep")
            self.assertLess(len(fast["checks"]), len(standard["checks"]))
            self.assertLess(len(standard["checks"]), len(deep["checks"]))
            self.assertIn("python.mutation", {item["id"] for item in deep["checks"]})

    def test_nested_package_uses_its_own_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / "web"
            web.mkdir()
            (web / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint .", "test": "vitest", "typecheck": "tsc --noEmit"}}),
                encoding="utf-8",
            )
            (web / "package-lock.json").write_text("{}", encoding="utf-8")
            (web / "app.ts").write_text("export {}\n", encoding="utf-8")
            plan = plan_audit.create_plan(root, "standard")
            js = [item for item in plan["checks"] if item["ecosystem"] == "javascript-typescript"]
            self.assertTrue(js)
            self.assertEqual({"web"}, {item["cwd"] for item in js})

    def test_plan_is_data_only_and_commands_are_argument_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "go.mod").write_text("module example.invalid\n", encoding="utf-8")
            (root / "main.go").write_text("package main\n", encoding="utf-8")
            plan = plan_audit.create_plan(root, "deep")
            for check in plan["checks"]:
                self.assertIsInstance(check["argv"], list)
                self.assertNotIn(";", check["argv"])
                self.assertIn(check["workspace_effects"], {"none", "cache", "runtime"})


    def test_changed_file_scope_is_applied_to_semgrep_and_gitleaks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "changed.py").write_text("value = 2", encoding="utf-8")
            (root / "legacy.py").write_text("value = 1", encoding="utf-8")
            inventory = {
                "ecosystems": [], "configurations": [],
                "default_scope": {"type": "changed-files", "files": ["changed.py"]},
                "tools": {
                    "semgrep": {"status": "available", "command": "semgrep"},
                    "gitleaks": {"status": "available", "command": "gitleaks"},
                },
            }
            with patch.object(plan_audit, "detect", return_value=inventory):
                plan = plan_audit.create_plan(root, "fast")
            semgrep = next(item for item in plan["checks"] if item["id"] == "universal.semgrep")
            self.assertEqual("changed-files", semgrep["effective_scope"])
            self.assertEqual("changed.py", semgrep["argv"][-1])
            self.assertNotIn("legacy.py", semgrep["argv"])
            gitleaks = next(item for item in plan["checks"] if item["id"] == "universal.gitleaks")
            self.assertEqual("changed.py", gitleaks["argv"][2])
            self.assertEqual("changed-files", gitleaks["effective_scope"])

    def test_explicit_scope_must_exist_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1", encoding="utf-8")
            with self.assertRaises(ValueError):
                plan_audit.create_plan(root, "fast", "../outside")

if __name__ == "__main__":
    unittest.main()


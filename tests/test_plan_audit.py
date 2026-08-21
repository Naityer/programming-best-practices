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

    def test_design_patterns_check_narrows_to_changed_files_but_reads_the_whole_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "changed.py").write_text("value = 2", encoding="utf-8")
            (root / "legacy.py").write_text("value = 1", encoding="utf-8")
            inventory = {
                "ecosystems": [], "configurations": [],
                "default_scope": {"type": "changed-files", "files": ["changed.py"]},
                "tools": {"python-runtime": {"status": "available", "command": sys.executable}},
            }
            with patch.object(plan_audit, "detect", return_value=inventory):
                plan = plan_audit.create_plan(root, "standard")
            check = next(item for item in plan["checks"] if item["id"] == "universal.design-patterns")
            self.assertEqual("changed files + local dependency context", check["effective_scope"])
            self.assertIn("--focus", check["argv"])
            self.assertEqual("changed.py", check["argv"][check["argv"].index("--focus") + 1])
            self.assertNotIn("legacy.py", check["argv"])
            # --root still points at the whole repo, never just the diff:
            self.assertIn(str(root), check["argv"])

    def test_explicit_scope_must_exist_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1", encoding="utf-8")
            with self.assertRaises(ValueError):
                plan_audit.create_plan(root, "fast", "../outside")

    def test_design_patterns_check_is_standard_and_above_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            fast = plan_audit.create_plan(root, "fast")
            standard = plan_audit.create_plan(root, "standard")
            self.assertNotIn("universal.design-patterns", {item["id"] for item in fast["checks"]})
            check = next(item for item in standard["checks"] if item["id"] == "universal.design-patterns")
            self.assertEqual("quality", check["category"])
            self.assertEqual("design-patterns", check["output_format"])
            self.assertEqual("none", check["workspace_effects"])
            self.assertFalse(check["network"])
            self.assertFalse(check["generated_code"])
            self.assertEqual("repository", check["effective_scope"])
            self.assertIn("analyze_design_patterns.py", check["argv"][1])
            self.assertIn(str(root), check["argv"])
            self.assertIn("{artifact}/design-patterns.json", check["argv"])
            self.assertIn("{artifact}/uml", check["argv"])

if __name__ == "__main__":
    unittest.main()



class MypyTargetsTests(unittest.TestCase):
    """Si el proyecto declara que comprobar, manda el proyecto."""

    def _project(self, root: Path, mypy_config: str) -> None:
        (root / "pyproject.toml").write_text(mypy_config, encoding="utf-8")
        (root / "app.py").write_text("value = 1" + chr(10), encoding="utf-8")
        scripts_dir = root / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "mypy.exe").write_text("", encoding="utf-8")
        bin_dir = root / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "mypy").write_text("", encoding="utf-8")

    def test_no_path_is_passed_when_the_project_declares_files(self) -> None:
        # Pasar `.` sobreescribe la config y arrastra todo el repositorio: en un
        # layout src/ eso hace que mypy vea conftest.py dos veces y ABORTE, lo
        # que se reportaria como defecto del codigo y no de la invocacion.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root, '[tool.mypy]' + chr(10) + 'files = ["src/app"]' + chr(10))
            checks = {c["id"]: c for c in plan_audit.create_plan(root, "fast")["checks"]}
            self.assertEqual(len(checks["python.mypy"]["argv"]), 1)

    def test_a_path_is_passed_when_the_project_declares_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root, "[project]" + chr(10) + "name = 'x'" + chr(10))
            checks = {c["id"]: c for c in plan_audit.create_plan(root, "fast")["checks"]}
            self.assertEqual(checks["python.mypy"]["argv"][-1], ".")


class CheckOrderTests(unittest.TestCase):
    """Un check nunca puede ir antes de aquello de lo que depende."""

    def test_dependencies_come_first_even_against_the_alphabet(self) -> None:
        # `coverage-report` va antes que `coverage-run` en el alfabeto. Con el
        # orden alfabetico se ejecutaba primero, el ejecutor veia su
        # prerequisito sin pasar, y la cobertura se medIa para tirarla.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]" + chr(10), encoding="utf-8")
            (root / "app.py").write_text("value = 1" + chr(10), encoding="utf-8")
            (root / "tests").mkdir()
            (root / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
            (root / "dist").mkdir()

            checks = plan_audit.create_plan(root, "standard")["checks"]
            position = {c["id"]: i for i, c in enumerate(checks)}
            for check in checks:
                for dependency in check.get("depends_on", []):
                    if dependency in position:
                        self.assertLess(
                            position[dependency], position[check["id"]],
                            f"{dependency} debe ir antes que {check['id']}",
                        )

    def test_the_order_is_still_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]" + chr(10) + "name='x'" + chr(10), encoding="utf-8")
            (root / "app.py").write_text("value = 1" + chr(10), encoding="utf-8")
            first = [c["id"] for c in plan_audit.create_plan(root, "standard")["checks"]]
            second = [c["id"] for c in plan_audit.create_plan(root, "standard")["checks"]]
            self.assertEqual(first, second)

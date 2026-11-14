"""Regresiones halladas al auditar proyectos reales (ver auditoria/INFORME.md)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
plan_audit = load_module("plan_audit_reg", SKILL / "scripts" / "plan_audit.py")
build_report = load_module("build_report_reg", SKILL / "scripts" / "build_report.py")
normalize = load_module("normalize_reg", SKILL / "scripts" / "normalize_tool_output.py")


def _inventory(tools: dict) -> dict:
    return {"ecosystems": [], "configurations": [], "default_scope": {"type": "repository", "files": []}, "tools": tools}


class PlanRegressions(unittest.TestCase):
    def test_bundled_semgrep_rules_exist(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            inv = _inventory({"semgrep": {"status": "available", "command": "semgrep"}})
            with patch.object(plan_audit, "detect", return_value=inv):
                plan = plan_audit.create_plan(root, "standard", scope="repository")
            semgrep = next(c for c in plan["checks"] if c["id"] == "universal.semgrep")
            config = Path(semgrep["argv"][semgrep["argv"].index("--config") + 1])
            self.assertTrue(config.is_file(), f"reglas de semgrep inexistentes: {config}")

    def test_ruff_does_not_write_cache_into_audited_repo(self) -> None:
        inventory = _inventory({"ruff": {"status": "available", "command": "ruff"}})
        inventory["ecosystems"] = [{"name": "python", "build_systems": ["python"], "test_runners": []}]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            with patch.object(plan_audit, "detect", return_value=inventory):
                plan = plan_audit.create_plan(root, "standard", scope="repository")
        ruff = [c for c in plan["checks"] if c["id"] == "python.ruff"]
        self.assertTrue(ruff and ruff[0]["argv"])
        self.assertIn("--no-cache", ruff[0]["argv"])
        self.assertEqual("none", ruff[0]["workspace_effects"])


class ReportRegressions(unittest.TestCase):
    def test_ruff_findings_on_same_line_get_distinct_ids(self) -> None:
        data = [
            {"code": "F401", "message": "unused", "filename": "a.py", "location": {"row": 3, "column": 1}},
            {"code": "F401", "message": "unused", "filename": "a.py", "location": {"row": 3, "column": 9}},
        ]
        findings, _, _ = normalize.parse_ruff(data, None)
        self.assertEqual(2, len({f["id"] for f in findings}))

    def test_duplicate_finding_ids_do_not_abort_the_report(self) -> None:
        finding = {
            "id": "PBP-AAAAAAAAAAAA", "fingerprint": "a" * 24, "rule_id": "x.y", "title": "t", "category": "maintainability",
            "severity": "low", "confidence": "high", "locations": [{"file": "a.py", "line": 1}],
            "evidence": [{"source_type": "tool", "source": "x", "message": "m"}], "impact": "i", "recommendation": "r",
        }
        with tempfile.TemporaryDirectory() as d:
            execution = {"root": d, "profile": "standard", "scope": "repository", "generated_at": "2026-08-13T12:00:00Z", "checks": []}
            report = build_report.build(execution, [{"tool": "x", "findings": [dict(finding), dict(finding)], "dimensions": {}, "limitations": []}])
        ids = [f["id"] for f in report["findings"]]
        self.assertEqual(2, len(set(ids)))


if __name__ == "__main__":
    unittest.main()


class FileEnumeration(unittest.TestCase):
    def test_project_files_prunes_excluded_dirs_and_honours_gitignore(self) -> None:
        import subprocess
        files = load_module("pbp_files_test", SKILL / "scripts" / "analysis_core" / "files.py")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ("app/a.py", "node_modules/x/b.py", ".trabajo/w/c.py", "keep.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("x = 1\n", encoding="utf-8")
            (root / ".gitignore").write_text(".trabajo/\n", encoding="utf-8")
            plain = {p.relative_to(root).as_posix() for p in files.project_files(root, {"node_modules"})}
            self.assertEqual({"app/a.py", ".trabajo/w/c.py", "keep.py", ".gitignore"}, plain)  # sin git: solo poda por nombre
            if subprocess.run(["git", "init", "-q", str(root)], capture_output=True).returncode == 0:
                git = {p.relative_to(root).as_posix() for p in files.project_files(root, {"node_modules"})}
                self.assertEqual({"app/a.py", "keep.py", ".gitignore"}, git)


class StructureWiring(unittest.TestCase):
    def test_plan_includes_read_only_structure_check_the_report_understands(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            plan = plan_audit.create_plan(root, "standard", scope="repository")
        check = next(c for c in plan["checks"] if c["id"] == "universal.structure")
        self.assertEqual("none", check["workspace_effects"])
        self.assertFalse(check["network"])
        self.assertIn(check["output_format"], build_report.SUPPORTED_FORMATS)


class VendoredPaths(unittest.TestCase):
    def test_bundler_output_dirs_are_treated_as_generated(self) -> None:
        normalize = load_module("normalize_impl_reg", SKILL / "scripts" / "reporting" / "normalize_tool_output.py")
        for path in ("data/.vite-preview-1/paquetes/x/dist-atlas/ui.js", "dist-paquete/a.js", "app/dist/a.js"):
            self.assertTrue(normalize._is_vendored(path), path)
        for path in ("src/distance.py", "server/src/server.ts", "src/vite-config.ts"):
            self.assertFalse(normalize._is_vendored(path), path)


class RuffClassification(unittest.TestCase):
    def test_only_bandit_codes_are_security(self) -> None:
        impl = load_module("normalize_impl_ruff", SKILL / "scripts" / "reporting" / "normalize_tool_output.py")
        data = [{"code": code, "message": "m", "filename": "a.py", "location": {"row": 1, "column": 1}} for code in ("S110", "SIM118", "SLF001")]
        found = {f["rule_id"]: (f["category"], f["severity"]) for f in impl.parse_ruff(data, None)[0]}
        self.assertEqual(("security", "high"), found["S110"])
        self.assertEqual(("maintainability", "low"), found["SIM118"])
        self.assertEqual(("maintainability", "low"), found["SLF001"])


class DisposableCopy(unittest.TestCase):
    def test_copy_respects_gitignore_and_never_writes_to_original(self) -> None:
        import subprocess
        run_in_copy = load_module("run_in_copy_t", SKILL / "scripts" / "run_in_copy.py")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "proj"
            (root / "src").mkdir(parents=True)
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "secret.log").write_text("no\n", encoding="utf-8")
            (root / "node_modules" / "x" / "i.js").write_text("1\n", encoding="utf-8")
            (root / ".gitignore").write_text("*.log\nnode_modules/\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], capture_output=True)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git/" not in p.as_posix())
            out = Path(d) / "copy"
            summary = run_in_copy.copy_project(root, out)
            self.assertEqual({"src/a.py", ".gitignore"}, {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()})
            self.assertEqual([], summary["deps"])
            deps = run_in_copy.copy_project(root, Path(d) / "copy2", copy_deps=True)
            self.assertEqual(["node_modules"], deps["deps"])
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git/" not in p.as_posix())
            self.assertEqual(before, after)


class FastApiIdiom(unittest.TestCase):
    def test_b008_depends_is_not_a_medium_defect(self) -> None:
        impl = load_module("normalize_impl_b008", SKILL / "scripts" / "reporting" / "normalize_tool_output.py")
        data = [
            {"code": "B008", "message": "Do not perform function call `Depends` in argument defaults", "filename": "a.py", "location": {"row": 1, "column": 1}},
            {"code": "B008", "message": "Do not perform function call `list` in argument defaults", "filename": "a.py", "location": {"row": 2, "column": 1}},
        ]
        found = [f["severity"] for f in impl.parse_ruff(data, None)[0]]
        self.assertEqual(["low", "medium"], found)


class MonorepoPackage(unittest.TestCase):
    def test_subpackage_with_most_scripts_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, scripts in (("desktop", {}), ("server", {"test": "vitest", "build": "tsc", "typecheck": "tsc --noEmit"})):
                (root / name).mkdir()
                (root / name / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")
                (root / name / "a.ts").write_text("export {}\n", encoding="utf-8")
            plan = plan_audit.create_plan(root, "standard", scope="repository")
        test = next(c for c in plan["checks"] if c["id"] == "js.test")
        self.assertEqual("server", test["cwd"])


class FailingTestsBecomeFindings(unittest.TestCase):
    def test_pytest_and_vitest_failures_are_reported(self) -> None:
        for text, expected in (
            ("FAILED tests/test_a.py::test_x - AssertionError\n2 failed, 557 passed in 732s\n", 2),
            ("\x1b[31m ❯ src/flujos/flujos.test.ts (13 tests | 2 failed) 18326ms\n Tests  7 failed | 545 passed\n", 7),
        ):
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / "stdout.txt"
                out.write_text(text, encoding="utf-8")
                check = {"id": "x.tests", "name": "t", "category": "tests", "status": "findings", "stdout": str(out), "required": True,
                         "output_format": "text", "command": "t", "exit_code": 1, "duration_ms": 1, "artifact_dir": "", "reason": ""}
                execution = {"root": d, "profile": "standard", "scope": "repository", "generated_at": "2026-08-13T12:00:00Z", "checks": [check]}
                report = build_report.build(execution, [])
            self.assertEqual(["pbp.tests.failing"], [f["rule_id"] for f in report["findings"]])
            self.assertIn(f"{expected} test(s)", report["findings"][0]["title"])
            self.assertEqual("high", report["findings"][0]["severity"])

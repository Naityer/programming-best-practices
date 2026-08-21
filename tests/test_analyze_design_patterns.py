from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module, scripts_on_path

# Must run BEFORE load_module(): analyze_design_patterns.py's top-level
# `from design_patterns... import ...` statements need scripts/ on sys.path
# the moment exec_module() runs it, not after.
scripts_on_path()

analyze_design_patterns = load_module("analyze_design_patterns", SKILL / "scripts" / "analyze_design_patterns.py")
validate_design_patterns = load_module("validate_design_patterns", SKILL / "scripts" / "validate_design_patterns.py")


ADAPTER_REPO = {
    "ports.py": """
        class PaymentGateway:
            def pay(self):
                raise NotImplementedError
    """,
    "legacy/client.py": """
        class LegacyGateway:
            def charge(self):
                return True
    """,
    "adapter.py": """
        from ports import PaymentGateway
        from legacy.client import LegacyGateway

        class LegacyGatewayAdapter(PaymentGateway):
            def __init__(self, legacy: LegacyGateway):
                self._legacy = legacy

            def pay(self):
                return self._legacy.charge()
    """,
}


def write_repo(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")


class AnalyzeEndToEndTests(unittest.TestCase):
    def test_produces_a_schema_valid_report_with_the_adapter_and_no_stray_findings(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            output = Path(out_dir) / "design-patterns.json"
            uml_dir = Path(out_dir) / "uml"

            result = analyze_design_patterns.analyze(root, uml_dir=uml_dir)
            data = result.to_dict()

            errors = validate_design_patterns.validate_design_patterns(data)
            self.assertEqual([], errors)

            self.assertEqual(3, data["files_scanned"])
            self.assertEqual(["python"], data["languages"])
            self.assertEqual("repository", data["effective_scope"])
            adapter_hits = [p for p in data["patterns"] if p["pattern_id"] == "adapter"]
            self.assertEqual(1, len(adapter_hits))
            self.assertEqual("detected", adapter_hits[0]["status"])
            self.assertIsNotNone(adapter_hits[0]["uml_artifact"])
            self.assertEqual("UML 2.5.1", adapter_hits[0]["uml"]["notation"])
            self.assertEqual(
                {"dependency", "realization", "association"},
                {rel["type"] for rel in adapter_hits[0]["uml"]["relationships"]},
            )

            output.write_text(json.dumps(data), encoding="utf-8")
            reloaded, reload_errors = validate_design_patterns.load_and_validate(output)
            self.assertEqual([], reload_errors)
            self.assertIsNotNone(reloaded)

            mmd_files = list(uml_dir.glob("adapter-*.mmd"))
            self.assertEqual(1, len(mmd_files))
            self.assertIn("LegacyGatewayAdapter", mmd_files[0].read_text(encoding="utf-8"))

    def test_empty_repository_produces_zero_patterns_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir:
            root = Path(repo_dir)
            result = analyze_design_patterns.analyze(root)
            self.assertEqual(0, result.files_scanned)
            self.assertEqual([], result.patterns)

    def test_excludes_vendored_directories(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir:
            root = Path(repo_dir)
            write_repo(root, {
                ".venv/lib/site.py": "class Ignored:\n    pass\n",
                "node_modules/pkg/x.py": "class AlsoIgnored:\n    pass\n",
                "src/real.py": "class Real:\n    pass\n",
            })
            result = analyze_design_patterns.analyze(root)
            self.assertEqual(1, result.files_scanned)

    def test_main_exits_zero_even_with_zero_patterns_found(self) -> None:
        """Trap documented in design-patterns-module/05-hallazgos-codigo.md:
        run_audit.py maps a non-zero exit for a 'quality'-category check to
        `failed`, not `findings` — this CLI must never use the exit code to
        signal "nothing found"."""
        import sys
        from unittest import mock

        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            output = Path(out_dir) / "design-patterns.json"
            argv = ["analyze_design_patterns.py", "--root", repo_dir, "--output", str(output)]
            with mock.patch.object(sys, "argv", argv):
                exit_code = analyze_design_patterns.main()
            self.assertEqual(0, exit_code)
            self.assertTrue(output.is_file())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([], payload["patterns"])

    def test_main_returns_2_on_a_genuine_operational_failure(self) -> None:
        import sys
        from unittest import mock

        argv = ["analyze_design_patterns.py", "--root", "/definitely/does/not/exist", "--output", "/tmp/x.json"]
        with mock.patch.object(sys, "argv", argv):
            exit_code = analyze_design_patterns.main()
        self.assertEqual(2, exit_code)


class ValidatorTests(unittest.TestCase):
    def test_rejects_missing_required_field(self) -> None:
        errors = validate_design_patterns.validate_design_patterns({
            "schema_version": "1.0.0", "files_scanned": 1, "languages": ["python"], "limitations": [],
        })
        self.assertTrue(any("patterns" in e for e in errors))

    def test_rejects_unknown_status(self) -> None:
        errors = validate_design_patterns.validate_design_patterns({
            "schema_version": "1.0.0", "files_scanned": 1, "languages": ["python"], "limitations": [],
            "patterns": [{
                "pattern_id": "adapter", "status": "definitely-not-a-status", "confidence": "high",
                "primary_location": {"file": "a.py", "line": 1}, "roles": {}, "evidence": [], "contradictions": [],
            }],
        })
        self.assertTrue(any("status" in e for e in errors))

    def test_rejects_high_confidence_on_a_refactor_opportunity(self) -> None:
        errors = validate_design_patterns.validate_design_patterns({
            "schema_version": "1.0.0", "files_scanned": 1, "languages": ["python"], "limitations": [],
            "patterns": [{
                "pattern_id": "strategy", "status": "refactor-opportunity", "confidence": "high",
                "primary_location": {"file": "a.py", "line": 1}, "roles": {}, "evidence": [], "contradictions": [],
            }],
        })
        self.assertTrue(any("confidence" in e for e in errors))


class ScopeFilteringTests(unittest.TestCase):
    """spec §17: "focus scope + dependency context" — the graph always reads
    the whole repo (Target/Adaptee can live outside the diff), but findings
    only surface for the requested scope."""

    def test_focus_on_the_adapters_own_file_keeps_the_finding(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            result = analyze_design_patterns.analyze(root, focus=["adapter.py"])
            self.assertEqual("changed files + local dependency context", result.effective_scope)
            adapter_hits = [p for p in result.patterns if p.pattern_id == "adapter"]
            self.assertEqual(1, len(adapter_hits))
            self.assertEqual("adapter.py", adapter_hits[0].primary_location.file)

    def test_focus_on_a_dependency_only_file_drops_the_finding(self) -> None:
        """ports.py is READ for context (PaymentGateway resolves from it) but
        the Adapter is anchored in adapter.py — focusing on ports.py alone
        must not surface a finding whose anchor lives outside the scope."""
        with tempfile.TemporaryDirectory() as repo_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            result = analyze_design_patterns.analyze(root, focus=["ports.py"])
            self.assertEqual([], result.patterns)
            # but the full repo was still read for context, not just ports.py:
            self.assertEqual(3, result.files_scanned)

    def test_no_focus_means_repository_scope_and_every_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            result = analyze_design_patterns.analyze(root)
            self.assertEqual("repository", result.effective_scope)
            self.assertTrue(any(p.pattern_id == "adapter" for p in result.patterns))

    def test_focus_only_affects_uml_written_for_surfaced_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            uml_dir = Path(out_dir) / "uml"
            analyze_design_patterns.analyze(root, uml_dir=uml_dir, focus=["ports.py"])
            self.assertEqual([], list(uml_dir.glob("*.mmd")))

    def test_cli_wires_repeated_focus_flags_through(self) -> None:
        import sys
        from unittest import mock

        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as out_dir:
            root = Path(repo_dir)
            write_repo(root, ADAPTER_REPO)
            output = Path(out_dir) / "design-patterns.json"
            argv = [
                "analyze_design_patterns.py", "--root", str(root), "--output", str(output),
                "--focus", "adapter.py",
            ]
            with mock.patch.object(sys, "argv", argv):
                exit_code = analyze_design_patterns.main()
            self.assertEqual(0, exit_code)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("changed files + local dependency context", payload["effective_scope"])
            self.assertEqual(1, len(payload["patterns"]))


if __name__ == "__main__":
    unittest.main()

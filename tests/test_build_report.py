from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
build_report = load_module("build_report", SKILL / "scripts" / "build_report.py")
render_report = load_module("render_report_build", SKILL / "scripts" / "render_report.py")


class BuildReportTests(unittest.TestCase):
    def test_builds_outcome_tools_dimensions_and_generated_identity(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            execution = {
                "root": str(root), "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z",
                "checks": [
                    {
                        "id": "python.tests", "name": "pytest", "category": "tests",
                        "status": "passed", "command": "python -m pytest", "exit_code": 0,
                        "duration_ms": 12, "stdout": "", "stderr": "", "artifact_dir": "",
                        "output_format": "text", "required": True, "reason": "",
                    },
                    {
                        "id": "python.coverage", "name": "coverage", "category": "coverage",
                        "status": "unavailable", "command": "", "exit_code": None,
                        "duration_ms": 0, "stdout": "", "stderr": "", "artifact_dir": "",
                        "output_format": "coverage-py", "required": False, "reason": "not installed",
                    },
                ],
            }
            fragment = {
                "tool": "semantic",
                "findings": [{
                    "rule_id": "correctness.example", "title": "Example defect", "category": "correctness",
                    "severity": "high", "confidence": "medium", "locations": [{"file": "app.py", "line": 1}],
                    "evidence": [{"source_type": "llm", "source": "semantic-review", "message": "Observed control flow."}],
                    "impact": "The operation can return an incorrect result.", "recommendation": "Correct the condition.",
                }],
                "dimensions": {"coverage": {"branch_percent": 70}},
                "limitations": [],
            }
            report = build_report.build(execution, [fragment])
            self.assertEqual("informational", report["audit"]["outcome"])
            self.assertEqual(70, report["summary"]["dimensions"]["coverage"]["branch_percent"])
            with tempfile.TemporaryDirectory() as parent:
                input_path = Path(parent) / "canonical.json"
                input_path.write_text(json.dumps(report), encoding="utf-8")
                destination = render_report.render(input_path, root, Path(parent) / "rendered")
                normalized = json.loads((destination / "report.json").read_text(encoding="utf-8"))
                finding = normalized["findings"][0]
                self.assertTrue(finding["id"].startswith("PBP-"))
                self.assertEqual(24, len(finding["fingerprint"]))

    def test_blocker_fails_and_required_missing_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            base = {
                "root": project, "profile": "fast", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z",
                "checks": [{"id": "tests", "name": "tests", "category": "tests", "status": "unavailable", "command": "", "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "artifact_dir": "", "output_format": "text", "required": True, "reason": "missing"}],
            }
            self.assertEqual("incomplete", build_report.build(base, [])["audit"]["outcome"])
            blocker = {
                "tool": "semantic", "dimensions": {}, "limitations": [],
                "findings": [{"id": "B", "fingerprint": "b", "rule_id": "security.auth", "title": "Bypass", "category": "security", "severity": "blocker", "confidence": "high", "locations": [{"file": "app.py"}], "evidence": [{"source_type": "llm", "source": "review", "message": "Direct bypass"}], "impact": "Unauthorized access.", "recommendation": "Enforce authorization."}],
            }
            self.assertEqual("fail", build_report.build(base, [blocker])["audit"]["outcome"])


    def test_parsed_findings_change_tool_status(self) -> None:
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as artifacts:
            output = Path(artifacts) / "semgrep.json"
            output.write_text(json.dumps({
                "results": [{
                    "check_id": "pbp.python.rule", "path": "app.py",
                    "start": {"line": 2},
                    "extra": {"message": "match", "severity": "WARNING", "metadata": {"category": "security", "confidence": "MEDIUM"}},
                }],
                "errors": [],
            }), encoding="utf-8")
            execution = {
                "root": project, "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z",
                "checks": [{
                    "id": "universal.semgrep", "name": "semgrep", "category": "security",
                    "status": "passed", "command": "semgrep", "exit_code": 0,
                    "duration_ms": 2, "stdout": str(output), "stderr": "",
                    "artifact_dir": artifacts, "output_format": "semgrep",
                    "required": False, "reason": "", "gate": False,
                    "effective_scope": "repository",
                }],
            }
            report = build_report.build(execution, [])
            self.assertEqual("findings", report["tools"][0]["status"])
            self.assertEqual(1, len(report["findings"]))

    def test_configured_gates_produce_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            check = {
                "id": "tests", "name": "pytest", "category": "tests", "status": "passed",
                "command": "pytest", "exit_code": 0, "duration_ms": 1, "stdout": "",
                "stderr": "", "artifact_dir": "", "output_format": "text",
                "required": True, "reason": "", "gate": True, "effective_scope": "repository",
            }
            execution = {
                "root": project, "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z", "checks": [check],
            }
            self.assertEqual("pass", build_report.build(execution, [])["audit"]["outcome"])
            check["status"] = "findings"
            check["exit_code"] = 1
            self.assertEqual("fail", build_report.build(execution, [])["audit"]["outcome"])

    def test_semantic_review_can_dismiss_or_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = {
                "root": project, "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z", "checks": [],
            }
            finding = {
                "id": "F", "fingerprint": "fp-one", "rule_id": "security.shell",
                "title": "Shell invocation", "category": "security", "severity": "medium",
                "confidence": "medium", "locations": [{"file": "app.py", "line": 1}],
                "evidence": [{"source_type": "tool", "source": "semgrep", "message": "Pattern match."}],
                "impact": "Potential injection.", "recommendation": "Review data flow.",
            }
            fragment = {"tool": "semgrep", "findings": [finding], "dimensions": {}, "limitations": []}
            with self.assertRaises(ValueError):
                build_report.build(execution, [fragment], semantic_review=[{"fingerprint": "fp-one", "action": "dismiss"}])
            dismissed = build_report.build(
                execution, [fragment], semantic_review=[
                    {"fingerprint": "fp-one", "action": "dismiss", "reason": "Command is a trusted constant."}
                ],
            )
            self.assertEqual([], dismissed["findings"])
            self.assertTrue(any("Dismissed security.shell" in item for item in dismissed["limitations"]))
            confirmed = build_report.build(
                execution, [fragment], semantic_review=[{
                    "fingerprint": "fp-one", "action": "confirm", "reason": "Request data reaches the shell.",
                    "overrides": {"severity": "high", "confidence": "high"},
                }],
            )
            self.assertEqual("high", confirmed["findings"][0]["severity"])
            self.assertEqual("semantic-review", confirmed["findings"][0]["evidence"][-1]["source"])

    def _empty_execution(self, project: str) -> dict:
        return {
            "root": project, "profile": "standard", "scope": "repository",
            "generated_at": "2026-08-13T12:00:00Z", "checks": [],
        }

    def _shell_finding(self) -> dict:
        return {
            "id": "F", "fingerprint": "fp-one", "rule_id": "security.shell",
            "title": "Shell invocation", "category": "security", "severity": "medium",
            "confidence": "medium", "locations": [{"file": "app.py", "line": 1}],
            "evidence": [{"source_type": "tool", "source": "semgrep", "message": "Pattern match."}],
            "impact": "Potential injection.", "recommendation": "Review data flow.",
        }

    def test_dismiss_decision_produces_a_ledger_entry_with_evidence_source_types(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = self._empty_execution(project)
            finding = self._shell_finding()
            fragment = {"tool": "semgrep", "findings": [finding], "dimensions": {}, "limitations": []}
            report = build_report.build(
                execution, [fragment],
                semantic_review=[{"fingerprint": "fp-one", "action": "dismiss", "reason": "Trusted constant."}],
            )
            ledger = report["_review_ledger"]
            self.assertEqual(1, len(ledger))
            entry = ledger[0]
            self.assertEqual("dismiss", entry["action"])
            self.assertFalse(entry["unmatched"])
            self.assertEqual(["tool"], entry["matched"][0]["evidence_source_types"])
            self.assertEqual("semgrep", entry["matched"][0]["primary_source"])
            self.assertEqual("fp-one", entry["matched"][0]["fingerprint"])

    def test_confirm_decision_produces_a_ledger_entry_with_overrides_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = self._empty_execution(project)
            finding = self._shell_finding()
            fragment = {"tool": "semgrep", "findings": [finding], "dimensions": {}, "limitations": []}
            report = build_report.build(
                execution, [fragment],
                semantic_review=[{
                    "fingerprint": "fp-one", "action": "confirm", "reason": "Data reaches the shell.",
                    "overrides": {"severity": "high"},
                }],
            )
            entry = report["_review_ledger"][0]
            self.assertEqual("confirm", entry["action"])
            self.assertEqual({"severity": "high"}, entry["overrides"])
            # La instantánea es de ANTES de la mutación: sigue mostrando la
            # severidad original, no la que el override acaba de aplicar.
            self.assertEqual("medium", entry["matched"][0]["severity"])
            self.assertEqual("high", report["findings"][0]["severity"])

    def test_unmatched_decision_is_recorded_in_the_ledger_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = self._empty_execution(project)
            report = build_report.build(
                execution, [],
                semantic_review=[{"fingerprint": "does-not-exist", "action": "dismiss", "reason": "n/a"}],
            )
            ledger = report["_review_ledger"]
            self.assertEqual(1, len(ledger))
            self.assertTrue(ledger[0]["unmatched"])
            self.assertEqual([], ledger[0]["matched"])

    def test_no_semantic_review_means_no_ledger_key(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = self._empty_execution(project)
            report = build_report.build(execution, [])
            self.assertNotIn("_review_ledger", report)

    def test_empty_semantic_review_still_produces_an_empty_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            execution = self._empty_execution(project)
            report = build_report.build(execution, [], semantic_review=[])
            self.assertEqual([], report["_review_ledger"])

    def test_tools_carry_category_and_output_format_from_execution_checks(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            check = {
                "id": "universal.semgrep", "name": "semgrep", "category": "security", "status": "passed",
                "command": "semgrep", "exit_code": 0, "duration_ms": 5, "stdout": "", "stderr": "",
                "artifact_dir": "", "output_format": "semgrep", "required": False, "reason": "",
            }
            execution = {
                "root": project, "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z", "checks": [check],
            }
            report = build_report.build(execution, [])
            self.assertEqual("security", report["tools"][0]["category"])
            self.assertEqual("semgrep", report["tools"][0]["output_format"])

    def test_ledger_file_is_written_only_when_semantic_review_was_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            execution = {
                "root": str(root), "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z", "checks": [],
            }
            execution_path = root / "execution.json"
            execution_path.write_text(json.dumps(execution), encoding="utf-8")

            without_review = root / "without-review"
            argv = sys.argv
            try:
                sys.argv = ["build_report.py", str(execution_path), "--output-dir", str(without_review)]
                self.assertEqual(0, build_report.main())
            finally:
                sys.argv = argv
            self.assertEqual(
                {"report.json", "report.md", "report.sarif"},
                {p.name for p in without_review.iterdir()},
            )

            review_path = root / "review.json"
            review_path.write_text(json.dumps({"decisions": []}), encoding="utf-8")
            with_review = root / "with-review"
            argv = sys.argv
            try:
                sys.argv = [
                    "build_report.py", str(execution_path), "--output-dir", str(with_review),
                    "--semantic-review", str(review_path),
                ]
                self.assertEqual(0, build_report.main())
            finally:
                sys.argv = argv
            self.assertEqual(
                {"report.json", "report.md", "report.sarif", "review-ledger.json"},
                {p.name for p in with_review.iterdir()},
            )
            ledger_doc = json.loads((with_review / "review-ledger.json").read_text(encoding="utf-8"))
            self.assertEqual([], ledger_doc["decisions"])
            self.assertEqual("1.0.0", ledger_doc["schema_version"])

            # `report.json` en sí no debe contener la clave privada del ledger:
            # `main()` la retira antes de validar/renderizar.
            report_doc = json.loads((with_review / "report.json").read_text(encoding="utf-8"))
            self.assertNotIn("_review_ledger", report_doc)

    def test_design_patterns_check_is_normalized_and_merged_into_dimensions_and_findings(self) -> None:
        """Both edits build_report.py needs are exercised here: SUPPORTED_FORMATS
        (or _auto_fragment never even tries) and the `candidates` entry (or it tries
        and finds nothing) — see design-patterns-module/05-hallazgos-codigo.md."""
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as artifacts:
            output = Path(artifacts) / "design-patterns.json"
            output.write_text(json.dumps({
                "schema_version": "1.0.0", "files_scanned": 2, "languages": ["python"],
                "patterns": [
                    {
                        "pattern_id": "adapter", "status": "detected", "confidence": "medium",
                        "primary_location": {"file": "a.py", "line": 1},
                        "roles": {"target": "T", "adapter": "A", "adaptee": "D"},
                        "evidence": [], "contradictions": [],
                    },
                    {
                        "pattern_id": "strategy", "status": "refactor-opportunity", "confidence": "medium",
                        "primary_location": {"file": "calc.py", "line": 4},
                        "roles": {"discriminator_site_1": "X", "discriminator_site_2": "Y"},
                        "evidence": [{"kind": "hard", "description": "shared discriminator"}],
                        "contradictions": [],
                        "refactoring": {
                            "smell": "repeated conditional dispatch", "candidate_pattern": "strategy",
                            "sites": ["X", "Y"],
                        },
                    },
                ],
                "limitations": [],
            }), encoding="utf-8")
            execution = {
                "root": project, "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z",
                "checks": [{
                    "id": "universal.design-patterns", "name": "design-patterns", "category": "quality",
                    "status": "passed", "command": "python analyze_design_patterns.py", "exit_code": 0,
                    "duration_ms": 5, "stdout": "", "stderr": "",
                    "artifact_dir": artifacts, "output_format": "design-patterns",
                    "required": False, "reason": "", "gate": False, "effective_scope": "repository",
                }],
            }
            report = build_report.build(execution, [])
            self.assertEqual(1, len(report["findings"]))
            self.assertEqual("pbp.pattern.strategy.opportunity", report["findings"][0]["rule_id"])
            self.assertEqual("quality", report["findings"][0]["category"])
            design_patterns = report["summary"]["dimensions"]["design_patterns"]
            self.assertEqual(1, design_patterns["detected"])
            self.assertEqual(1, design_patterns["refactor_opportunities"])
            self.assertEqual("findings", report["tools"][0]["status"])

    def test_first_audit_of_a_repository_succeeds_when_quality_audit_does_not_exist_yet(self) -> None:
        """Regresión: en el primer audit de un repositorio, `<repo>/.quality-audit/`
        (el padre de `--output-dir` si se sigue la convención documentada en
        SKILL.md) todavía no existe. El fichero de staging se escribía sin
        crear ese directorio antes, así que la primera ejecución siempre
        fallaba con un `FileNotFoundError` cuya causa real quedaba oculta."""
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            execution = {
                "root": str(root), "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-13T12:00:00Z", "checks": [],
            }
            execution_path = root / "execution.json"
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            output_dir = root / ".quality-audit" / "20260813T120000Z"
            self.assertFalse((root / ".quality-audit").exists())
            argv = sys.argv
            try:
                sys.argv = ["build_report.py", str(execution_path), "--output-dir", str(output_dir)]
                self.assertEqual(0, build_report.main())
            finally:
                sys.argv = argv
            self.assertTrue((output_dir / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()


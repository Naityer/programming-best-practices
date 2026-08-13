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

if __name__ == "__main__":
    unittest.main()


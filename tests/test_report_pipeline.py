from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

scripts = SKILL / "scripts"
sys.path.insert(0, str(scripts))
validate_report = load_module("validate_report", scripts / "validate_report.py")
render_report = load_module("render_report", scripts / "render_report.py")


def sample_report() -> dict:
    finding = {
        "id": "F-001",
        "fingerprint": "same-root-cause",
        "rule_id": "security.hardcoded-secret",
        "title": "Credential embedded in source",
        "category": "security",
        "severity": "blocker",
        "confidence": "high",
        "locations": [{"file": "src/app.py", "line": 4, "column": 1}],
        "evidence": [
            {
                "source_type": "tool",
                "source": "gitleaks",
                "message": "token=super-secret-value was detected",
            }
        ],
        "impact": "An attacker with repository access can reuse the credential.",
        "recommendation": "Revoke it, remove it from code and history, and load a replacement from a secret store.",
    }
    duplicate = json.loads(json.dumps(finding))
    duplicate["id"] = "F-002"
    duplicate["severity"] = "high"
    duplicate["confidence"] = "medium"
    duplicate["evidence"] = [
        {
            "source_type": "llm",
            "source": "semantic-review",
            "message": "The value is used as an authorization token.",
        }
    ]
    return {
        "schema_version": "1.0.0",
        "audit": {
            "repository": "sample",
            "profile": "standard",
            "scope": "changed files",
            "mode": "audit",
            "generated_at": "2026-08-13T12:00:00Z",
            "outcome": "fail",
        },
        "summary": {
            "finding_counts": {"blocker": 1, "high": 1, "medium": 0, "low": 0},
            "dimensions": {"coverage": {"branch": 72}},
        },
        "tools": [
            {"name": "gitleaks", "status": "findings", "command": "gitleaks git", "exit_code": 1, "duration_ms": 10},
            {"name": "semgrep", "status": "unavailable", "reason": "not installed"},
        ],
        "findings": [finding, duplicate],
        "limitations": ["Semgrep was unavailable.", "Semgrep was unavailable."],
    }


class ReportPipelineTests(unittest.TestCase):
    def test_validates_and_renders_all_formats(self) -> None:
        data = sample_report()
        self.assertEqual([], validate_report.validate_report(data))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            destination = render_report.render(input_path, root)
            self.assertTrue((destination / "report.md").is_file())
            self.assertTrue((destination / "report.json").is_file())
            self.assertTrue((destination / "report.sarif").is_file())

            normalized_text = (destination / "report.json").read_text(encoding="utf-8")
            self.assertNotIn("super-secret-value", normalized_text)
            normalized = json.loads(normalized_text)
            self.assertEqual(1, len(normalized["findings"]))
            self.assertEqual(2, len(normalized["findings"][0]["evidence"]))
            self.assertEqual({"blocker": 1, "high": 0, "medium": 0, "low": 0}, normalized["summary"]["finding_counts"])
            self.assertEqual(["Semgrep was unavailable."], normalized["limitations"])

            sarif = json.loads((destination / "report.sarif").read_text(encoding="utf-8"))
            self.assertEqual("2.1.0", sarif["version"])
            self.assertEqual("error", sarif["runs"][0]["results"][0]["level"])
            properties = sarif["runs"][0]["results"][0]["properties"]
            self.assertEqual(normalized["findings"][0]["impact"], properties["impact"])
            self.assertEqual(normalized["findings"][0]["recommendation"], properties["recommendation"])
            self.assertNotIn("informationUri", sarif["runs"][0]["tool"]["driver"])
            markdown = (destination / "report.md").read_text(encoding="utf-8")
            self.assertIn("Semgrep was unavailable", markdown)
            self.assertIn("UNAVAILABLE", markdown.upper())

    def test_matches_golden_outputs(self) -> None:
        input_path = SKILL.parents[1] / "tests" / "fixtures" / "golden-input.json"
        golden = SKILL.parents[1] / "tests" / "golden"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = render_report.render(input_path, root)
            for name in ("report.md", "report.json", "report.sarif"):
                self.assertEqual(
                    (golden / name).read_text(encoding="utf-8"),
                    (destination / name).read_text(encoding="utf-8"),
                    name,
                )
    def test_never_overwrites_default_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(sample_report()), encoding="utf-8")
            first = render_report.render(input_path, root)
            second = render_report.render(input_path, root)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_rejects_invalid_specification_oracle(self) -> None:
        data = sample_report()
        data["findings"] = [data["findings"][0]]
        data["findings"][0]["oracle"] = {"type": "specification"}
        errors = validate_report.validate_report(data)
        self.assertTrue(any("oracle.source" in error for error in errors))

    def test_rejects_unexpected_fields(self) -> None:
        data = sample_report()
        data["quality_score"] = 100
        data["tools"][0]["unexpected"] = True
        errors = validate_report.validate_report(data)
        self.assertTrue(any("$.quality_score" in error for error in errors))
        self.assertTrue(any("$.tools[0].unexpected" in error for error in errors))
    def test_rejects_unavailable_as_unknown_status(self) -> None:
        data = sample_report()
        data["tools"][0]["status"] = "ok"
        errors = validate_report.validate_report(data)
        self.assertTrue(any("$.tools[0].status" in error for error in errors))


if __name__ == "__main__":
    unittest.main()





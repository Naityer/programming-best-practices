from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

export_verdict = load_module("export_verdict_t", SKILL / "scripts" / "export_verdict.py")


def _report() -> dict:
    return {
        "audit": {"repository": "demo", "generated_at": "2026-11-05T10:00:00Z", "profile": "standard", "scope": "repository", "outcome": "incomplete"},
        "findings": [{"severity": "blocker"}, {"severity": "high"}, {"severity": "medium"}, {"severity": "low"}, {"severity": "low"}],
        "tools": [{"name": "t1", "status": "passed"}, {"name": "t2", "status": "timed_out", "gate": True}, {"name": "t3", "status": "skipped"}],
    }


class VerdictTests(unittest.TestCase):
    def test_blockers_count_as_graves(self) -> None:
        verdict = export_verdict.build_verdict(_report(), Path("report.json"))
        self.assertEqual({"blocker": 1, "high": 1, "medium": 1, "low": 2}, verdict["counts"])
        self.assertEqual(2, verdict["graves"])
        self.assertEqual(["t2"], verdict["incomplete_required"])
        self.assertFalse(verdict["semantic_review"]["done"])

    def test_review_ledger_is_summarised(self) -> None:
        ledger = {"decisions": [{"action": "confirm"}, {"action": "dismiss"}, {"action": "dismiss"}]}
        verdict = export_verdict.build_verdict(_report(), Path("report.json"), ledger)
        self.assertEqual({"done": True, "confirmed": 1, "dismissed": 2}, verdict["semantic_review"])

    def test_cli_writes_verdict_next_to_report(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "report.json").write_text(json.dumps(_report()), encoding="utf-8")
            done = subprocess.run([sys.executable, str(SKILL / "scripts" / "export_verdict.py"), d], capture_output=True, text=True)
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual("demo", json.loads((Path(d) / "verdict.json").read_text(encoding="utf-8"))["repository"])

    def test_missing_report_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            done = subprocess.run([sys.executable, str(SKILL / "scripts" / "export_verdict.py"), d], capture_output=True, text=True)
            self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()


class CoverageGapTests(unittest.TestCase):
    def test_unanalyzed_code_and_tools_not_run_are_declared(self) -> None:
        report = _report()
        report["limitations"] = ["TypeScript design-pattern frontend is not operational; 94 source file(s) were not analyzed.", "otra cosa"]
        verdict = export_verdict.build_verdict(report, Path("report.json"))
        self.assertEqual(1, len(verdict["coverage_gaps"]))
        self.assertEqual(["t2", "t3"], verdict["tools_not_run"])

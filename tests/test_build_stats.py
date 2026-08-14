from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.helpers import ROOT, SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
build_stats = load_module("build_stats", SKILL / "scripts" / "build_stats.py")
render_stats = load_module("render_stats_for_stats", SKILL / "scripts" / "render_stats.py")


def _ts_iso(stamp: str) -> str:
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_report(root: Path, stamp: str, *, blocker=0, high=1, medium=0, low=0,
                   coverage: float | None = None, findings: list | None = None,
                   tools: list | None = None) -> Path:
    run_dir = root / ".quality-audit" / stamp
    run_dir.mkdir(parents=True)
    dimensions = {"coverage": {"line_percent": coverage}} if coverage is not None else {}
    report = {
        "schema_version": "1.0.0",
        "audit": {
            "repository": root.name, "profile": "standard", "scope": "repository",
            "mode": "audit", "generated_at": _ts_iso(stamp), "outcome": "informational",
        },
        "summary": {
            "finding_counts": {"blocker": blocker, "high": high, "medium": medium, "low": low},
            "dimensions": dimensions,
        },
        "tools": tools if tools is not None else [],
        "findings": findings if findings is not None else [],
        "limitations": [],
    }
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return run_dir


def _write_ledger(run_dir: Path, stamp: str, decisions: list) -> None:
    (run_dir / "review-ledger.json").write_text(json.dumps({
        "schema_version": "1.0.0", "repository": run_dir.parent.parent.parent.name,
        "generated_at": _ts_iso(stamp), "decisions": decisions,
    }), encoding="utf-8")


def _finding(fingerprint: str, *, tool="semgrep", source_type="tool", rule_id="security.shell",
             category="security", severity="high", confidence="medium", file="app.py", line=1) -> dict:
    return {
        "id": f"F-{fingerprint}", "fingerprint": fingerprint, "rule_id": rule_id, "title": "Finding",
        "category": category, "severity": severity, "confidence": confidence,
        "locations": [{"file": file, "line": line}],
        "evidence": [{"source_type": source_type, "source": tool, "message": "match"}],
        "impact": "x", "recommendation": "y",
    }


def _decision(fingerprint: str, action: str, *, source_types, primary_source="semgrep") -> dict:
    return {
        "decision_id": f"d-{fingerprint}-{action}", "action": action, "reason": "reviewed",
        "reviewed_at": None, "reviewer": "agent-semantic-review", "overrides": None, "unmatched": False,
        "matched": [{
            "fingerprint": fingerprint, "rule_id": "security.shell", "category": "security",
            "severity": "high", "confidence": "medium", "locations": [{"file": "app.py", "line": 1}],
            "evidence_source_types": source_types, "primary_source": primary_source, "primary_message": "match",
        }],
    }


class DiscoverRunsTests(unittest.TestCase):
    def test_orders_chronologically_and_respects_max_runs(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z")
            _write_report(root, "20260805T090000Z")
            _write_report(root, "20260810T090000Z")
            runs = build_stats.discover_runs(root, max_runs=2)
            self.assertEqual(["20260805T090000Z", "20260810T090000Z"], [r["dir"].name for r in runs])

    def test_ledger_is_none_when_the_file_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z")
            runs = build_stats.discover_runs(root)
            self.assertIsNone(runs[0]["ledger"])


class BuildStatsTests(unittest.TestCase):
    def test_zero_runs_raises_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            with self.assertRaises(ValueError):
                build_stats.build(root, [], plan=None)

    def test_single_run_has_null_stddev_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z", coverage=60.0)
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            series = stats["trends"]["dimensions"]["coverage.line_percent"]
            self.assertEqual(1, series["n"])
            self.assertIsNone(series["stdev"])
            self.assertEqual("insufficient_data", series["direction"])

    def test_current_run_matches_the_latest_report(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z", high=2)
            _write_report(root, "20260810T090000Z", high=1)
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            self.assertEqual(".quality-audit/20260810T090000Z", stats["current_run"]["run_dir"])
            self.assertEqual(1, stats["current_run"]["finding_counts"]["high"])

    def test_report_without_category_or_output_format_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z", tools=[{"name": "old.tool (tool)", "status": "passed"}])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            entry = stats["by_tool"]["old.tool (tool)"]
            self.assertIsNone(entry["measurement_domain"])
            self.assertEqual("not-registered", entry["measurement_domain_source"])

    def test_tool_confirmation_and_false_positive_rates_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            tools = [{"name": "universal.semgrep (semgrep)", "status": "findings", "duration_ms": 10,
                      "category": "security", "output_format": "semgrep"}]
            run1 = _write_report(root, "20260801T090000Z", findings=[_finding("fp-1"), _finding("fp-2")], tools=tools)
            _write_ledger(run1, "20260801T090000Z", [
                _decision("fp-1", "confirm", source_types=["tool"]),
                _decision("fp-2", "dismiss", source_types=["tool"]),
            ])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None, min_sample=1)
            rate = stats["review"]["tool_findings"]
            self.assertEqual(2, rate["reviewed"])
            self.assertEqual(1, rate["confirmed"])
            self.assertEqual(1, rate["dismissed"])
            self.assertEqual(0.5, rate["confirmation_rate"])
            self.assertEqual(0.5, rate["false_positive_rate"])

    def test_agent_hallucination_rate_only_counts_strictly_llm_only_findings(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            run1 = _write_report(root, "20260801T090000Z", findings=[
                _finding("fp-llm", source_type="llm", tool="semantic-review"),
                _finding("fp-mixed", source_type="tool"),
            ])
            _write_ledger(run1, "20260801T090000Z", [
                _decision("fp-llm", "dismiss", source_types=["llm"], primary_source="semantic-review"),
                # Evidencia mixta tool+llm: cuenta como tool-sourced, nunca como alucinación del agente.
                _decision("fp-mixed", "dismiss", source_types=["tool", "llm"], primary_source="semgrep"),
            ])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None, min_sample=1)
            llm_rate = stats["review"]["agent_llm_only_findings"]
            self.assertEqual(1, llm_rate["reviewed"])
            self.assertEqual(0, llm_rate["confirmed"])
            self.assertEqual(1, llm_rate["dismissed"])
            self.assertEqual(1.0, llm_rate["false_positive_rate"])
            tool_rate = stats["review"]["tool_findings"]
            self.assertEqual(1, tool_rate["reviewed"])
            self.assertEqual(1, tool_rate["dismissed"])

    def test_rates_below_min_sample_are_null_with_a_warning_flag(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            run1 = _write_report(root, "20260801T090000Z", findings=[_finding("fp-1")])
            _write_ledger(run1, "20260801T090000Z", [_decision("fp-1", "confirm", source_types=["tool"])])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None, min_sample=5)
            rate = stats["review"]["tool_findings"]
            self.assertIsNone(rate["confirmation_rate"])
            self.assertIsNone(rate["confirmation_rate_ci95"])
            self.assertTrue(rate["sample_size_warning"])

    def test_location_conflicts_detected_across_tools_at_the_same_file_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z", findings=[
                _finding("fp-a", tool="semgrep", severity="high", rule_id="pbp.a"),
                _finding("fp-b", tool="ruff", severity="low", rule_id="B008"),
            ])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            conflicts = stats["anomalies"]["location_conflicts"]
            self.assertEqual(1, len(conflicts))
            self.assertEqual("app.py", conflicts[0]["file"])
            self.assertEqual(2, len(conflicts[0]["entries"]))

    def test_findings_on_removed_code_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            _write_report(root, "20260801T090000Z", findings=[_finding("fp-1", file="deleted.py")])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            removed = stats["anomalies"]["findings_on_removed_code"]
            self.assertEqual(1, len(removed))
            self.assertEqual("deleted.py", removed[0]["file"])

    def test_decision_reversal_detected_when_the_same_fingerprint_is_confirmed_then_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            run1 = _write_report(root, "20260801T090000Z", findings=[_finding("fp-1")])
            _write_ledger(run1, "20260801T090000Z", [_decision("fp-1", "confirm", source_types=["tool"])])
            run2 = _write_report(root, "20260805T090000Z", findings=[])
            _write_ledger(run2, "20260805T090000Z", [_decision("fp-1", "dismiss", source_types=["tool"])])
            runs = build_stats.discover_runs(root)
            stats = build_stats.build(root, runs, plan=None)
            reversals = stats["anomalies"]["decision_reversals"]
            self.assertEqual(1, len(reversals))
            self.assertEqual("fp-1", reversals[0]["fingerprint"])
            self.assertEqual({"confirm", "dismiss"}, {entry["action"] for entry in reversals[0]["history"]})

    def test_never_overwrites_an_existing_stats_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            root.mkdir(exist_ok=True)
            existing = root / "already-there"
            existing.mkdir()
            with self.assertRaises(FileExistsError):
                build_stats._new_output_dir(root, existing)

    def test_matches_golden_outputs(self) -> None:
        fixture_root = (ROOT / "tests" / "fixtures" / "stats-history").resolve()
        golden = ROOT / "tests" / "golden"
        runs = build_stats.discover_runs(fixture_root)
        now = datetime(2026, 8, 14, 17, 0, 0, tzinfo=timezone.utc)
        stats = build_stats.build(fixture_root, runs, plan=None, min_sample=1, now=now)
        stats["root"] = "<root>"  # la ruta absoluta del fixture varía por checkout; no forma parte de lo comparado
        self.assertEqual(
            (golden / "stats.json").read_text(encoding="utf-8"),
            json.dumps(stats, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        self.assertEqual((golden / "stats.md").read_text(encoding="utf-8"), render_stats._markdown(stats))
        self.assertEqual((golden / "stats.html").read_text(encoding="utf-8"), render_stats._html(stats))


if __name__ == "__main__":
    unittest.main()

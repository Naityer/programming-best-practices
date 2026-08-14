from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
render_stats = load_module("render_stats", SKILL / "scripts" / "render_stats.py")


class BarChartSvgTests(unittest.TestCase):
    def test_produces_a_valid_svg_root_with_one_bar_per_value(self) -> None:
        svg = render_stats._bar_chart_svg({"blocker": 0.0, "high": 3.0, "low": 1.0}, title="Findings")
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        rects = [el for el in root.iter() if el.tag.endswith("rect")]
        self.assertEqual(3, len(rects))

    def test_empty_input_renders_a_placeholder_not_a_crash(self) -> None:
        svg = render_stats._bar_chart_svg({}, title="Nothing")
        self.assertIn("no data", svg)
        ET.fromstring(svg)  # sigue siendo XML válido

    def test_labels_containing_markup_are_escaped_not_injected(self) -> None:
        svg = render_stats._bar_chart_svg({"<script>alert(1)</script>": 1.0}, title="Title")
        self.assertNotIn("<script>alert(1)</script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        ET.fromstring(svg)  # si el escape fallara, esto no parsearía como XML


class LineChartSvgTests(unittest.TestCase):
    def test_produces_one_path_per_series(self) -> None:
        svg = render_stats._line_chart_svg(
            {"blocker": [("2026-01-01", 0.0), ("2026-01-02", 1.0)], "high": [("2026-01-01", 2.0), ("2026-01-02", 1.0)]},
            title="Trend",
        )
        root = ET.fromstring(svg)
        paths = [el for el in root.iter() if el.tag.endswith("path")]
        self.assertEqual(2, len(paths))

    def test_empty_input_renders_a_placeholder_not_a_crash(self) -> None:
        svg = render_stats._line_chart_svg({}, title="Nothing")
        self.assertIn("no data", svg)
        ET.fromstring(svg)


class ContingencyTableHtmlTests(unittest.TestCase):
    def test_renders_a_row_per_tool_and_escapes_user_text(self) -> None:
        html = render_stats._contingency_table_html(
            {"<b>tool</b>": {"confirmed": 2, "dismissed": 1}},
            row_label="Tool", col_labels=["confirmed", "dismissed", "unreviewed"],
        )
        self.assertNotIn("<b>tool</b>", html)
        self.assertIn("&lt;b&gt;tool&lt;/b&gt;", html)
        self.assertIn("<table", html)


class MarkdownAndHtmlSmokeTests(unittest.TestCase):
    def _minimal_stats(self) -> dict:
        return {
            "schema_version": "1.0.0", "generated_at": "2026-08-14T17:00:00Z",
            "repository": "demo", "root": "/tmp/demo", "source_runs_considered": 1,
            "source_runs": [], "findings_timeline": [],
            "current_run": {
                "run_dir": ".quality-audit/x", "generated_at": "2026-08-14T17:00:00Z",
                "profile": "standard", "scope": "repository", "outcome": "informational",
                "finding_counts": {"blocker": 0, "high": 0, "medium": 0, "low": 0},
                "dimensions_snapshot": {},
            },
            "by_tool": {}, "by_category": {},
            "review": {
                "runs_with_ledger": 0, "runs_without_ledger": 1, "decisions_considered": 0,
                "tool_findings": {"reviewed": 0, "confirmed": 0, "dismissed": 0, "confirmation_rate": None,
                                   "false_positive_rate": None, "confirmation_rate_ci95": None,
                                   "false_positive_rate_ci95": None, "sample_size_warning": True, "by_tool": {}},
                "agent_llm_only_findings": {"reviewed": 0, "confirmed": 0, "dismissed": 0, "confirmation_rate": None,
                                             "false_positive_rate": None, "confirmation_rate_ci95": None,
                                             "false_positive_rate_ci95": None, "sample_size_warning": True},
                "unreviewed_findings": {"count": 0}, "note": "note text",
            },
            "trends": {"finding_counts": {}, "dimensions": {}},
            "anomalies": {"location_conflicts": [], "stale_baselines": [], "decision_reversals": [], "findings_on_removed_code": []},
            "limitations": [],
        }

    def test_markdown_contains_the_expected_sections(self) -> None:
        text = render_stats._markdown(self._minimal_stats())
        for heading in ("# Statistics: demo", "## Current run", "## Review", "## By tool", "## Trends", "## Anomalies", "## Limitations"):
            self.assertIn(heading, text)

    def test_html_is_well_formed_and_self_contained(self) -> None:
        html = render_stats._html(self._minimal_stats())
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("<script", html)
        self.assertTrue(re.search(r"<title>Statistics: demo</title>", html))


if __name__ == "__main__":
    unittest.main()

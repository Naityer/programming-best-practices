from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

sys.path.insert(0, str(SKILL / "scripts"))
validate_review_ledger = load_module(
    "validate_review_ledger", SKILL / "scripts" / "validate_review_ledger.py"
)


def ledger(decisions: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0", "repository": "sample",
        "generated_at": "2026-08-20T12:00:00Z", "decisions": decisions,
    }


def decision(**overrides) -> dict:
    base = {
        "decision_id": "d-1", "action": "dismiss", "reason": "trusted constant",
        "unmatched": False, "matched": [],
    }
    base.update(overrides)
    return base


class ReviewerTierPatternTests(unittest.TestCase):
    """Spec's 3-tier hierarchy (skill/agent/human) enforced at the schema
    boundary — see design-patterns-module/02-decisiones.md and 04-progreso.md
    Fase 3."""

    def test_accepts_bare_tier_names(self) -> None:
        for tier in ("skill", "agent", "human"):
            errors = validate_review_ledger.validate_review_ledger(
                ledger([decision(reviewer=tier)])
            )
            self.assertEqual([], errors, msg=f"tier={tier}")

    def test_accepts_tier_with_free_text_suffix(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(reviewer="human:jane.doe")])
        )
        self.assertEqual([], errors)

    def test_rejects_a_tier_not_in_the_hierarchy(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(reviewer="robot")])
        )
        self.assertTrue(any("reviewer" in e for e in errors))

    def test_rejects_the_old_free_text_convention(self) -> None:
        """agent-semantic-review (hyphen, no tier prefix) was the previous
        default — the whole point of this guardrail is that it no longer
        validates, so build_stats.py can trust the field means something."""
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(reviewer="agent-semantic-review")])
        )
        self.assertTrue(any("reviewer" in e for e in errors))

    def test_reviewer_is_optional(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(ledger([decision()]))
        self.assertEqual([], errors)


class StructuralValidationTests(unittest.TestCase):
    def test_valid_ledger_round_trips_clean(self) -> None:
        data = ledger([decision(
            reviewer="agent:semantic-review",
            matched=[{
                "fingerprint": "fp-1", "rule_id": "pbp.pattern.singleton.misimplemented",
                "category": "quality", "severity": "medium", "confidence": "medium",
                "locations": [{"file": "registry.py", "line": 5}],
                "evidence_source_types": ["tool"], "primary_source": "design-patterns", "primary_message": "x",
            }],
        )])
        self.assertEqual([], validate_review_ledger.validate_review_ledger(data))

    def test_rejects_missing_top_level_field(self) -> None:
        data = ledger([])
        del data["repository"]
        errors = validate_review_ledger.validate_review_ledger(data)
        self.assertTrue(any("repository" in e for e in errors))

    def test_rejects_unknown_action(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(action="approve")])
        )
        self.assertTrue(any("action" in e for e in errors))

    def test_rejects_duplicate_decision_id(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(decision_id="dup"), decision(decision_id="dup")])
        )
        self.assertTrue(any("duplicate id" in e for e in errors))

    def test_rejects_bad_evidence_source_type(self) -> None:
        data = ledger([decision(matched=[{"evidence_source_types": ["magic"]}])])
        errors = validate_review_ledger.validate_review_ledger(data)
        self.assertTrue(any("evidence_source_types" in e for e in errors))

    def test_rejects_unexpected_field(self) -> None:
        errors = validate_review_ledger.validate_review_ledger(
            ledger([decision(quality_score=100)])
        )
        self.assertTrue(any("quality_score" in e for e in errors))


class BuildReportRejectsBadReviewerTests(unittest.TestCase):
    """The guardrail must actually be wired in, not just exist as a script."""

    def test_build_report_main_aborts_on_an_invalid_reviewer_tier(self) -> None:
        build_report = load_module("build_report_ledger_guard", SKILL / "scripts" / "build_report.py")
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            execution = {
                "root": str(root), "profile": "standard", "scope": "repository",
                "generated_at": "2026-08-20T12:00:00Z", "checks": [],
            }
            execution_path = root / "execution.json"
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            review_path = root / "review.json"
            review_path.write_text(json.dumps({"decisions": [{
                "fingerprint": "does-not-matter", "action": "dismiss", "reason": "n/a",
                "reviewer": "not-a-real-tier",
            }]}), encoding="utf-8")
            output_dir = root / "out"
            argv = sys.argv
            try:
                sys.argv = [
                    "build_report.py", str(execution_path), "--output-dir", str(output_dir),
                    "--semantic-review", str(review_path),
                ]
                exit_code = build_report.main()
            finally:
                sys.argv = argv
            self.assertEqual(2, exit_code)


if __name__ == "__main__":
    unittest.main()

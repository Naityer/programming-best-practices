#!/usr/bin/env python3
"""Measure the design-pattern module against an explicit functional rubric.

The score is evidence-based and scope-labelled. It does not claim equivalent
language support: frontend breadth is penalized independently.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))

from design_patterns.catalog import load_catalog
from design_patterns.detectors import registry
from design_patterns.misimplementations import SUPPORTED_MISIMPLEMENTATIONS
from design_patterns.opportunities import SUPPORTED_OPPORTUNITIES

TARGET_LANGUAGES = 8
POSITIVE_SCENARIOS = 22
NAME_NEGATIVE_SCENARIOS = 22
PARTIAL_SCENARIOS = 22
LOOKALIKE_SCENARIOS = 15
ACTIVE_FRONTENDS = 1


def _criterion(name: str, earned: float, possible: float, evidence: str) -> dict:
    return {"name": name, "earned": round(earned, 2), "possible": possible, "evidence": evidence}


def _section(criteria: list[dict]) -> dict:
    earned = sum(item["earned"] for item in criteria)
    possible = sum(item["possible"] for item in criteria)
    return {"score": round(100 * earned / possible, 1), "criteria": criteria}


def compute_index(*, suite_passed: bool) -> dict:
    catalog_count = len(load_catalog())
    detector_count = len(registry())
    gate = 1.0 if suite_passed else 0.0

    detection = _section([
        _criterion("catalog and registered detectors", 20 * min(catalog_count, detector_count) / 22, 20, f"{catalog_count} catalog / {detector_count} detectors"),
        _criterion("positive fixtures", 20 * POSITIVE_SCENARIOS / 22 * gate, 20, f"{POSITIVE_SCENARIOS}/22; full suite {'passed' if suite_passed else 'failed'}"),
        _criterion("name-only false positives", 15 * NAME_NEGATIVE_SCENARIOS / 22 * gate, 15, f"{NAME_NEGATIVE_SCENARIOS}/22"),
        _criterion("partial and lookalike scenarios", 15 * (PARTIAL_SCENARIOS + LOOKALIKE_SCENARIOS) / 44 * gate, 15, f"partial {PARTIAL_SCENARIOS}/22; lookalike {LOOKALIKE_SCENARIOS}/22"),
        _criterion("role binding and UML contract", 10 * gate, 10, "guardrail and UML regression suites"),
        _criterion("frontend breadth", 10 * ACTIVE_FRONTENDS / TARGET_LANGUAGES * gate, 10, f"{ACTIVE_FRONTENDS}/{TARGET_LANGUAGES} operational frontends"),
        _criterion("pipeline integration", 10 * gate, 10, "plan -> analyze -> normalize -> report -> SARIF"),
    ])

    correction = _section([
        _criterion("misimplementation pattern breadth", 20 * len(SUPPORTED_MISIMPLEMENTATIONS) / 22 * gate, 20, f"{len(SUPPORTED_MISIMPLEMENTATIONS)}/22 conservative rules"),
        _criterion("intent plus structural guardrail", 20 * gate, 20, "name-only negative plus partial-structure positives"),
        _criterion("structured correction plan", 20 * gate, 20, "steps, verification, behavior-preserving and semantic-review flags"),
        _criterion("normalized actionable finding", 15 * gate, 15, "misimplemented -> medium quality finding"),
        _criterion("agent/human review hierarchy", 10 * gate, 10, "semantic review and constrained review ledger"),
        _criterion("integration and verification", 15 * gate, 15, "analyzer integration and remediation regressions"),
    ])

    suggestions = _section([
        _criterion("opportunity pattern breadth", 30 * len(SUPPORTED_OPPORTUNITIES) / 22 * gate, 30, f"{len(SUPPORTED_OPPORTUNITIES)}/22 evidence-backed opportunity detectors"),
        _criterion("observed-smell guardrail", 20 * gate, 20, "no suggestion from absence or name alone"),
        _criterion("structured refactoring plan", 20 * gate, 20, "candidate, sites, steps and verification"),
        _criterion("report and SARIF propagation", 15 * gate, 15, "low-severity opportunity finding"),
        _criterion("semantic review", 10 * gate, 10, "confirm/dismiss with reason"),
        _criterion("pipeline integration", 5 * gate, 5, "end-to-end opportunity regression"),
    ])

    global_score = round(0.50 * detection["score"] + 0.25 * correction["score"] + 0.25 * suggestions["score"], 1)
    return {
        "schema_version": "1.0.0",
        "scope": "Python frontend + language-neutral IR/detectors + report/audit_code interchange",
        "weights": {"detection": 0.50, "correction": 0.25, "suggestions": 0.25},
        "detection": detection,
        "correction": correction,
        "suggestions": suggestions,
        "functional_global_index": global_score,
        "target_met": global_score > 80.0,
        "suite_passed": suite_passed,
        "limitations": [
            "Only Python has a production frontend; the score explicitly penalizes frontend breadth.",
            "Pattern breadth for misimplementations and opportunities is reported separately and is not hidden by pipeline capabilities.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-tests", action="store_true", help="Measure structure only; test-backed points score zero")
    args = parser.parse_args()
    suite_passed = False
    if not args.skip_tests:
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=REPO_ROOT)
        suite_passed = completed.returncode == 0
    result = compute_index(suite_passed=suite_passed)
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

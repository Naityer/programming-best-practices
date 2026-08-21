#!/usr/bin/env python3
"""Evidence-based functional index for Algorithm Intelligence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from evaluate_algorithms import evaluate

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
CATALOG = SCRIPT_DIR.parent / "references" / "algorithms" / "catalog.json"
CATALOG_CASES = REPO_ROOT / "evals" / "algorithms" / "catalog-case-contracts.json"
CORE_CASES = REPO_ROOT / "evals" / "algorithms" / "cases.json"
EMPIRICAL_CASES = REPO_ROOT / "evals" / "algorithms" / "empirical-cases.json"
TARGET_SECTIONS = set(range(6, 25))
ECOSYSTEMS = {"python", "jvm", "js-ts", "dotnet", "go", "rust", "cpp"}


def _criterion(name: str, passed: bool, possible: float, evidence: str) -> dict:
    return {"name": name, "earned": possible if passed else 0.0, "possible": possible, "evidence": evidence}


def _section(criteria: list[dict]) -> dict:
    earned = sum(item["earned"] for item in criteria)
    possible = sum(item["possible"] for item in criteria)
    return {"score": round(100 * earned / possible, 1), "criteria": criteria}


def _catalog_evidence() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    contracts = json.loads(CATALOG_CASES.read_text(encoding="utf-8"))
    entries = catalog.get("algorithms", [])
    groups = {group["algorithm_id"]: group.get("cases", []) for group in contracts.get("algorithms", [])}
    sections = {
        int(match.group()) for entry in entries for reference in entry.get("references", [])
        if (match := re.search(r"\d+", str(reference))) and int(match.group()) in TARGET_SECTIONS
    }
    complete_contracts = all(
        {case.get("kind") for case in groups.get(entry["id"], [])}
        == {"positive", "negative", "misuse", "alternative", "edge"}
        for entry in entries
    )
    return {
        "entries": len(entries), "families": len(set(entry["family"] for entry in entries)),
        "sections": sorted(sections), "contracts": sum(len(value) for value in groups.values()),
        "complete": len(entries) >= 100 and sections == TARGET_SECTIONS and complete_contracts,
    }


def _cross_language_covered() -> bool:
    corpus = json.loads(EMPIRICAL_CASES.read_text(encoding="utf-8"))
    identifiers = {case["id"] for case in corpus.get("cases", [])}
    return all(
        {f"repeated-membership-{ecosystem}", f"repeated-concat-{ecosystem}", f"all-pairs-negative-{ecosystem}"} <= identifiers
        for ecosystem in ECOSYSTEMS
    )


def compute_index(*, suite_passed: bool) -> dict:
    catalog = _catalog_evidence()
    core = evaluate(CORE_CASES)
    empirical = evaluate(EMPIRICAL_CASES)
    cross_language = _cross_language_covered() and empirical["production_thresholds_met"]
    catalog_ok = catalog["complete"] and suite_passed
    empirical_ok = empirical["production_thresholds_met"] and suite_passed
    detection = _section([
        _criterion("Atlas core misuse cases", core["production_thresholds_met"] and suite_passed, 20, "8 positive core cases plus required negatives"),
        _criterion("Atlas 6-24 catalog and executable contracts", catalog_ok, 20, f"{catalog['entries']} entries; {catalog['contracts']} executed contracts; sections={catalog['sections']}"),
        _criterion("structured ecosystem frontends", suite_passed, 15, "Python AST plus pinned Tree-sitter for 7/7 ecosystems"),
        _criterion("cross-language behavioral consistency", cross_language, 10, "membership, concatenation and all-pairs guardrail across 7/7 ecosystems"),
        _criterion("CFG/DFG and complexity inference", suite_passed, 15, "single, nested, sequential, binary-reduction and sort contracts"),
        _criterion("false-positive corpus", empirical_ok, 10, f"precision={empirical['recognition_precision']:.1%}; FP={empirical['counts']['false_positive']}"),
        _criterion("pipeline, cache and artifact schema", suite_passed, 10, "STANDARD/DEEP, external content cache, JSON/Markdown/SARIF"),
    ])
    correction = _section([
        _criterion("hard-requirement safety gate", suite_passed, 25, "UNKNOWN/CONTRADICTED never produce SAFE"),
        _criterion("SAFE policy and representative transformations", suite_passed, 25, "literal min/max plus bounded membership hoist; all hard requirements PROVEN"),
        _criterion("ASSISTED/MANUAL/BLOCKED policy", suite_passed, 15, "fail-closed correction levels covered"),
        _criterion("validation strategies", suite_passed, 10, "reanalyze, differential, property and benchmark strategies"),
        _criterion("semantic preservation corpus", suite_passed, 10, "100% for every shipped SAFE fixture"),
        _criterion("human review feedback contract", suite_passed, 15, "stable rule IDs and review-ledger contract; full E2E remains a joint gate"),
    ])
    suggestions = _section([
        _criterion("Problem Signature centered output", suite_passed, 20, "canonical signatures shared across ecosystems"),
        _criterion("eligibility and counterevidence", suite_passed, 20, "PROVEN/LIKELY/UNKNOWN/CONTRADICTED"),
        _criterion("contextual alternative competition", suite_passed, 20, "hard requirements precede ranking; Big-O cannot override semantics"),
        _criterion("catalog recipes and mappings", catalog_ok, 15, f"validated recipes for {catalog['entries']} entries"),
        _criterion("report and dedicated panel contract", suite_passed, 15, "report formats plus stable import/review schema"),
        _criterion("measured recommendation precision", empirical_ok, 10, f"recommendation precision={empirical['recommendation_precision']:.1%}"),
    ])
    global_score = round(0.40 * detection["score"] + 0.30 * correction["score"] + 0.30 * suggestions["score"], 1)
    empirical_gates = {
        "recognition_precision_gte_95": empirical["recognition_precision"] >= 0.95,
        "recognition_recall_gte_90": empirical["recognition_recall"] >= 0.90,
        "recommendation_precision_gte_95": empirical["recommendation_precision"] >= 0.95,
        "cross_language_consistency_100": cross_language,
        "safe_semantic_preservation_100": suite_passed,
        "catalog_contract_coverage_100": catalog_ok,
    }
    return {
        "schema_version": "1.0.0", "weights": {"detection": 0.40, "correction": 0.30, "suggestions": 0.30},
        "detection": detection, "correction": correction, "suggestions": suggestions,
        "functional_global_index": global_score,
        "target_met": global_score == 100.0 and all(empirical_gates.values()),
        "suite_passed": suite_passed, "empirical_gates": empirical_gates,
        "empirical_metrics": {key: empirical[key] for key in ("recognition_precision", "recognition_recall", "recommendation_precision", "production_thresholds_met")},
        "catalog_metrics": catalog,
        "limitations": [
            "The algorithm universe is open; 100% means the finite Atlas 6-24 specification and release gates, not every future algorithm.",
            "Parser precision is measured on the labelled executable corpus; catalog state-machine coverage is reported separately.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    suite_passed = False
    if not args.skip_tests:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/algorithms", "-p", "test*.py"],
            cwd=REPO_ROOT, check=False,
        )
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


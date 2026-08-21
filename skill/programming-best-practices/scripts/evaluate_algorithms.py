#!/usr/bin/env python3
"""Evaluate core recognition and recommendation precision on labelled cases."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from algorithms import analyze_repository

ACTIONABLE = {"suboptimal", "incorrect", "refactor-opportunity", "security-risk"}


def evaluate(cases_path: Path) -> dict:
    document = json.loads(cases_path.read_text(encoding="utf-8"))
    tp = fp = fn = recommendation_correct = recommendation_total = 0
    case_results = []
    for case in document.get("cases", []):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = case.get("files") or {"case.py": case["source"]}
            for filename, source in files.items():
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        actionable = {item["rule_id"]: item for item in artifact["algorithms"] if item["status"] in ACTIONABLE}
        expected = case.get("expected", {})
        actual_rules, expected_rules = set(actionable), set(expected)
        tp += len(actual_rules & expected_rules)
        fp += len(actual_rules - expected_rules)
        fn += len(expected_rules - actual_rules)
        for rule_id, level in expected.items():
            recommendation_total += 1
            item = actionable.get(rule_id)
            if item and (item.get("recommendation") or {}).get("correction_level") == level:
                recommendation_correct += 1
        case_results.append({
            "id": case["id"], "expected": sorted(expected_rules), "actual": sorted(actual_rules),
            "false_positive": sorted(actual_rules - expected_rules), "missed": sorted(expected_rules - actual_rules),
        })
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    recommendation_precision = recommendation_correct / recommendation_total if recommendation_total else 1.0
    return {
        "schema_version": "1.0.0", "scope": document.get("scope"),
        "counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
        "recognition_precision": round(precision, 4), "recognition_recall": round(recall, 4),
        "recommendation_precision": round(recommendation_precision, 4),
        "production_thresholds_met": precision >= 0.95 and recall >= 0.90 and recommendation_precision >= 0.95,
        "cases": case_results,
        "limitation": "Metrics cover the labelled executable corpus named by scope; declarative catalog contracts are reported separately.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.cases)
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["production_thresholds_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

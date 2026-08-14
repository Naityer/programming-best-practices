#!/usr/bin/env python3
"""Validate `stats.json` (from `build_stats.py`) without third-party packages.

Same hand-rolled discipline as `validate_report.py`: every field the schema
allows is checked, every field it doesn't know is rejected, so a malformed or
hand-edited `stats.json` fails loudly instead of reaching a downstream
dashboard silently wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REVIEW_STATUSES = {"confirmed", "dismissed", "unreviewed"}
TREND_DIRECTIONS = {"improving", "worsening", "not_distinguishable_from_noise", "insufficient_data", "unknown_polarity"}
SEVERITIES = {"blocker", "high", "medium", "low"}


def _required(obj: dict[str, Any], fields: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(fields - obj.keys()):
        errors.append(f"{path}.{field}: missing required field")


def _unknown(obj: dict[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(obj.keys() - allowed):
        errors.append(f"{path}.{field}: unexpected field")


def _enum(value: Any, values: set[str], path: str, errors: list[str]) -> None:
    if value not in values:
        errors.append(f"{path}: expected one of {sorted(values)}, got {value!r}")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: expected non-empty string")


def _rate_fields(obj: dict[str, Any], path: str, errors: list[str], *, extra: set[str] = frozenset()) -> None:
    fields = {"reviewed", "confirmed", "dismissed", "confirmation_rate", "false_positive_rate",
              "confirmation_rate_ci95", "false_positive_rate_ci95", "sample_size_warning"} | extra
    if not isinstance(obj, dict):
        errors.append(f"{path}: expected object")
        return
    _required(obj, {"reviewed", "confirmed", "dismissed", "sample_size_warning"}, path, errors)
    _unknown(obj, fields, path, errors)
    for key in ("reviewed", "confirmed", "dismissed"):
        value = obj.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{path}.{key}: expected non-negative integer")
    if not isinstance(obj.get("sample_size_warning"), bool):
        errors.append(f"{path}.sample_size_warning: expected boolean")
    for key in ("confirmation_rate", "false_positive_rate"):
        value = obj.get(key)
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"{path}.{key}: expected number or null")
    for key in ("confirmation_rate_ci95", "false_positive_rate_ci95"):
        value = obj.get(key)
        if value is not None:
            if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, (int, float)) for v in value):
                errors.append(f"{path}.{key}: expected a [low, high] pair or null")


def _series_fields(obj: dict[str, Any], path: str, errors: list[str]) -> None:
    fields = {"series", "n", "mean", "stdev", "min", "max", "slope_per_day", "slope_standard_error", "direction"}
    if not isinstance(obj, dict):
        errors.append(f"{path}: expected object")
        return
    _required(obj, {"series", "n", "direction"}, path, errors)
    _unknown(obj, fields, path, errors)
    if not isinstance(obj.get("n"), int) or isinstance(obj.get("n"), bool) or obj.get("n", 0) < 0:
        errors.append(f"{path}.n: expected non-negative integer")
    _enum(obj.get("direction"), TREND_DIRECTIONS, f"{path}.direction", errors)
    series = obj.get("series")
    if not isinstance(series, list):
        errors.append(f"{path}.series: expected array")
    else:
        for index, point in enumerate(series):
            point_path = f"{path}.series[{index}]"
            if not isinstance(point, dict):
                errors.append(f"{point_path}: expected object")
                continue
            _unknown(point, {"generated_at", "value"}, point_path, errors)
            if "value" in point and not isinstance(point["value"], (int, float)):
                errors.append(f"{point_path}.value: expected number")


def validate_stats(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected object"]

    top_fields = {
        "schema_version", "generated_at", "repository", "root", "source_runs_considered",
        "source_runs", "current_run", "findings_timeline", "by_tool", "by_category",
        "review", "trends", "anomalies", "limitations",
    }
    _required(data, top_fields, "$", errors)
    _unknown(data, top_fields, "$", errors)
    if data.get("schema_version") != "1.0.0":
        errors.append("$.schema_version: expected '1.0.0'")
    _nonempty_string(data.get("repository"), "$.repository", errors)
    _nonempty_string(data.get("root"), "$.root", errors)
    if not isinstance(data.get("source_runs_considered"), int) or isinstance(data.get("source_runs_considered"), bool):
        errors.append("$.source_runs_considered: expected integer")

    source_runs = data.get("source_runs")
    if not isinstance(source_runs, list):
        errors.append("$.source_runs: expected array")
    else:
        for index, run in enumerate(source_runs):
            path = f"$.source_runs[{index}]"
            if not isinstance(run, dict):
                errors.append(f"{path}: expected object")
                continue
            _unknown(run, {"dir", "generated_at", "profile", "outcome", "has_ledger"}, path, errors)
            if "has_ledger" in run and not isinstance(run["has_ledger"], bool):
                errors.append(f"{path}.has_ledger: expected boolean")

    current_run = data.get("current_run")
    if not isinstance(current_run, dict):
        errors.append("$.current_run: expected object")
    else:
        _unknown(current_run, {"run_dir", "generated_at", "profile", "scope", "outcome", "finding_counts", "dimensions_snapshot"}, "$.current_run", errors)

    timeline = data.get("findings_timeline")
    if not isinstance(timeline, list):
        errors.append("$.findings_timeline: expected array")
    else:
        for index, entry in enumerate(timeline):
            path = f"$.findings_timeline[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{path}: expected object")
                continue
            _unknown(entry, {
                "generated_at", "run_dir", "tool", "rule_id", "category", "severity",
                "confidence", "file", "line", "review_status", "sample_evidence",
            }, path, errors)
            if "review_status" in entry:
                _enum(entry["review_status"], REVIEW_STATUSES, f"{path}.review_status", errors)
            if "severity" in entry and entry["severity"] is not None:
                _enum(entry["severity"], SEVERITIES, f"{path}.severity", errors)

    by_tool = data.get("by_tool")
    if not isinstance(by_tool, dict):
        errors.append("$.by_tool: expected object")
    else:
        for name, entry in by_tool.items():
            path = f"$.by_tool[{name!r}]"
            if not isinstance(entry, dict):
                errors.append(f"{path}: expected object")
                continue
            _unknown(entry, {
                "runs_seen", "status_histogram", "measurement_domain", "measurement_domain_source",
                "category", "gate", "avg_duration_ms", "duration_ms_stddev", "reproducibility",
                "coverage_of_codebase", "findings_total", "review",
            }, path, errors)
            if "review" in entry:
                _rate_fields(entry["review"], f"{path}.review", errors)

    review = data.get("review")
    if not isinstance(review, dict):
        errors.append("$.review: expected object")
    else:
        _required(review, {"runs_with_ledger", "runs_without_ledger", "decisions_considered", "tool_findings", "agent_llm_only_findings", "unreviewed_findings", "note"}, "$.review", errors)
        _unknown(review, {"runs_with_ledger", "runs_without_ledger", "decisions_considered", "tool_findings", "agent_llm_only_findings", "unreviewed_findings", "note"}, "$.review", errors)
        if "tool_findings" in review:
            _rate_fields(review["tool_findings"], "$.review.tool_findings", errors, extra={"by_tool"})
        if "agent_llm_only_findings" in review:
            _rate_fields(review["agent_llm_only_findings"], "$.review.agent_llm_only_findings", errors)

    trends = data.get("trends")
    if not isinstance(trends, dict):
        errors.append("$.trends: expected object")
    else:
        _unknown(trends, {"finding_counts", "dimensions"}, "$.trends", errors)
        for group in ("finding_counts", "dimensions"):
            if group not in trends:
                continue
            group_obj = trends[group]
            if not isinstance(group_obj, dict):
                errors.append(f"$.trends.{group}: expected object")
                continue
            for metric, series in group_obj.items():
                _series_fields(series, f"$.trends.{group}[{metric!r}]", errors)

    anomalies = data.get("anomalies")
    if not isinstance(anomalies, dict):
        errors.append("$.anomalies: expected object")
    else:
        _unknown(anomalies, {"location_conflicts", "stale_baselines", "decision_reversals", "findings_on_removed_code"}, "$.anomalies", errors)
        for key in ("location_conflicts", "stale_baselines", "decision_reversals", "findings_on_removed_code"):
            if key in anomalies and not isinstance(anomalies[key], list):
                errors.append(f"$.anomalies.{key}: expected array")

    limitations = data.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        errors.append("$.limitations: expected array of strings")

    return errors


def load_and_validate(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"$: cannot read input: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
    errors = validate_stats(data)
    return data if isinstance(data, dict) else None, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stats", type=Path)
    args = parser.parse_args()
    _, errors = load_and_validate(args.stats)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the canonical quality-audit JSON without third-party packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SEVERITIES = {"blocker", "high", "medium", "low"}
CONFIDENCES = {"high", "medium", "low"}
PROFILES = {"fast", "standard", "deep"}
MODES = {"audit", "fix"}
OUTCOMES = {"pass", "fail", "incomplete", "informational"}
TOOL_STATUSES = {"passed", "findings", "failed", "timed_out", "skipped", "unavailable"}
SOURCE_TYPES = {"tool", "specification", "property", "llm"}
ORACLE_TYPES = {"regression", "specification", "property"}


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


def validate_report(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected object"]

    top_fields = {"schema_version", "audit", "summary", "tools", "findings", "limitations"}
    _required(data, top_fields, "$", errors)
    _unknown(data, top_fields, "$", errors)
    if data.get("schema_version") != "1.0.0":
        errors.append("$.schema_version: expected '1.0.0'")

    audit = data.get("audit")
    if not isinstance(audit, dict):
        errors.append("$.audit: expected object")
    else:
        audit_fields = {"repository", "profile", "scope", "mode", "generated_at", "outcome"}
        _required(audit, audit_fields, "$.audit", errors)
        _unknown(audit, audit_fields, "$.audit", errors)
        _enum(audit.get("profile"), PROFILES, "$.audit.profile", errors)
        _enum(audit.get("mode"), MODES, "$.audit.mode", errors)
        _enum(audit.get("outcome"), OUTCOMES, "$.audit.outcome", errors)
        for key in ("repository", "scope", "generated_at"):
            _nonempty_string(audit.get(key), f"$.audit.{key}", errors)

    summary = data.get("summary")
    if not isinstance(summary, dict):
        errors.append("$.summary: expected object")
    else:
        _required(summary, {"finding_counts"}, "$.summary", errors)
        _unknown(summary, {"finding_counts", "dimensions"}, "$.summary", errors)
        if "dimensions" in summary and not isinstance(summary["dimensions"], dict):
            errors.append("$.summary.dimensions: expected object")
        counts = summary.get("finding_counts")
        if not isinstance(counts, dict):
            errors.append("$.summary.finding_counts: expected object")
        else:
            _required(counts, SEVERITIES, "$.summary.finding_counts", errors)
            _unknown(counts, SEVERITIES, "$.summary.finding_counts", errors)
            for severity in SEVERITIES:
                value = counts.get(severity)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    errors.append(f"$.summary.finding_counts.{severity}: expected non-negative integer")

    tools = data.get("tools")
    if not isinstance(tools, list):
        errors.append("$.tools: expected array")
    else:
        tool_fields = {"name", "status", "command", "version", "exit_code", "duration_ms", "report", "reason", "gate", "effective_scope"}
        for index, tool in enumerate(tools):
            path = f"$.tools[{index}]"
            if not isinstance(tool, dict):
                errors.append(f"{path}: expected object")
                continue
            _required(tool, {"name", "status"}, path, errors)
            _unknown(tool, tool_fields, path, errors)
            _nonempty_string(tool.get("name"), f"{path}.name", errors)
            _enum(tool.get("status"), TOOL_STATUSES, f"{path}.status", errors)
            if "gate" in tool and not isinstance(tool["gate"], bool):
                errors.append(f"{path}.gate: expected boolean")
            if "effective_scope" in tool:
                _nonempty_string(tool["effective_scope"], f"{path}.effective_scope", errors)
            for key in ("command", "version", "report", "reason"):
                if key in tool and not isinstance(tool[key], str):
                    errors.append(f"{path}.{key}: expected string")
            if "exit_code" in tool and tool["exit_code"] is not None:
                if not isinstance(tool["exit_code"], int) or isinstance(tool["exit_code"], bool):
                    errors.append(f"{path}.exit_code: expected integer or null")
            if "duration_ms" in tool:
                value = tool["duration_ms"]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    errors.append(f"{path}.duration_ms: expected non-negative integer")

    findings = data.get("findings")
    if not isinstance(findings, list):
        errors.append("$.findings: expected array")
    else:
        seen_ids: set[str] = set()
        required = {
            "id", "fingerprint", "rule_id", "title", "category", "severity",
            "confidence", "locations", "evidence", "impact", "recommendation",
        }
        for index, finding in enumerate(findings):
            path = f"$.findings[{index}]"
            if not isinstance(finding, dict):
                errors.append(f"{path}: expected object")
                continue
            _required(finding, required, path, errors)
            _unknown(finding, required | {"oracle"}, path, errors)
            for key in ("id", "fingerprint", "rule_id", "title", "category", "impact", "recommendation"):
                _nonempty_string(finding.get(key), f"{path}.{key}", errors)
            finding_id = finding.get("id")
            if isinstance(finding_id, str):
                if finding_id in seen_ids:
                    errors.append(f"{path}.id: duplicate id {finding_id!r}")
                seen_ids.add(finding_id)
            _enum(finding.get("severity"), SEVERITIES, f"{path}.severity", errors)
            _enum(finding.get("confidence"), CONFIDENCES, f"{path}.confidence", errors)

            locations = finding.get("locations")
            if not isinstance(locations, list) or not locations:
                errors.append(f"{path}.locations: expected non-empty array")
            else:
                for loc_index, location in enumerate(locations):
                    loc_path = f"{path}.locations[{loc_index}]"
                    if not isinstance(location, dict):
                        errors.append(f"{loc_path}: expected object")
                        continue
                    _unknown(location, {"file", "line", "column"}, loc_path, errors)
                    _nonempty_string(location.get("file"), f"{loc_path}.file", errors)
                    for key in ("line", "column"):
                        if key in location:
                            value = location[key]
                            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                                errors.append(f"{loc_path}.{key}: expected positive integer")

            evidence = finding.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{path}.evidence: expected non-empty array")
            else:
                evidence_fields = {"source_type", "source", "message", "metric", "value"}
                for ev_index, item in enumerate(evidence):
                    ev_path = f"{path}.evidence[{ev_index}]"
                    if not isinstance(item, dict):
                        errors.append(f"{ev_path}: expected object")
                        continue
                    _required(item, {"source_type", "source", "message"}, ev_path, errors)
                    _unknown(item, evidence_fields, ev_path, errors)
                    _enum(item.get("source_type"), SOURCE_TYPES, f"{ev_path}.source_type", errors)
                    for key in ("source", "message"):
                        _nonempty_string(item.get(key), f"{ev_path}.{key}", errors)
                    if "metric" in item and not isinstance(item["metric"], str):
                        errors.append(f"{ev_path}.metric: expected string")

            oracle = finding.get("oracle")
            if oracle is not None:
                if not isinstance(oracle, dict):
                    errors.append(f"{path}.oracle: expected object")
                else:
                    _required(oracle, {"type"}, f"{path}.oracle", errors)
                    _unknown(oracle, {"type", "source", "rule"}, f"{path}.oracle", errors)
                    _enum(oracle.get("type"), ORACLE_TYPES, f"{path}.oracle.type", errors)
                    if "source" in oracle and not isinstance(oracle["source"], str):
                        errors.append(f"{path}.oracle.source: expected string")
                    if "rule" in oracle and not isinstance(oracle["rule"], str):
                        errors.append(f"{path}.oracle.rule: expected string")
                    if oracle.get("type") == "specification" and not oracle.get("source"):
                        errors.append(f"{path}.oracle.source: required for specification oracle")
                    if oracle.get("type") == "property" and not oracle.get("rule"):
                        errors.append(f"{path}.oracle.rule: required for property oracle")

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
    errors = validate_report(data)
    return data if isinstance(data, dict) else None, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    _, errors = load_and_validate(args.report)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


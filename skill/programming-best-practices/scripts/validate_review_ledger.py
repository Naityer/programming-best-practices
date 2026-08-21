#!/usr/bin/env python3
"""Validate review-ledger.json without third-party packages — same style as
validate_report.py, against references/review-ledger.schema.json.

Nothing in the pipeline validated this artifact before: build_report.py
writes it straight from its own construction, and build_stats.py reads it
back on trust. This closes that gap — a guardrail per the "puntos de
verificación" requirement, not just correctness by construction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ACTIONS = {"confirm", "dismiss"}
EVIDENCE_SOURCE_TYPES = {"tool", "specification", "property", "llm"}
REVIEWER_PATTERN = re.compile(r"^(skill|agent|human)(:[A-Za-z0-9._-]+)?$")


def _required(obj: dict[str, Any], fields: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(fields - obj.keys()):
        errors.append(f"{path}.{field}: missing required field")


def _unknown(obj: dict[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
    for field in sorted(obj.keys() - allowed):
        errors.append(f"{path}.{field}: unexpected field")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path}: expected non-empty string")


def validate_review_ledger(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$: expected object"]

    top_fields = {"schema_version", "repository", "generated_at", "decisions"}
    _required(data, top_fields, "$", errors)
    _unknown(data, top_fields, "$", errors)
    if data.get("schema_version") != "1.0.0":
        errors.append("$.schema_version: expected '1.0.0'")
    _nonempty_string(data.get("repository"), "$.repository", errors)

    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        errors.append("$.decisions: expected array")
        return errors

    decision_fields = {"decision_id", "action", "reason", "reviewed_at", "reviewer", "overrides", "unmatched", "matched"}
    required = {"decision_id", "action", "reason", "matched", "unmatched"}
    seen_ids: set[str] = set()
    for index, decision in enumerate(decisions):
        path = f"$.decisions[{index}]"
        if not isinstance(decision, dict):
            errors.append(f"{path}: expected object")
            continue
        _required(decision, required, path, errors)
        _unknown(decision, decision_fields, path, errors)
        decision_id = decision.get("decision_id")
        _nonempty_string(decision_id, f"{path}.decision_id", errors)
        if isinstance(decision_id, str):
            if decision_id in seen_ids:
                errors.append(f"{path}.decision_id: duplicate id {decision_id!r}")
            seen_ids.add(decision_id)
        if decision.get("action") not in ACTIONS:
            errors.append(f"{path}.action: expected one of {sorted(ACTIONS)}, got {decision.get('action')!r}")
        if not isinstance(decision.get("reason"), str):
            errors.append(f"{path}.reason: expected string")
        if not isinstance(decision.get("unmatched"), bool):
            errors.append(f"{path}.unmatched: expected boolean")
        if "reviewed_at" in decision and decision["reviewed_at"] is not None and not isinstance(decision["reviewed_at"], str):
            errors.append(f"{path}.reviewed_at: expected string or null")
        if "overrides" in decision and decision["overrides"] is not None and not isinstance(decision["overrides"], dict):
            errors.append(f"{path}.overrides: expected object or null")

        reviewer = decision.get("reviewer")
        if reviewer is not None:
            if not isinstance(reviewer, str) or not REVIEWER_PATTERN.match(reviewer):
                errors.append(
                    f"{path}.reviewer: expected 'skill', 'agent', or 'human', optionally followed by "
                    f"':<identifier>' — got {reviewer!r}"
                )

        matched = decision.get("matched")
        if not isinstance(matched, list):
            errors.append(f"{path}.matched: expected array")
        else:
            matched_fields = {
                "fingerprint", "rule_id", "category", "severity", "confidence",
                "locations", "evidence_source_types", "primary_source", "primary_message",
            }
            for m_index, snapshot in enumerate(matched):
                m_path = f"{path}.matched[{m_index}]"
                if not isinstance(snapshot, dict):
                    errors.append(f"{m_path}: expected object")
                    continue
                _unknown(snapshot, matched_fields, m_path, errors)
                if "evidence_source_types" in snapshot:
                    types = snapshot["evidence_source_types"]
                    if not isinstance(types, list) or any(t not in EVIDENCE_SOURCE_TYPES for t in types):
                        errors.append(f"{m_path}.evidence_source_types: expected array of {sorted(EVIDENCE_SOURCE_TYPES)}")

    return errors


def load_and_validate(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"$: cannot read input: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
    errors = validate_review_ledger(data)
    return data if isinstance(data, dict) else None, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    _, errors = load_and_validate(args.ledger)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

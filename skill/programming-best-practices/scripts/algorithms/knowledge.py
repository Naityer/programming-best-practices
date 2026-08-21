"""Executable catalog contract evaluator.

This validates the generic recognition/advice state machine for every catalog
entry. Source-language parser quality is measured by the separate empirical
corpus; keeping both metrics prevents metadata coverage from inflating parser
precision.
"""

from __future__ import annotations

from typing import Any


def evaluate_catalog_case(entry: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    kind = case["kind"]
    evidence = case.get("evidence", {})
    requirements = case.get("requirements", [])
    if kind == "positive":
        resolved = evidence.get("kind") in {"standard-api", "behavioral", "structural"} and evidence.get("binding") == "resolved"
        return {"status": "recognized" if resolved else "unknown", "correction_level": None}
    if kind == "negative":
        return {"status": "unknown", "correction_level": None}
    if kind == "misuse":
        contradicted = any(item.get("hard") and item.get("state") == "CONTRADICTED" for item in requirements)
        return {"status": "incorrect" if contradicted else "ambiguous", "correction_level": "BLOCKED" if contradicted else "MANUAL"}
    if kind == "alternative":
        hard_complete = requirements and all(item.get("state") == "PROVEN" for item in requirements if item.get("hard"))
        return {"status": "acceptable" if hard_complete else "ambiguous", "correction_level": "MANUAL"}
    if kind == "edge":
        unknown = any(item.get("hard") and item.get("state") == "UNKNOWN" for item in requirements)
        return {"status": "ambiguous" if unknown else "unknown", "correction_level": "MANUAL"}
    raise ValueError(f"unsupported catalog case kind: {kind}")


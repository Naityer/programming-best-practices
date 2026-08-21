"""Stable output builders for algorithm occurrences."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def occurrence_id(rule_id: str, location: dict[str, Any], signature: dict[str, Any]) -> str:
    identity = {
        "rule_id": rule_id,
        "file": str(location.get("file", "")).replace("\\", "/"),
        "line": location.get("line"),
        "qualified_name": location.get("qualified_name"),
        "problem": signature.get("problem"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return f"ALG-{digest.upper()}"


def relative_location(path: Path, root: Path, line: int, qualified_name: str | None = None) -> dict[str, Any]:
    try:
        file_name = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        file_name = path.as_posix()
    result: dict[str, Any] = {"file": file_name, "line": max(1, line)}
    if qualified_name:
        result["qualified_name"] = qualified_name
    return result


def make_occurrence(
    *, algorithm_id: str, rule_id: str, family: str, status: str,
    confidence: str, location: dict[str, Any], problem: str,
    current_approach: str, current_time: str, expected_time: str | None,
    evidence: list[dict[str, Any]], requirements: list[dict[str, Any]],
    alternatives: list[dict[str, Any]], recommendation: dict[str, Any] | None,
    contradictions: list[dict[str, Any]] | None = None, category: str = "performance",
) -> dict[str, Any]:
    signature = {"problem": problem, "properties": {}, "operations": []}
    result = {
        "algorithm_id": algorithm_id,
        "rule_id": rule_id,
        "family": family,
        "status": status,
        "confidence": confidence,
        "primary_location": location,
        "problem_signature": signature,
        "current_approach": current_approach,
        "complexity": {
            "current": {"time": current_time, "space": "unknown", "kind": "worst"},
            "expected": ({"time": expected_time, "space": "unknown", "kind": "worst"} if expected_time else None),
            "basis": "structural static analysis",
        },
        "evidence": evidence,
        "contradictions": contradictions or [],
        "requirements": requirements,
        "alternatives": alternatives,
        "recommendation": recommendation,
        "category": category,
    }
    result["id"] = occurrence_id(rule_id, location, signature)
    return result

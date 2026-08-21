"""Optional correlation with user-supplied profiling and security evidence."""

from __future__ import annotations

from typing import Any


def _matches(location: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if str(location.get("file", "")).replace("\\", "/") != str(evidence.get("file", "")).replace("\\", "/"):
        return False
    if evidence.get("qualified_name") and location.get("qualified_name") != evidence.get("qualified_name"):
        return False
    line = evidence.get("line")
    return line is None or int(location.get("line") or 0) == int(line)


def correlate(
    occurrences: list[dict[str, Any]],
    *,
    profiling: dict[str, Any] | None = None,
    security: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profiling_locations = (profiling or {}).get("locations", [])
    security_locations = (security or {}).get("locations", [])
    for item in occurrences:
        location = item.get("primary_location", {})
        for evidence in profiling_locations:
            if _matches(location, evidence):
                item.setdefault("evidence", []).append({
                    "kind": "profiling",
                    "description": f"Authorized profiling evidence marks this location hot (samples={evidence.get('samples', 'unknown')}).",
                })
                item.setdefault("problem_signature", {}).setdefault("properties", {})["profile_hot"] = bool(evidence.get("hot", True))
        for evidence in security_locations:
            if not _matches(location, evidence):
                continue
            controlled = evidence.get("externally_controlled") is True
            amplifiable = evidence.get("attack_amplifiable") is True
            item.setdefault("evidence", []).append({
                "kind": "security-correlation",
                "description": f"Authorized evidence: externally_controlled={controlled}, attack_amplifiable={amplifiable}.",
            })
            if controlled and amplifiable and item.get("status") in {"suboptimal", "refactor-opportunity"}:
                item["status"] = "security-risk"
                item["category"] = "security"
    return occurrences


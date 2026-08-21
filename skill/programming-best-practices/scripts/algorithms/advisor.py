"""Contextual alternative competition centered on hard requirements."""

from __future__ import annotations

from typing import Any

CONTEXT_KEYS = {
    "memory", "ordering", "duplicates", "equality", "mutability", "precision",
    "determinism", "stability", "exactness", "side_effects", "input_size",
}


def rank_alternatives(
    problem_signature: dict[str, Any],
    candidates: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate requirements before scoring; missing hard facts reject a candidate."""
    ranked: list[dict[str, Any]] = []
    signature_properties = problem_signature.get("properties", {})
    facts = {**signature_properties, **{key: value for key, value in context.items() if key in CONTEXT_KEYS}}
    for candidate in candidates:
        requirement_results = []
        eligible = True
        for name, expected in candidate.get("hard_requirements", {}).items():
            if name not in facts:
                state, reason = "UNKNOWN", "Required context is unavailable."
                eligible = False
            elif facts[name] != expected:
                state, reason = "CONTRADICTED", f"Observed {facts[name]!r}; candidate requires {expected!r}."
                eligible = False
            else:
                state, reason = "PROVEN", "Observed context satisfies the hard requirement."
            requirement_results.append({"name": name, "state": state, "hard": True, "reason": reason})

        input_size = context.get("input_size")
        simplicity = float(candidate.get("simplicity", 0))
        time_rank = float(candidate.get("time_rank", 0))
        memory_cost = float(candidate.get("memory_cost", 0))
        score = time_rank - memory_cost + simplicity
        if isinstance(input_size, int) and input_size <= 8:
            score += 3 * simplicity  # Atlas §102: adequate simple algorithms win for tiny inputs.
        if not eligible:
            score = float("-inf")
        ranked.append({
            "algorithm_id": candidate["algorithm_id"], "eligible": eligible,
            "requirements": requirement_results,
            "score": None if not eligible else round(score, 3),
            "reason": "eligible after hard requirements" if eligible else "rejected before ranking",
        })
    return sorted(ranked, key=lambda item: (item["eligible"], item["score"] or float("-inf")), reverse=True)


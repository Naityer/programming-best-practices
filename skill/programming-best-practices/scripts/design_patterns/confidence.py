"""Confidence tiers (spec §14), as invariants of code rather than guidance.

`compute_confidence` is deliberately the only place a tier gets decided. Every
detector calls it instead of computing its own score, so the caps below are
impossible to bypass from a detector:

  * a lexical frontend (Level C, spec §6) never returns "high" — it never
    returns anything but "low";
  * `supporting` evidence (names, comments, annotations) never appears in this
    function's inputs at all — see design_patterns_module/02-decisiones.md D1
    and evidence.py's docstring. It literally cannot move the tier because it
    is never counted here.
  * a contradiction present forces "low" — the engine is responsible for
    turning that into an `ambiguous` status, not for silently keeping the
    higher-scoring guess (spec §10, §12).

This corte collects no `behavioral` evidence (see 02-decisiones.md D1), so the
practical ceiling for a structural-only detection is "medium": all HARD
invariants hold, against resolved symbols, with zero contradictions. That is
strictly more conservative than spec §14's own MEDIUM (which only requires
>=1 BEHAVIORAL) and is the documented ceiling for this delivery.
"""

from __future__ import annotations

from typing import Literal

from .evidence import Evidence

Confidence = Literal["high", "medium", "low"]
FrontendLevel = Literal["A", "B", "C"]


def compute_confidence(
    *,
    all_hard_satisfied: bool,
    evidence: list[Evidence],
    frontend_level: FrontendLevel,
    symbols_resolved: bool = True,
) -> Confidence:
    if frontend_level == "C":
        return "low"
    if not all_hard_satisfied or not symbols_resolved:
        return "low"
    behavioral_count = sum(1 for item in evidence if item.kind == "behavioral")
    contradiction_count = sum(1 for item in evidence if item.kind == "contradiction")
    if contradiction_count:
        return "low"
    if behavioral_count >= 2:
        return "high"
    return "medium"

"""Pattern Engine (spec §3): ties catalog + IR + detectors + confidence into
the list of `PatternResult` that becomes design-patterns.json.

The one thing this module exists to guarantee: when two catalog-declared
`conflicts_with` patterns both fire on the SAME anchor entity (Adapter vs
Decorator vs Proxy on the same wrapper class; Strategy vs State on the same
context), the engine never picks the higher-scoring guess. It emits one
`ambiguous` result naming every candidate (spec §10, §12) — see
design-patterns-module/02-decisiones.md D1 for why that is this corte's
deliberate ceiling for the pattern trios spec §12 asks to be tested.

Detectors return `(anchor_entity_id, PatternResult)` pairs rather than bare
results specifically so the engine can group by anchor without detectors
having to agree on any shared "primary role" naming convention.
"""

from __future__ import annotations

from typing import Callable

from .catalog import Catalog
from .ir import CodeGraph
from .model import Contradiction, PatternResult

DetectorResult = tuple[str, PatternResult]
Detector = Callable[[CodeGraph], list[DetectorResult]]


def _conflicts(catalog: Catalog, a: str, b: str) -> bool:
    spec_a = catalog.get(a)
    spec_b = catalog.get(b)
    return bool((spec_a and b in spec_a.conflicts_with) or (spec_b and a in spec_b.conflicts_with))


def _cluster_by_conflict(results: list[PatternResult], catalog: Catalog) -> list[list[PatternResult]]:
    """Union-find over `conflicts_with`: patterns that don't conflict with
    anything at this anchor stay independent even if others here do."""
    parent = list(range(len(results)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            if _conflicts(catalog, results[i].pattern_id, results[j].pattern_id):
                union(i, j)

    groups: dict[int, list[PatternResult]] = {}
    for index, result in enumerate(results):
        groups.setdefault(find(index), []).append(result)
    return list(groups.values())


def _resolve_cluster(cluster: list[PatternResult]) -> PatternResult:
    if len(cluster) == 1:
        return cluster[0]
    primary = min(cluster, key=lambda r: r.pattern_id)  # deterministic pick for the anchor's evidence/location
    others = [r for r in cluster if r is not primary]
    contradictions = [
        Contradiction(
            pattern_id=other.pattern_id,
            reason=(
                f"{other.pattern_id} explains the same structure as {primary.pattern_id} "
                "and this corte collects no behavioral evidence to tell them apart (spec §12)"
            ),
        )
        for other in others
    ]
    return PatternResult(
        pattern_id=primary.pattern_id,
        status="ambiguous",
        confidence="low",
        primary_location=primary.primary_location,
        roles=primary.roles,
        evidence=primary.evidence,
        contradictions=contradictions,
    )


def roles_are_bound(result: PatternResult) -> bool:
    """Guardrail: every role a detector emits must point at a real, resolved
    IR entity — never an empty or missing value. A pattern that fails this
    is invalidated (dropped, never written to design-patterns.json), not
    patched up or emitted half-formed. This is a verification checkpoint on
    top of `_shared.build_result()` always building roles from real `Entity`
    objects — it exists so a future detector bug that manages to produce an
    unbound role cannot reach the report silently.
    """
    return bool(result.roles) and all(isinstance(value, str) and value for value in result.roles.values())


def dropped_role_limitation(result: PatternResult) -> str:
    location = result.primary_location
    return (
        f"{result.pattern_id} at {location.file}:{location.line} was dropped: "
        "at least one role had no entity bound to it (role-binding guardrail)."
    )


def run_engine(
    graph: CodeGraph, catalog: Catalog, detectors: dict[str, Detector],
) -> tuple[list[PatternResult], list[str]]:
    by_anchor: dict[str, list[PatternResult]] = {}
    for pattern_id, detector in detectors.items():
        if catalog.get(pattern_id) is None:
            raise ValueError(f"detector registered for unknown catalog pattern: {pattern_id!r}")
        for anchor_id, result in detector(graph):
            by_anchor.setdefault(anchor_id, []).append(result)

    resolved: list[PatternResult] = []
    limitations: list[str] = []
    for results in by_anchor.values():
        for cluster in _cluster_by_conflict(results, catalog):
            candidate = _resolve_cluster(cluster)
            if not roles_are_bound(candidate):
                limitations.append(dropped_role_limitation(candidate))
                continue
            resolved.append(candidate)

    resolved.sort(key=lambda r: (r.primary_location.file, r.primary_location.line, r.pattern_id))
    return resolved, limitations

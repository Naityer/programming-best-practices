"""Additional opportunities supported directly by the language-neutral IR."""
from __future__ import annotations

from itertools import combinations

from .detectors._shared import field_references
from .ir import CodeGraph
from .model import EvidenceEntry, Location, PatternResult

SUPPORTED_ADDITIONAL_OPPORTUNITIES = frozenset({"iterator", "mediator", "template_method"})


def _iterator(graph: CodeGraph) -> list[PatternResult]:
    for aggregate in graph.classes():
        by_field: dict[str, list] = {}
        for method in graph.members(aggregate.id, "method"):
            for relation in graph.outgoing(method.id, "ITERATES"):
                if relation.target_id:
                    by_field.setdefault(relation.target_id, []).append(method)
        for field_id, methods in by_field.items():
            unique = {method.id: method for method in methods}
            if len(unique) < 2:
                continue
            field = graph.entity(field_id)
            if field is None:
                continue
            sites = sorted(unique.values(), key=lambda entity: (entity.file, entity.line))
            roles = {"aggregate": aggregate.qualified_name, "collection": field.qualified_name}
            roles.update({f"traversal_site_{i}": site.qualified_name for i, site in enumerate(sites, 1)})
            return [PatternResult(
                "iterator", "refactor-opportunity", "medium", Location(sites[0].file, sites[0].line), roles,
                [EvidenceEntry("hard", f"{len(sites)} methods manually iterate the same collection field {field.name}")],
                refactoring={
                    "smell": "repeated manual traversal of the same collection", "candidate_pattern": "iterator",
                    "sites": [site.qualified_name for site in sites],
                    "steps": ["Extract traversal state and progression behind an iterator contract.", "Migrate duplicated loops while preserving iteration order and termination behavior."],
                    "verification": "Compare yielded elements and order against both original traversals.",
                },
            )]
    return []


def _mediator(graph: CodeGraph) -> list[PatternResult]:
    classes = list(graph.classes())
    neighbors = {entity.id: {ref.target.id for ref in field_references(graph, entity.id)} for entity in classes}
    for group in combinations(classes, 3):
        ids = {entity.id for entity in group}
        if not all(len(neighbors[entity.id] & (ids - {entity.id})) >= 2 for entity in group):
            continue
        roles = {f"component_{i}": entity.qualified_name for i, entity in enumerate(group, 1)}
        anchor = min(group, key=lambda entity: (entity.file, entity.line))
        return [PatternResult(
            "mediator", "refactor-opportunity", "medium", Location(anchor.file, anchor.line), roles,
            [EvidenceEntry("hard", "three concrete components each reference both of the others")],
            refactoring={
                "smell": "many-to-many direct dependencies between collaborating components", "candidate_pattern": "mediator",
                "sites": [entity.qualified_name for entity in group],
                "steps": ["Define the collaboration events each component actually needs.", "Move cross-component coordination into a mediator and make components depend on its contract."],
                "verification": "Run collaboration tests and assert components no longer hold peer-to-peer references.",
            },
        )]
    return []


def _template_method(graph: CodeGraph) -> list[PatternResult]:
    candidates = []
    for method in graph.by_kind.get("method", []):
        called = [graph.entity(relation.target_id) for relation in graph.outgoing(method.id, "CALLS") if relation.target_id]
        called = [target for target in called if target is not None]
        owner_ids = {relation.source_id for relation in graph.incoming(method.id, "CONTAINS")}
        if len(called) >= 2 and owner_ids:
            candidates.append((method, owner_ids, called))
    for left, right in combinations(candidates, 2):
        if left[1] & right[1]:
            continue
        shared_names = {target.name for target in left[2]} & {target.name for target in right[2]}
        if len(shared_names) < 2:
            continue
        sites = sorted((left[0], right[0]), key=lambda entity: (entity.file, entity.line))
        roles = {f"sequence_site_{i}": site.qualified_name for i, site in enumerate(sites, 1)}
        return [PatternResult(
            "template_method", "refactor-opportunity", "medium", Location(sites[0].file, sites[0].line), roles,
            [EvidenceEntry("hard", f"two classes repeat calls to {len(shared_names)} equally named steps; call ordering is unavailable in the IR")],
            refactoring={
                "smell": "repeated multi-step algorithm with shared step names", "candidate_pattern": "template_method",
                "sites": [site.qualified_name for site in sites],
                "steps": ["Extract the invariant algorithm skeleton into one template operation.", "Keep varying steps overridable and preserve their existing pre/postconditions."],
                "verification": "Run characterization tests for each original sequence before removing duplication.",
            },
        )]
    return []


def detect_additional_opportunities(graph: CodeGraph) -> list[PatternResult]:
    return _iterator(graph) + _mediator(graph) + _template_method(graph)

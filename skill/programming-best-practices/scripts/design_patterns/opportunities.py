"""Detect refactor opportunities only from repeated, observable evidence."""
from __future__ import annotations

from collections import defaultdict
from .additional_opportunities import detect_additional_opportunities

from .engine import dropped_role_limitation, roles_are_bound
from .ir import CodeGraph
from .model import EvidenceEntry, Location, PatternResult

_LIFECYCLE_LEXICON = {
    "pending", "running", "active", "inactive", "open", "closed", "start", "started",
    "stop", "stopped", "failed", "error", "completed", "done", "cancelled", "canceled",
    "idle", "paused", "ready", "waiting", "initializing", "terminated", "success",
}

SUPPORTED_OPPORTUNITIES = frozenset({"builder", "facade", "iterator", "mediator", "observer", "state", "strategy", "template_method"})


def _looks_like_lifecycle(values: set[str]) -> bool:
    normalized = {value.strip("'\"").lower() for value in values}
    return bool(normalized) and len(normalized & _LIFECYCLE_LEXICON) >= max(2, len(normalized) // 2)


def _owner_class_ids(graph: CodeGraph, entity_id: str) -> set[str]:
    owners: set[str] = set()
    for relation in graph.incoming(entity_id, "CONTAINS"):
        owner = graph.entity(relation.source_id)
        if owner and owner.kind in {"class", "struct", "trait"}:
            owners.add(owner.id)
    return owners


def _facade_opportunities(graph: CodeGraph) -> list[PatternResult]:
    sources = [entity for entity in graph.entities.values() if entity.kind in {"function", "method"}]
    subsystem_sets: dict[str, set[str]] = {}
    for source in sources:
        owners = {
            owner
            for relation in graph.outgoing(source.id, "CALLS") if relation.target_id
            for owner in _owner_class_ids(graph, relation.target_id)
        }
        if owners:
            subsystem_sets[source.id] = owners
    for index, left in enumerate(sources):
        for right in sources[index + 1:]:
            shared = subsystem_sets.get(left.id, set()) & subsystem_sets.get(right.id, set())
            if len(shared) < 2:
                continue
            sites = sorted((left, right), key=lambda entity: (entity.file, entity.line))
            roles = {f"orchestration_site_{i}": entity.qualified_name for i, entity in enumerate(sites, 1)}
            roles.update({f"subsystem_{i}": graph.entity(owner).qualified_name for i, owner in enumerate(sorted(shared), 1)})
            return [PatternResult(
                "facade", "refactor-opportunity", "medium", Location(sites[0].file, sites[0].line), roles,
                [EvidenceEntry("hard", f"two orchestration sites share calls into {len(shared)} subsystem classes; call ordering is not available in the normalized IR")],
                refactoring={
                    "smell": "repeated subsystem orchestration at multiple call sites", "candidate_pattern": "facade",
                    "sites": [entity.qualified_name for entity in sites],
                    "steps": ["Extract the shared subsystem calls behind one cohesive facade operation.", "Redirect both orchestration sites through the facade while preserving call results."],
                    "verification": "Run subsystem integration tests for both original call sites.",
                },
            )]
    return []


def _observer_opportunities(graph: CodeGraph) -> list[PatternResult]:
    for producer in graph.classes():
        consumer_ids = {
            owner
            for method in graph.members(producer.id, "method")
            for relation in graph.outgoing(method.id, "CALLS") if relation.target_id
            for owner in _owner_class_ids(graph, relation.target_id)
            if owner != producer.id
        }
        consumers = [graph.entity(owner) for owner in sorted(consumer_ids)]
        consumers = [consumer for consumer in consumers if consumer is not None]
        if len(consumers) < 2:
            continue
        roles = {"producer": producer.qualified_name}
        roles.update({f"concrete_consumer_{i}": consumer.qualified_name for i, consumer in enumerate(consumers, 1)})
        return [PatternResult(
            "observer", "refactor-opportunity", "medium", Location(producer.file, producer.line), roles,
            [EvidenceEntry("hard", f"producer directly calls {len(consumers)} concrete consumers; an Observer boundary may remove the concrete coupling")],
            refactoring={
                "smell": "producer calling multiple concrete consumers directly", "candidate_pattern": "observer",
                "steps": ["Define a minimal observer contract for the emitted event.", "Register consumers through the contract and fan out over a stable collection."],
                "verification": "Register two test observers and assert each receives exactly one notification.",
            },
        )]
    return []


def _builder_opportunities(graph: CodeGraph) -> list[PatternResult]:
    for product in graph.classes():
        constructors = graph.members(product.id, "constructor")
        if not constructors or len(constructors[0].parameters) < 4:
            continue
        site_ids = {relation.source_id for relation in graph.incoming(product.id, "INSTANTIATES")}
        sites = [graph.entity(site_id) for site_id in sorted(site_ids)]
        sites = [site for site in sites if site is not None]
        if len(sites) < 2:
            continue
        roles = {"product": product.qualified_name}
        roles.update({f"construction_site_{i}": site.qualified_name for i, site in enumerate(sites, 1)})
        return [PatternResult(
            "builder", "refactor-opportunity", "medium", Location(sites[0].file, sites[0].line), roles,
            [EvidenceEntry("hard", f"{product.name} has {len(constructors[0].parameters)} constructor parameters and is instantiated by {len(sites)} distinct classes")],
            refactoring={
                "smell": "repeated complex construction with many constructor parameters", "candidate_pattern": "builder",
                "sites": [site.qualified_name for site in sites],
                "steps": [f"Introduce explicit construction steps for {product.name}'s optional or grouped inputs.", "Migrate repeated call sites incrementally and retain constructor compatibility until tests pass."],
                "verification": "Compare products built by old and new paths for equivalent observable state.",
            },
        )]
    return []


def _conditional_opportunities(graph: CodeGraph) -> tuple[list[PatternResult], list[str]]:
    by_discriminator: dict[str, list] = defaultdict(list)
    for branch in graph.discriminator_branches:
        by_discriminator[branch.discriminator_param].append(branch)
    results: list[PatternResult] = []
    limitations: list[str] = []
    seen_groups: set[frozenset] = set()
    for branches in by_discriminator.values():
        for index, anchor_branch in enumerate(branches):
            group = [anchor_branch] + [
                other for other in branches[index + 1:]
                if len(set(anchor_branch.branch_values) & set(other.branch_values)) >= 2
            ]
            if len(group) < 2:
                continue
            functions = [entity for branch in group if (entity := graph.entity(branch.function_id)) is not None]
            key = frozenset(entity.id for entity in functions)
            if len(functions) < 2 or key in seen_groups:
                continue
            seen_groups.add(key)
            values = {value for branch in group for value in branch.branch_values}
            candidate = "state" if _looks_like_lifecycle(values) else "strategy"
            functions.sort(key=lambda entity: (entity.file, entity.line))
            steps = ["Extract one class per conditional branch behind a shared interface.", "Replace repeated branch selection with delegation through the interface."]
            if candidate == "state":
                steps = ["Extract one state class per lifecycle value behind a shared state interface.", "Move transitions and state-specific behavior into the corresponding state classes."]
            result = PatternResult(
                candidate, "refactor-opportunity", "medium", Location(functions[0].file, functions[0].line),
                {f"discriminator_site_{i}": entity.qualified_name for i, entity in enumerate(functions, 1)},
                [EvidenceEntry("hard", f"parameter {anchor_branch.discriminator_param!r} is compared against the same {len(values)} literal value(s) across {len(functions)} functions/methods")],
                refactoring={
                    "smell": "repeated conditional dispatch on the same discriminator", "candidate_pattern": candidate,
                    "sites": [entity.qualified_name for entity in functions], "steps": steps,
                    "verification": "Run characterization tests for every discriminator value before removing the conditionals.",
                },
            )
            if roles_are_bound(result):
                results.append(result)
            else:
                limitations.append(dropped_role_limitation(result))
    return results, limitations


def detect_opportunities(graph: CodeGraph) -> tuple[list[PatternResult], list[str]]:
    conditional, limitations = _conditional_opportunities(graph)
    return _facade_opportunities(graph) + _observer_opportunities(graph) + _builder_opportunities(graph) + detect_additional_opportunities(graph) + conditional, limitations

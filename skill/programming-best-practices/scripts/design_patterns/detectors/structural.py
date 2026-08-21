"""Structural family (spec §11): Adapter, Bridge, Composite, Decorator,
Facade, Flyweight, Proxy. HARD evidence only (this corte — see
design-patterns-module/02-decisiones.md D1).

Adapter/Decorator/Proxy share the exact same anchor shape in `_wrapper_
candidates`: a class that IMPLEMENTS an interface and DELEGATES_TO another
class from a method matching that interface. The only HARD-observable split
is whether the delegated method name differs (Adapter, translation) or
matches (Decorator/Proxy — genuinely indistinguishable without BEHAVIORAL
evidence, spec §12). Both still get emitted; `engine.py` merges same-anchor
`conflicts_with` results into a single `ambiguous` finding instead of
guessing, which is the corte's honest answer to spec §31.3.
"""

from __future__ import annotations

from ..ir import CodeGraph, Entity
from ..model import PatternResult
from ._shared import (
    build_result,
    cache_fields,
    collection_fields,
    delegations,
    field_references,
    implementors_of,
    implements,
    instantiated_by,
    iterates_and_calls,
    methods_of,
    subclasses_of,
)


def _wrapper_candidates(graph: CodeGraph):
    for wrapper in graph.classes():
        targets = implements(graph, wrapper.id)
        if not targets:
            continue
        for target in targets:
            target_methods = {m.name for m in methods_of(graph, target.id)}
            if not target_methods:
                continue
            for method in methods_of(graph, wrapper.id):
                if method.name not in target_methods:
                    continue
                for wrapped, delegated_method in delegations(graph, method.id):
                    if delegated_method:
                        yield wrapper, target, wrapped, method, delegated_method


def detect_adapter(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for wrapper, target, wrapped, method, delegated in _wrapper_candidates(graph):
        if delegated == method.name:
            continue
        results.append(build_result(
            pattern_id="adapter", status="detected", anchor=wrapper,
            roles={"target": target, "adapter": wrapper, "adaptee": wrapped},
            hard_evidence=[
                f"{wrapper.name} implements {target.name}",
                f"{wrapper.name} holds a reference to {wrapped.name}",
                f"{wrapper.name}.{method.name}() delegates to {wrapped.name}.{delegated}() "
                "(different method name — translation, not passthrough)",
            ],
            graph=graph,
        ))
    return results


def detect_decorator(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for wrapper, target, wrapped, method, delegated in _wrapper_candidates(graph):
        if delegated != method.name:
            continue
        results.append(build_result(
            pattern_id="decorator", status="detected", anchor=wrapper,
            roles={"component": target, "concrete_component": wrapped, "decorator": wrapper},
            hard_evidence=[
                f"{wrapper.name} implements {target.name}",
                f"{wrapper.name} holds a reference to {wrapped.name}",
                f"{wrapper.name}.{method.name}() delegates to {wrapped.name}.{delegated}() (same contract)",
            ],
            graph=graph,
        ))
    return results


def detect_proxy(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for wrapper, target, wrapped, method, delegated in _wrapper_candidates(graph):
        if delegated != method.name:
            continue
        results.append(build_result(
            pattern_id="proxy", status="detected", anchor=wrapper,
            roles={"subject": target, "real_subject": wrapped, "proxy": wrapper},
            hard_evidence=[
                f"{wrapper.name} implements {target.name}",
                f"{wrapper.name} holds a reference to {wrapped.name}",
                f"{wrapper.name}.{method.name}() delegates to {wrapped.name}.{delegated}() (same contract)",
            ],
            graph=graph,
        ))
    return results


def detect_facade(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for cls in graph.classes():
        refs = field_references(graph, cls.id)
        distinct: dict[str, Entity] = {fr.target.id: fr.target for fr in refs}
        if len(distinct) < 2:
            continue
        delegated_ids: set[str] = set()
        for method in methods_of(graph, cls.id):
            for target, _ in delegations(graph, method.id):
                delegated_ids.add(target.id)
        subsystems = [t for tid, t in distinct.items() if tid in delegated_ids]
        if len(subsystems) < 2:
            continue
        roles: dict[str, Entity] = {"facade": cls}
        for index, subsystem in enumerate(subsystems[:4], start=1):
            roles[f"subsystem_{index}"] = subsystem
        results.append(build_result(
            pattern_id="facade", status="detected", anchor=cls, roles=roles,
            hard_evidence=[
                f"{cls.name} holds references to {len(subsystems)} distinct subsystem components",
                f"{cls.name}'s methods delegate across all {len(subsystems)} of them",
            ],
            graph=graph,
        ))
    return results


def detect_bridge(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for abstraction in graph.classes():
        refined = subclasses_of(graph, abstraction.id)
        if not refined:
            continue
        for fr in field_references(graph, abstraction.id):
            implementor = fr.target
            if implementor.kind != "interface":
                continue
            concretes = implementors_of(graph, implementor.id)
            if len(concretes) < 2:
                continue
            results.append(build_result(
                pattern_id="bridge", status="detected", anchor=abstraction,
                roles={
                    "abstraction": abstraction, "implementor": implementor,
                    "refined_abstraction": refined[0], "concrete_implementor": concretes[0],
                },
                hard_evidence=[
                    f"{abstraction.name} has {len(refined)} subclass(es) (refined abstractions)",
                    f"{abstraction.name} holds a reference to {implementor.name}, an interface, by composition",
                    f"{implementor.name} has {len(concretes)} independent implementations",
                ],
                graph=graph,
            ))
    return results


def detect_composite(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for component in graph.by_kind.get("interface", []):
        implementors = implementors_of(graph, component.id)
        if len(implementors) < 2:
            continue
        component_method_names = {m.name for m in methods_of(graph, component.id)}
        if not component_method_names:
            continue
        for candidate in implementors:
            coll_field_names = {f.name for f in collection_fields(graph, candidate.id)}
            if not coll_field_names:
                continue
            fan_out = iterates_and_calls(graph, candidate.id)
            matches = [
                (method, field_name, called)
                for method, field_name, called in fan_out
                if field_name in coll_field_names and called in component_method_names
            ]
            if not matches:
                continue
            leaves = [i for i in implementors if i.id != candidate.id]
            if not leaves:
                continue
            _, _, called_method = matches[0]
            results.append(build_result(
                pattern_id="composite", status="detected", anchor=candidate,
                roles={"component": component, "composite": candidate, "leaf": leaves[0]},
                hard_evidence=[
                    f"{component.name} is implemented by {len(implementors)} classes",
                    f"{candidate.name} holds a homogeneous collection of {component.name}",
                    f"{candidate.name} iterates that collection and calls {called_method}() on each element, "
                    f"matching {component.name}'s own contract",
                ],
                graph=graph,
            ))
    return results


def detect_flyweight(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for factory in graph.classes():
        cached = cache_fields(graph, factory.id)
        if not cached:
            continue
        created = instantiated_by(graph, factory.id)
        if not created:
            continue
        flyweight_type, _ = created[0]
        contexts = [
            c for c in graph.classes()
            if c.id != factory.id and any(fr.target.id == flyweight_type.id for fr in field_references(graph, c.id))
        ]
        if not contexts:
            continue
        results.append(build_result(
            pattern_id="flyweight", status="detected", anchor=factory,
            roles={"flyweight_factory": factory, "flyweight": flyweight_type, "context": contexts[0]},
            hard_evidence=[
                f"{factory.name} caches instances via {cached[0]}",
                f"{factory.name} instantiates {flyweight_type.name}",
                f"{contexts[0].name} holds a shared reference to {flyweight_type.name} rather than owning its own copy",
            ],
            graph=graph,
        ))
    return results


DETECTORS = {
    "adapter": detect_adapter,
    "decorator": detect_decorator,
    "proxy": detect_proxy,
    "facade": detect_facade,
    "bridge": detect_bridge,
    "composite": detect_composite,
    "flyweight": detect_flyweight,
}

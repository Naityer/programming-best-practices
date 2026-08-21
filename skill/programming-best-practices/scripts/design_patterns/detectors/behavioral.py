"""Behavioral family (spec §11): Chain of Responsibility, Command, Iterator,
Mediator, Memento, Observer, State, Strategy, Template Method, Visitor. HARD
evidence only (this corte).

State vs Strategy (spec §12) is the one lookalike pair this corte CAN
separate without collecting BEHAVIORAL evidence: a `TRANSITIONS_TO` relation
(the field is reassigned to a different concrete implementation from inside
the class's own methods) is itself HARD/structural, not behavioral in the
spec §9 sense — it is an IR fact, not a traced runtime call sequence. So
`detect_state` requires it and `detect_strategy` requires its absence on the
same field; they are mutually exclusive by construction and never need the
engine's `ambiguous` merge. Update design-patterns-module/04-progreso.md's
§31.4 line if this changes.
"""

from __future__ import annotations

from ..ir import CodeGraph
from ..model import PatternResult
from ._shared import (
    build_result,
    collection_fields,
    delegations,
    field_references,
    implementors_of,
    instantiated_by,
    iterates_and_calls,
    methods_of,
    subclasses_of,
    transitions,
    visitor_delegations,
)


def detect_chain_of_responsibility(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for handler in graph.by_kind.get("interface", []):
        concretes = implementors_of(graph, handler.id)
        if not concretes:
            continue
        for concrete in concretes:
            # The "next" field must be typed as the HANDLER INTERFACE itself
            # (any concrete handler can follow any other), not one specific
            # sibling implementor — that narrower shape is Adapter/Decorator/
            # Proxy's "wraps one concrete RealX" instead. Without this, a
            # class that merely holds+delegates to a sibling implementor of
            # the same interface (e.g. a Proxy wrapping a RealService that
            # also implements Service) spuriously reads as a chain link too.
            for fr in field_references(graph, concrete.id):
                if fr.target.id != handler.id:
                    continue
                for method in methods_of(graph, concrete.id):
                    for target, _ in delegations(graph, method.id):
                        if target.id != fr.target.id:
                            continue
                        results.append(build_result(
                            pattern_id="chain_of_responsibility", status="detected", anchor=concrete,
                            roles={"handler": handler, "concrete_handler": concrete},
                            hard_evidence=[
                                f"{concrete.name} implements {handler.name}",
                                f"{concrete.name} holds a reference typed {handler.name} itself "
                                "(the next handler, not one fixed sibling)",
                                f"{concrete.name}.{method.name}() calls that next handler",
                            ],
                            graph=graph,
                        ))
    return results


def detect_command(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for command_iface in graph.by_kind.get("interface", []):
        concretes = implementors_of(graph, command_iface.id)
        if not concretes:
            continue
        invokers = [
            c for c in graph.classes()
            if any(fr.target.id == command_iface.id for fr in field_references(graph, c.id))
        ]
        if not invokers:
            continue
        for concrete in concretes:
            for fr in field_references(graph, concrete.id):
                receiver = fr.target
                if receiver.id == concrete.id:
                    continue
                for method in methods_of(graph, concrete.id):
                    for target, delegated in delegations(graph, method.id):
                        if target.id != receiver.id:
                            continue
                        results.append(build_result(
                            pattern_id="command", status="detected", anchor=concrete,
                            roles={
                                "command": command_iface, "concrete_command": concrete,
                                "receiver": receiver, "invoker": invokers[0],
                            },
                            hard_evidence=[
                                f"{concrete.name} implements {command_iface.name}",
                                f"{concrete.name} holds a reference to {receiver.name}",
                                f"{concrete.name}.{method.name}() delegates to {receiver.name}.{delegated}()",
                                f"{invokers[0].name} references {command_iface.name} without knowing the concrete type",
                            ],
                            graph=graph,
                        ))
    return results


def detect_iterator(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for aggregate in graph.classes():
        for target, in_method in instantiated_by(graph, aggregate.id):
            if in_method == "__init__" or target.id == aggregate.id:
                continue
            refs = field_references(graph, target.id)
            if not any(fr.target.id == aggregate.id for fr in refs):
                continue
            results.append(build_result(
                pattern_id="iterator", status="detected", anchor=aggregate,
                roles={"aggregate": aggregate, "iterator": target},
                hard_evidence=[
                    f"{aggregate.name}.{in_method}() instantiates {target.name}",
                    f"{target.name} holds its own reference back into {aggregate.name}, "
                    f"separate from {aggregate.name}'s own traversal state",
                ],
                graph=graph,
            ))
    return results


def detect_mediator(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for mediator in graph.classes():
        distinct: dict[str, object] = {fr.target.id: fr.target for fr in field_references(graph, mediator.id)}
        if len(distinct) < 2:
            continue
        confirmed = [
            colleague for colleague in distinct.values()
            if any(fr.target.id == mediator.id for fr in field_references(graph, colleague.id))
        ]
        if len(confirmed) < 2:
            continue
        results.append(build_result(
            pattern_id="mediator", status="detected", anchor=mediator,
            roles={"mediator": mediator, "colleague": confirmed[0]},
            hard_evidence=[
                f"{mediator.name} holds references to {len(confirmed)} colleagues",
                f"each of those {len(confirmed)} colleagues holds a reference back to {mediator.name}, "
                "not to each other directly",
            ],
            graph=graph,
        ))
    return results


def detect_memento(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for originator in graph.classes():
        for memento, snapshot_method in instantiated_by(graph, originator.id):
            if memento.id == originator.id:
                continue
            caretakers = [
                c for c in graph.classes() if c.id not in (originator.id, memento.id)
                and any(fr.target.id == memento.id for fr in field_references(graph, c.id))
            ]
            if not caretakers:
                continue
            results.append(build_result(
                pattern_id="memento", status="detected", anchor=originator,
                roles={"originator": originator, "memento": memento, "caretaker": caretakers[0]},
                hard_evidence=[
                    f"{originator.name}.{snapshot_method}() instantiates {memento.name} (a snapshot)",
                    f"{caretakers[0].name} holds a reference to {memento.name} without exposing its internals",
                ],
                graph=graph,
            ))
    return results


def detect_observer(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for subject in graph.classes():
        coll_field_names = {f.name for f in collection_fields(graph, subject.id)}
        if not coll_field_names:
            continue
        fan_out = [
            (method, field_name, called)
            for method, field_name, called in iterates_and_calls(graph, subject.id)
            if field_name in coll_field_names
        ]
        if not fan_out:
            continue
        method, field_name, called_method = fan_out[0]
        instantiated = instantiated_by(graph, subject.id)
        observer_role = instantiated[0][0] if instantiated else subject
        results.append(build_result(
            pattern_id="observer", status="detected", anchor=subject,
            roles={"subject": subject, "observer": observer_role},
            hard_evidence=[
                f"{subject.name} holds a homogeneous collection in field {field_name!r}",
                f"{subject.name}.{method.name}() iterates that collection and calls {called_method}() "
                "on each element (fan-out)",
            ],
            graph=graph,
        ))
    return results


def detect_state(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for context in graph.classes():
        for fr in field_references(graph, context.id):
            state_iface = fr.target
            if state_iface.kind != "interface":
                continue
            concretes = implementors_of(graph, state_iface.id)
            if len(concretes) < 2:
                continue
            concrete_ids = {c.id for c in concretes}
            trans = [t for t in transitions(graph, context.id) if t.id in concrete_ids]
            if not trans:
                continue  # no evidence of a transition — that's Strategy's shape
            delegating = [
                (m, delegated) for m in methods_of(graph, context.id)
                for target, delegated in delegations(graph, m.id) if target.id == state_iface.id
            ]
            if not delegating:
                continue
            method, delegated = delegating[0]
            results.append(build_result(
                pattern_id="state", status="detected", anchor=context,
                roles={"context": context, "state": state_iface, "concrete_state": concretes[0]},
                hard_evidence=[
                    f"{context.name} holds a reference to {state_iface.name}",
                    f"{state_iface.name} has {len(concretes)} concrete states",
                    f"{context.name}.{method.name}() delegates to the current state's {delegated}()",
                    f"{context.name} reassigns that field to {len(trans)} different concrete state(s) "
                    "from its own methods — a transition",
                ],
                graph=graph,
            ))
    return results


def detect_strategy(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for context in graph.classes():
        for fr in field_references(graph, context.id):
            strategy_iface = fr.target
            if strategy_iface.kind != "interface":
                continue
            concretes = implementors_of(graph, strategy_iface.id)
            if len(concretes) < 2:
                continue
            # A refined abstraction plus independent implementors is Bridge's
            # two-axis shape, not an interchangeable Strategy context.
            if subclasses_of(graph, context.id):
                continue
            concrete_ids = {c.id for c in concretes}
            trans = [t for t in transitions(graph, context.id) if t.id in concrete_ids]
            if trans:
                continue  # a transition is State's shape, not Strategy's
            delegating = [
                (m, delegated) for m in methods_of(graph, context.id)
                for target, delegated in delegations(graph, m.id) if target.id == strategy_iface.id
            ]
            if not delegating:
                continue
            method, delegated = delegating[0]
            results.append(build_result(
                pattern_id="strategy", status="detected", anchor=context,
                roles={"context": context, "strategy": strategy_iface, "concrete_strategy": concretes[0]},
                hard_evidence=[
                    f"{context.name} holds a reference to {strategy_iface.name}",
                    f"{strategy_iface.name} has {len(concretes)} interchangeable implementations",
                    f"{context.name}.{method.name}() delegates to the current strategy's {delegated}()",
                    "no reassignment of that field between concrete strategies was found from within "
                    f"{context.name} itself (that would instead be State)",
                ],
                graph=graph,
            ))
    return results


def detect_template_method(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    abstract_candidates = [*graph.classes(), *graph.by_kind.get("interface", [])]
    for abstract_class in abstract_candidates:
        for template in methods_of(graph, abstract_class.id):
            step_names: set[str] = set()
            for rel in graph.outgoing(template.id, "CALLS"):
                target = graph.entity(rel.target_id) if rel.target_id else None
                if target and target.kind in {"method", "constructor"}:
                    step_names.add(target.name)
            if len(step_names) < 2:
                continue
            subclasses = subclasses_of(graph, abstract_class.id) or implementors_of(graph, abstract_class.id)
            overriding = next(
                (sub for sub in subclasses if {m.name for m in methods_of(graph, sub.id)} & step_names),
                None,
            )
            if overriding is None:
                continue
            results.append(build_result(
                pattern_id="template_method", status="detected", anchor=abstract_class,
                roles={"abstract_class": abstract_class, "concrete_class": overriding},
                hard_evidence=[
                    f"{abstract_class.name}.{template.name}() calls {len(step_names)} of its own "
                    "overridable steps in sequence",
                    f"{overriding.name} inherits {abstract_class.name} and overrides at least one of those steps",
                ],
                graph=graph,
            ))
    return results


def detect_visitor(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    hits: dict[str, list] = {}
    for element in graph.classes():
        for method in methods_of(graph, element.id):
            for visitor, per_type_method in visitor_delegations(graph, method.id):
                hits.setdefault(visitor.id, []).append((element, method, per_type_method, visitor))

    results = []
    for entries in hits.values():
        distinct_elements = {e[0].id: e[0] for e in entries}
        distinct_methods = {e[2] for e in entries}
        if len(distinct_elements) < 2 or len(distinct_methods) < 2:
            continue
        first_element, first_method, _, visitor = entries[0]
        results.append(build_result(
            pattern_id="visitor", status="detected", anchor=visitor,
            roles={"visitor": visitor, "element": first_element},
            hard_evidence=[
                f"{visitor.name} receives a type-specific delegated call from {len(distinct_elements)} "
                f"different accept(visitor)-shaped methods across element classes",
                f"{visitor.name} exposes {len(distinct_methods)} distinct per-type methods",
            ],
            graph=graph,
        ))
    return results


DETECTORS = {
    "chain_of_responsibility": detect_chain_of_responsibility,
    "command": detect_command,
    "iterator": detect_iterator,
    "mediator": detect_mediator,
    "memento": detect_memento,
    "observer": detect_observer,
    "state": detect_state,
    "strategy": detect_strategy,
    "template_method": detect_template_method,
    "visitor": detect_visitor,
}

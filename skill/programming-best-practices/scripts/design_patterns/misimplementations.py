"""Conservative detection of incomplete pattern implementations.

A pattern-like name is only intent evidence. Every result below also requires
resolved structural evidence and one missing invariant; name alone never emits.
"""
from __future__ import annotations

from .detectors._shared import build_result, cache_fields, delegations, field_references, implements, instantiated_by, methods_of
from .ir import CodeGraph, Entity
from .model import PatternResult

SUPPORTED_MISIMPLEMENTATIONS = frozenset({"adapter", "builder", "singleton", "observer"})


def _intent(entity: Entity, token: str) -> bool:
    lowered = token.replace("_", "").lower()
    names = [entity.name, *entity.modifiers, *entity.annotations]
    return any(lowered in value.replace("_", "").lower() for value in names)


def _plan(pattern_id: str, violation: str, steps: list[str], verify: str) -> dict:
    return {
        "smell": violation,
        "candidate_pattern": pattern_id,
        "violation": violation,
        "steps": steps,
        "verification": verify,
        "behavior_preserving": True,
        "requires_semantic_review": True,
    }


def detect_misimplementations(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results: list[tuple[str, PatternResult]] = []
    for cls in graph.classes():
        refs = field_references(graph, cls.id)
        methods = methods_of(graph, cls.id)
        delegated_targets = {
            target.id for method in methods for target, _ in delegations(graph, method.id)
        }

        if _intent(cls, "adapter"):
            contracts = implements(graph, cls.id)
            if contracts and refs and not any(ref.target.id in delegated_targets for ref in refs):
                target, adaptee = contracts[0], refs[0].target
                results.append(build_result(
                    pattern_id="adapter", status="misimplemented", anchor=cls,
                    roles={"adapter": cls, "target": target, "adaptee": adaptee}, graph=graph,
                    hard_evidence=[
                        f"{cls.name} explicitly signals Adapter intent and implements {target.name}",
                        f"{cls.name} stores resolved adaptee {adaptee.name} but no method delegates to it",
                    ],
                    refactoring=_plan("adapter", "adapter stores an adaptee but does not delegate to it", [
                        f"Map each required {target.name} operation to the corresponding {adaptee.name} operation.",
                        "Keep conversion at the adapter boundary and preserve the target contract.",
                    ], "Run target-contract tests and verify at least one DELEGATES_TO edge reaches the adaptee."),
                ))

        if _intent(cls, "builder"):
            chain = [method for method in methods if method.return_type == cls.qualified_name]
            products = [(target, method) for target, method in instantiated_by(graph, cls.id) if target.id != cls.id]
            if len(chain) >= 2 and not products:
                results.append(build_result(
                    pattern_id="builder", status="misimplemented", anchor=cls,
                    roles={"builder": cls}, graph=graph,
                    hard_evidence=[
                        f"{cls.name} explicitly signals Builder intent and has {len(chain)} chaining steps",
                        "no terminal operation constructs a product distinct from the builder",
                    ],
                    refactoring=_plan("builder", "builder has fluent steps but no terminal product construction", [
                        "Introduce a terminal build operation that validates accumulated state.",
                        "Construct and return the product without exposing mutable builder internals.",
                    ], "Test a complete chain and assert the terminal operation returns the expected product."),
                ))

        if _intent(cls, "singleton"):
            cached = cache_fields(graph, cls.id)
            self_created = any(target.id == cls.id for target, _ in instantiated_by(graph, cls.id))
            if cached and not self_created:
                results.append(build_result(
                    pattern_id="singleton", status="misimplemented", anchor=cls,
                    roles={"singleton": cls}, graph=graph,
                    hard_evidence=[
                        f"{cls.name} explicitly signals Singleton intent and caches field {cached[0]!r}",
                        "its accessor never constructs the cached class instance",
                    ],
                    refactoring=_plan("singleton", "singleton cache cannot initialize its own instance", [
                        "Make the accessor initialize the cached instance exactly once.",
                        "Define synchronization or document single-threaded initialization where concurrency is possible.",
                    ], "Call the accessor repeatedly and concurrently where applicable; assert identity is stable."),
                ))

        if _intent(cls, "observer") or _intent(cls, "subject") or _intent(cls, "publisher"):
            collections = [member for member in graph.members(cls.id, "field") if not graph.outgoing(member.id, "REFERENCES")]
            notified = graph.outgoing(cls.id, "NOTIFIES")
            if collections and not notified:
                results.append(build_result(
                    pattern_id="observer", status="misimplemented", anchor=cls,
                    roles={"subject": cls}, graph=graph,
                    hard_evidence=[
                        f"{cls.name} signals Observer/Subject intent and owns a collection field",
                        "no fan-out notification edge reaches an observer contract",
                    ],
                    refactoring=_plan("observer", "subject stores observers but never notifies them", [
                        "Define the observer update contract and type the collection against it.",
                        "Notify a stable snapshot of registered observers after the relevant state change.",
                    ], "Register two test observers, trigger the event, and assert each receives one notification."),
                ))
    return results

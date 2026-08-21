"""Creational family (spec §11): Factory Method, Abstract Factory, Builder,
Prototype, Singleton. HARD evidence only (this corte).

Factory Method and Abstract Factory both fire from the same underlying shape
(a method that instantiates a class implementing some interface) and are
declared `conflicts_with` each other in the catalog, so `engine.py` merges
them into `ambiguous` when a single creation method is the only evidence —
matching spec §12's Factory Method vs Abstract Factory distinction, which
needs "familia de productos relacionados" (>=2 creation methods) to separate
them, exactly the check `detect_abstract_factory` requires below.
"""

from __future__ import annotations

from ..ir import CodeGraph
from ..model import PatternResult
from ._shared import (
    build_result,
    cache_fields,
    clones_self,
    implementors_of,
    implements,
    instantiated_by,
    methods_of,
)


def detect_factory_method(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for creator in graph.classes():
        for target, in_method in instantiated_by(graph, creator.id):
            if target.id == creator.id:
                continue
            abstract_products = implements(graph, target.id)
            if not abstract_products:
                continue
            product = abstract_products[0]
            results.append(build_result(
                pattern_id="factory_method", status="detected", anchor=creator,
                roles={"creator": creator, "product": product},
                hard_evidence=[
                    f"{creator.name}.{in_method}() instantiates {target.name}",
                    f"{target.name} implements {product.name}, an abstract product",
                ],
                graph=graph,
            ))
    return results


def detect_abstract_factory(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for abstract_factory in graph.by_kind.get("interface", []):
        contract_methods = {m.name for m in methods_of(graph, abstract_factory.id)}
        if len(contract_methods) < 2:
            continue
        concretes = implementors_of(graph, abstract_factory.id)
        if not concretes:
            continue
        for concrete_factory in concretes:
            families: dict[str, tuple] = {}
            for target, in_method in instantiated_by(graph, concrete_factory.id):
                if in_method not in contract_methods:
                    continue
                products = implements(graph, target.id)
                if products:
                    families[in_method] = (target, products[0])
            if len(families) < 2:
                continue
            first_target, first_product = next(iter(families.values()))
            results.append(build_result(
                pattern_id="abstract_factory", status="detected", anchor=concrete_factory,
                roles={
                    "abstract_factory": abstract_factory, "concrete_factory": concrete_factory,
                    "abstract_product": first_product, "concrete_product": first_target,
                },
                hard_evidence=[
                    f"{concrete_factory.name} implements {abstract_factory.name}",
                    f"{concrete_factory.name} creates {len(families)} related products across its creation methods",
                ],
                graph=graph,
            ))
    return results


def detect_builder(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for builder in graph.classes():
        chain_methods = [m for m in methods_of(graph, builder.id) if m.return_type == builder.qualified_name]
        if len(chain_methods) < 2:
            continue
        chain_names = {m.name for m in chain_methods}
        product = None
        for target, in_method in instantiated_by(graph, builder.id):
            if in_method in chain_names or target.id == builder.id:
                continue
            product = target
            break
        if product is None:
            continue
        results.append(build_result(
            pattern_id="builder", status="detected", anchor=builder,
            roles={"builder": builder, "product": product},
            hard_evidence=[
                f"{builder.name} has {len(chain_methods)} methods that return {builder.name} itself (chaining)",
                f"{builder.name} has a terminal method that instantiates {product.name}",
            ],
            graph=graph,
        ))
    return results


def detect_prototype(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for cls in graph.classes():
        if not clones_self(graph, cls.id):
            continue
        results.append(build_result(
            pattern_id="prototype", status="detected", anchor=cls,
            roles={"prototype": cls},
            hard_evidence=[
                f"{cls.name} has a method that clones itself "
                "(copy.deepcopy(self), type(self)(...), or self.__class__(...))",
            ],
            graph=graph,
        ))
    return results


def detect_singleton(graph: CodeGraph) -> list[tuple[str, PatternResult]]:
    results = []
    for cls in graph.classes():
        cached = cache_fields(graph, cls.id)
        if not cached:
            continue
        self_instantiated = any(target.id == cls.id for target, _ in instantiated_by(graph, cls.id))
        if not self_instantiated:
            continue
        results.append(build_result(
            pattern_id="singleton", status="detected", anchor=cls,
            roles={"singleton": cls},
            hard_evidence=[
                f"{cls.name} caches its own instance via field {cached[0]!r}",
                f"{cls.name} has an accessor that instantiates {cls.name} itself",
            ],
            graph=graph,
        ))
    return results


DETECTORS = {
    "factory_method": detect_factory_method,
    "abstract_factory": detect_abstract_factory,
    "builder": detect_builder,
    "prototype": detect_prototype,
    "singleton": detect_singleton,
}

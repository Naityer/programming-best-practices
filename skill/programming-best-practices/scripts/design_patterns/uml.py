"""Generates UML from role relations, never from a copied image (spec §15).

`Canonical UML -> role binding -> repository UML`: `_CANONICAL_EDGES` is the
theoretical diagram for each pattern (same shape as spec §15's own JSON
example); `render_mermaid`/`render_plantuml` bind the repository's actual
class names onto those roles. Output lands at
`{artifact}/uml/<pattern_id>-<NNN>.mmd` / `.puml` (spec §15/§18's
`uml_artifact` field points at the `.mmd` file).
"""

from __future__ import annotations

from .model import PatternResult

# (source_role, edge_label, target_role). Edge labels map to real UML
# notation in _MERMAID_EDGE / _PLANTUML_EDGE below — same relation vocabulary
# audit_code's graph.html legend already uses (Herencia/Realización/
# Asociación/Dependencia/Agregación/Composición). `build_uml_contract` carries
# that semantic type in design-patterns.json so consumers never have to parse
# a renderer-specific file or guess it from a generic "contains" relation.
_CANONICAL_EDGES: dict[str, list[tuple[str, str, str]]] = {
    "adapter": [
        ("client", "uses", "target"),
        ("adapter", "implements", "target"),
        ("adapter", "wraps", "adaptee"),
    ],
    "decorator": [("decorator", "implements", "component"), ("decorator", "contains", "concrete_component")],
    "proxy": [("proxy", "implements", "subject"), ("proxy", "contains", "real_subject")],
    "bridge": [
        ("refined_abstraction", "extends", "abstraction"),
        ("abstraction", "contains", "implementor"),
        ("concrete_implementor", "implements", "implementor"),
    ],
    "composite": [
        ("leaf", "implements", "component"),
        ("composite", "implements", "component"),
        ("composite", "contains", "component"),
    ],
    "flyweight": [("flyweight_factory", "creates", "flyweight"), ("context", "contains", "flyweight")],
    "factory_method": [("creator", "creates", "product")],
    "abstract_factory": [
        ("concrete_factory", "implements", "abstract_factory"),
        ("concrete_factory", "creates", "concrete_product"),
        ("concrete_product", "implements", "abstract_product"),
    ],
    "builder": [("builder", "creates", "product")],
    "prototype": [("prototype", "clones", "prototype")],
    "singleton": [("singleton", "caches", "singleton")],
    "chain_of_responsibility": [
        ("concrete_handler", "implements", "handler"),
        ("concrete_handler", "contains", "handler"),
    ],
    "command": [
        ("concrete_command", "implements", "command"),
        ("concrete_command", "contains", "receiver"),
        ("invoker", "contains", "command"),
    ],
    "iterator": [("aggregate", "creates", "iterator")],
    "mediator": [("colleague", "contains", "mediator"), ("mediator", "contains", "colleague")],
    "memento": [("originator", "creates", "memento"), ("caretaker", "contains", "memento")],
    "observer": [("subject", "contains", "observer")],
    "state": [("context", "contains", "state"), ("concrete_state", "implements", "state")],
    "strategy": [("context", "contains", "strategy"), ("concrete_strategy", "implements", "strategy")],
    "template_method": [("concrete_class", "extends", "abstract_class")],
    "visitor": [("concrete_element", "contains", "visitor")],
}

_UML_TYPE = {
    "implements": "realization",
    "extends": "generalization",
    # A stored reference does not prove lifecycle ownership. Default to a
    # directed association; reserve aggregation/composition for explicit
    # canonical statements instead of turning every CONTAINS fact into *--.
    "contains": "association",
    "wraps": "association",
    "uses": "dependency",
    "creates": "dependency",
    "clones": "dependency",
    "caches": "dependency",
}
_EDGE_BY_UML_TYPE = {
    "generalization": "--|>",
    "realization": "..|>",
    "association": "-->",
    "dependency": "..>",
    "aggregation": "o--",
    "composition": "*--",
}
_CLASSIFIER_BY_PATTERN_ROLE: dict[tuple[str, str], str] = {
    ("adapter", "target"): "interface",
    ("decorator", "component"): "interface",
    ("proxy", "subject"): "interface",
    ("bridge", "abstraction"): "abstract",
    ("bridge", "implementor"): "interface",
    ("composite", "component"): "interface",
    ("abstract_factory", "abstract_factory"): "interface",
    ("abstract_factory", "abstract_product"): "interface",
    ("chain_of_responsibility", "handler"): "interface",
    ("command", "command"): "interface",
    ("state", "state"): "interface",
    ("strategy", "strategy"): "interface",
    ("template_method", "abstract_class"): "abstract",
}
_MULTIPLICITY: dict[tuple[str, str, str], tuple[str | None, str | None]] = {
    ("adapter", "adapter", "adaptee"): ("1", "1"),
    ("composite", "composite", "component"): ("1", "0..*"),
    ("observer", "subject", "observer"): ("1", "0..*"),
}


def build_uml_contract(pattern: PatternResult) -> dict:
    """Return renderer-neutral UML, including canonical roles not yet bound."""
    edges = _edges_for(pattern)
    ordered_roles: list[str] = []
    for source_role, _, target_role in edges:
        for role in (source_role, target_role):
            if role not in ordered_roles:
                ordered_roles.append(role)
    for role in pattern.roles:
        if role not in ordered_roles:
            ordered_roles.append(role)
    nodes = [{
        "role": role,
        "name": pattern.roles.get(role),
        "bound": bool(pattern.roles.get(role)),
        "classifier": _CLASSIFIER_BY_PATTERN_ROLE.get((pattern.pattern_id, role), "class"),
    } for role in ordered_roles]
    relationships = []
    for source_role, label, target_role in edges:
        source_mult, target_mult = _MULTIPLICITY.get(
            (pattern.pattern_id, source_role, target_role), (None, None)
        )
        relationships.append({
            "source_role": source_role,
            "target_role": target_role,
            "type": _UML_TYPE.get(label, "dependency"),
            "label": label,
            "source_multiplicity": source_mult,
            "target_multiplicity": target_mult,
        })
    return {"notation": "UML 2.5.1", "nodes": nodes, "relationships": relationships}


def _edges_for(pattern: PatternResult) -> list[tuple[str, str, str]]:
    edges = list(_CANONICAL_EDGES.get(pattern.pattern_id, []))
    subsystem_roles = sorted(role for role in pattern.roles if role.startswith("subsystem_"))
    for role in subsystem_roles:
        edges.append(("facade", "contains", role))
    return edges


def _mermaid_declaration(pattern_id: str, role: str, name: str) -> list[str]:
    classifier = _CLASSIFIER_BY_PATTERN_ROLE.get((pattern_id, role), "class")
    lines = [f"  class {name}"]
    if classifier == "interface":
        lines.append(f"  <<interface>> {name}")
    elif classifier == "abstract":
        lines.append(f"  <<abstract>> {name}")
    return lines


def _plantuml_declaration(pattern_id: str, role: str, name: str) -> str:
    classifier = _CLASSIFIER_BY_PATTERN_ROLE.get((pattern_id, role), "class")
    if classifier == "interface":
        return f"interface {name}"
    if classifier == "abstract":
        return f"abstract class {name}"
    return f"class {name}"


def _render_relation(source: str, arrow: str, target: str, label: str,
                     multiplicity: tuple[str | None, str | None]) -> str:
    source_mult, target_mult = multiplicity
    source_end = f' "{source_mult}"' if source_mult else ""
    target_end = f' "{target_mult}"' if target_mult else ""
    return f"{source}{source_end} {arrow}{target_end} {target} : {label}"


def render_mermaid(pattern: PatternResult) -> str:
    lines = ["classDiagram"]
    seen_nodes: set[str] = set()
    for source_role, label, target_role in _edges_for(pattern):
        source = pattern.roles.get(source_role)
        target = pattern.roles.get(target_role)
        if not source or not target:
            continue
        for role, name in ((source_role, source), (target_role, target)):
            if name not in seen_nodes:
                lines.extend(_mermaid_declaration(pattern.pattern_id, role, name))
                seen_nodes.add(name)
        arrow = _EDGE_BY_UML_TYPE[_UML_TYPE.get(label, "dependency")]
        multiplicity = _MULTIPLICITY.get(
            (pattern.pattern_id, source_role, target_role), (None, None)
        )
        lines.append("  " + _render_relation(source, arrow, target, label, multiplicity))
    if not seen_nodes:
        for role, name in pattern.roles.items():
            lines.extend(_mermaid_declaration(pattern.pattern_id, role, name))
    return "\n".join(lines) + "\n"


def render_plantuml(pattern: PatternResult) -> str:
    lines = ["@startuml"]
    seen_nodes: set[str] = set()
    for source_role, label, target_role in _edges_for(pattern):
        source = pattern.roles.get(source_role)
        target = pattern.roles.get(target_role)
        if not source or not target:
            continue
        for role, name in ((source_role, source), (target_role, target)):
            if name not in seen_nodes:
                lines.append(_plantuml_declaration(pattern.pattern_id, role, name))
                seen_nodes.add(name)
        arrow = _EDGE_BY_UML_TYPE[_UML_TYPE.get(label, "dependency")]
        multiplicity = _MULTIPLICITY.get(
            (pattern.pattern_id, source_role, target_role), (None, None)
        )
        lines.append(_render_relation(source, arrow, target, label, multiplicity))
    if not seen_nodes:
        for role, name in pattern.roles.items():
            lines.append(_plantuml_declaration(pattern.pattern_id, role, name))
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def artifact_name(pattern: PatternResult, sequence: int) -> str:
    return f"{pattern.pattern_id}-{sequence:03d}"

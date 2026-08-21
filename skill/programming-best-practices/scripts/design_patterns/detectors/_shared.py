"""IR query helpers shared by every detector.

These exist so a detector never re-scans `graph.entities`/`graph.relations`
directly (spec §26: anchors come from the indices, never a full sweep) and so
the HARD-evidence shape ("class CONTAINS a field that REFERENCES class Y") is
written once instead of 22 times.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..confidence import compute_confidence
from ..evidence import Evidence, hard
from ..ir import CodeGraph, Entity
from ..model import EvidenceEntry, Location, PatternResult


def implements(graph: CodeGraph, class_id: str) -> list[Entity]:
    return [t for r in graph.outgoing(class_id, "IMPLEMENTS") if (t := graph.entity(r.target_id))]


def inherits(graph: CodeGraph, class_id: str) -> list[Entity]:
    return [t for r in graph.outgoing(class_id, "INHERITS") if (t := graph.entity(r.target_id))]


def implementors_of(graph: CodeGraph, interface_id: str) -> list[Entity]:
    return [graph.entity(r.source_id) for r in graph.incoming(interface_id, "IMPLEMENTS") if graph.entity(r.source_id)]


def subclasses_of(graph: CodeGraph, base_id: str) -> list[Entity]:
    return [graph.entity(r.source_id) for r in graph.incoming(base_id, "INHERITS") if graph.entity(r.source_id)]


def methods_of(graph: CodeGraph, class_id: str) -> list[Entity]:
    return [m for m in graph.members(class_id) if m.kind in {"method", "constructor"}]


@dataclass(frozen=True)
class FieldRef:
    field: Entity
    target: Entity
    field_name: str


def field_references(graph: CodeGraph, class_id: str) -> list[FieldRef]:
    """Fields of `class_id` whose declared/inferred type resolved to another
    class/interface in scope — the composition edge every wrapper-based
    pattern (Adapter/Decorator/Proxy/Bridge/Strategy/State/Command/Mediator)
    needs as its first HARD check."""
    out: list[FieldRef] = []
    for rel in graph.outgoing(class_id, "CONTAINS"):
        field = graph.entity(rel.target_id) if rel.target_id else None
        if not field or field.kind != "field":
            continue
        for ref in graph.outgoing(field.id, "REFERENCES"):
            target = graph.entity(ref.target_id) if ref.target_id else None
            if target:
                out.append(FieldRef(field=field, target=target, field_name=rel.detail or field.name))
    return out


def collection_fields(graph: CodeGraph, class_id: str) -> list[Entity]:
    """Fields whose value is a homogeneous collection (Observer/Composite's
    anchor) — CONTAINS with no matching REFERENCES (field_references only
    returns typed/resolved single references, so a bare collection field
    shows up here instead)."""
    referenced_ids = {fr.field.id for fr in field_references(graph, class_id)}
    fields = [m for m in graph.members(class_id) if m.kind == "field"]
    return [f for f in fields if f.id not in referenced_ids]


def delegations(graph: CodeGraph, method_id: str) -> list[tuple[Entity, str]]:
    """[(target_class, delegated_method_name), ...] for a DELEGATES_TO
    relation whose source is this method. Excludes the accept(visitor)-shaped
    delegations that `visitor_delegations()` reads instead — see the
    `"visit:"` detail marker set by frontends/python.py."""
    out = []
    for rel in graph.outgoing(method_id, "DELEGATES_TO"):
        if (rel.detail or "").startswith("visit:"):
            continue
        target = graph.entity(rel.target_id) if rel.target_id else None
        if target:
            out.append((target, rel.detail or ""))
    return out


def visitor_delegations(graph: CodeGraph, method_id: str) -> list[tuple[Entity, str]]:
    """[(visitor_class, per_type_method_name), ...] — only the
    accept(visitor)-shaped delegations (spec §11 Visitor's `accept(visitor)`
    anchor), never ordinary field-based delegation."""
    out = []
    for rel in graph.outgoing(method_id, "DELEGATES_TO"):
        detail = rel.detail or ""
        if not detail.startswith("visit:"):
            continue
        target = graph.entity(rel.target_id) if rel.target_id else None
        if target:
            out.append((target, detail[len("visit:"):]))
    return out


def instantiated_by(graph: CodeGraph, class_id: str) -> list[tuple[Entity, str]]:
    """[(instantiated_class, in_method_name), ...]."""
    out = []
    for rel in graph.outgoing(class_id, "INSTANTIATES"):
        target = graph.entity(rel.target_id) if rel.target_id else None
        if target:
            out.append((target, rel.detail or ""))
    return out


def transitions(graph: CodeGraph, class_id: str) -> list[Entity]:
    return [t for r in graph.outgoing(class_id, "TRANSITIONS_TO") if (t := graph.entity(r.target_id))]


def clones_self(graph: CodeGraph, class_id: str) -> bool:
    return any(r.target_id == class_id for r in graph.outgoing(class_id, "CLONES"))


def cache_fields(graph: CodeGraph, class_id: str) -> list[str]:
    return [r.detail for r in graph.outgoing(class_id, "CACHES") if r.detail]


def iterates_and_calls(graph: CodeGraph, class_id: str) -> list[tuple[Entity, str, str]]:
    """[(method, iterated_field_name_via_field_entity_name, called_method), ...]
    reads ITERATES relations whose source is one of this class's methods."""
    out = []
    for method in methods_of(graph, class_id):
        for rel in graph.outgoing(method.id, "ITERATES"):
            field = graph.entity(rel.target_id) if rel.target_id else None
            if field:
                out.append((method, field.name, rel.detail or ""))
    return out


def location_of(entity: Entity) -> Location:
    return Location(file=entity.file, line=entity.line)


def build_result(
    *,
    pattern_id: str,
    status: str,
    anchor: Entity,
    roles: dict[str, Entity],
    hard_evidence: list[str],
    graph: CodeGraph,
    behavioral_evidence: list[str] = (),
    uml_artifact: str | None = None,
    refactoring: dict | None = None,
) -> tuple[str, PatternResult]:
    """Assembles one detector hit. `hard_evidence`/`behavioral_evidence` are
    plain descriptions — the caller has already confirmed every one of them
    holds; this function only wires them through compute_confidence(), it
    does not re-derive whether they're true.
    """
    evidence: list[Evidence] = [hard(text) for text in hard_evidence]
    evidence.extend(Evidence("behavioral", text) for text in behavioral_evidence)
    confidence = compute_confidence(
        all_hard_satisfied=bool(hard_evidence),
        evidence=evidence,
        frontend_level=graph.frontend_level,
        symbols_resolved=True,
    )
    result = PatternResult(
        pattern_id=pattern_id,
        status=status,
        confidence=confidence,
        primary_location=location_of(anchor),
        roles={role: entity.qualified_name for role, entity in roles.items()},
        evidence=[EvidenceEntry(kind=item.kind, description=item.description) for item in evidence],
        uml_artifact=uml_artifact,
        refactoring=refactoring,
    )
    return anchor.id, result

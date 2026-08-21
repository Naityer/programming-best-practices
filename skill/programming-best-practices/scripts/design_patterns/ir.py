"""Universal Code IR (spec §5): the model every language frontend normalizes
into, and the only thing detectors are allowed to read.

Detectors must never inspect `Entity.language`. That invariant is what makes
one detector work for Python, Java, Go, Rust, ... without 22 x N
implementations (spec §3, §31.6) — enforced by
tests/test_design_patterns_ir.py running the engine against a synthetic
CodeGraph with no frontend involved at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

ENTITY_KINDS = {
    "class", "interface", "trait", "struct", "enum", "function", "method",
    "constructor", "field", "property", "module",
}

# Closed vocabulary (spec §5.2). Frontends may only emit these; a detector
# that needs a relation not in this set is asking the wrong question.
RELATION_TYPES = {
    "INHERITS", "IMPLEMENTS", "CONTAINS", "REFERENCES", "INSTANTIATES",
    "CALLS", "RETURNS", "DELEGATES_TO", "WRAPS", "REGISTERS", "NOTIFIES",
    "ITERATES", "TRANSITIONS_TO", "CLONES", "CACHES", "CREATES", "USES",
}


@dataclass(frozen=True)
class Entity:
    id: str
    language: str
    kind: str
    name: str
    qualified_name: str
    file: str
    line: int
    modifiers: tuple[str, ...] = ()
    annotations: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    return_type: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ENTITY_KINDS:
            raise ValueError(f"unknown entity kind: {self.kind!r}")


@dataclass(frozen=True)
class Relation:
    type: str
    source_id: str
    # Exactly one of target_id (resolved to an Entity in this graph) or
    # target_unresolved (a bare name the frontend could not bind — e.g. a
    # base class defined outside the scanned scope) must be set.
    target_id: str | None = None
    target_unresolved: str | None = None
    detail: str | None = None  # e.g. the delegated method name

    def __post_init__(self) -> None:
        if self.type not in RELATION_TYPES:
            raise ValueError(f"unknown relation type: {self.type!r}")
        if not self.target_id and not self.target_unresolved:
            raise ValueError("relation needs target_id or target_unresolved")


@dataclass(frozen=True)
class DiscriminatorBranch:
    """One `if/elif` (or `match`) chain that compares a parameter against
    literal constants. Feeds opportunities.py (spec §13) — not part of the
    closed Entity/Relation vocabulary because it is a supplementary shape,
    not a pairwise relation.
    """

    function_id: str
    discriminator_param: str
    branch_values: tuple[str, ...]
    line: int


class CodeGraph:
    """Read-only, indexed view over an IR. Detectors query it; they never
    walk `entities`/`relations` directly for anything but a full scan.

    The indices exist because spec §26 forbids a generic subgraph-isomorphism
    sweep: each detector must start from `by_relation`/`by_kind` anchors.
    """

    def __init__(
        self,
        entities: Iterable[Entity],
        relations: Iterable[Relation],
        discriminator_branches: Iterable[DiscriminatorBranch] = (),
        *,
        frontend_level: str = "B",
    ) -> None:
        # Confidence ceiling for everything a detector reads from this graph
        # (confidence.py, spec §6). A run that mixes frontends of different
        # levels should build one CodeGraph per level rather than merging —
        # this corte only ever has one frontend active (Python, Level B).
        self.frontend_level = frontend_level
        self.entities: dict[str, Entity] = {e.id: e for e in entities}
        self.relations: list[Relation] = list(relations)
        self.discriminator_branches: list[DiscriminatorBranch] = list(discriminator_branches)

        self.by_kind: dict[str, list[Entity]] = {}
        for entity in self.entities.values():
            self.by_kind.setdefault(entity.kind, []).append(entity)

        self.by_name: dict[str, list[Entity]] = {}
        for entity in self.entities.values():
            self.by_name.setdefault(entity.name.lower(), []).append(entity)

        self.by_relation: dict[str, list[Relation]] = {}
        self._out: dict[tuple[str, str], list[Relation]] = {}
        self._in: dict[tuple[str, str], list[Relation]] = {}
        for relation in self.relations:
            self.by_relation.setdefault(relation.type, []).append(relation)
            self._out.setdefault((relation.source_id, relation.type), []).append(relation)
            if relation.target_id:
                self._in.setdefault((relation.target_id, relation.type), []).append(relation)

    def entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def outgoing(self, entity_id: str, relation_type: str) -> list[Relation]:
        return self._out.get((entity_id, relation_type), [])

    def incoming(self, entity_id: str, relation_type: str) -> list[Relation]:
        return self._in.get((entity_id, relation_type), [])

    def members(self, entity_id: str, kind: str | None = None) -> list[Entity]:
        result = []
        for relation in self.outgoing(entity_id, "CONTAINS"):
            if relation.target_id and relation.target_id in self.entities:
                member = self.entities[relation.target_id]
                if kind is None or member.kind == kind:
                    result.append(member)
        return result

    def resolve_by_name(self, name: str) -> list[Entity]:
        return self.by_name.get(name.lower(), [])

    def classes(self) -> Iterator[Entity]:
        for kind in ("class", "struct"):
            yield from self.by_kind.get(kind, [])

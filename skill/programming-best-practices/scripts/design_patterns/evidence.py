"""Evidence taxonomy (spec §9).

A class name, comment, or annotation may only ever produce `supporting`
evidence. `confidence.py` enforces — as an invariant, not a convention — that
`supporting` evidence alone can never justify emitting a pattern, and can
never move the confidence tier. That is the mechanism replacing
`_detect_by_name`'s fixed 0.55 (spec §2, §29).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EvidenceKind = Literal["hard", "behavioral", "supporting", "contradiction"]


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    description: str
    relation_type: str | None = None
    entity_ids: tuple[str, ...] = ()


def hard(description: str, *, relation_type: str | None = None, entity_ids: tuple[str, ...] = ()) -> Evidence:
    return Evidence("hard", description, relation_type=relation_type, entity_ids=entity_ids)


def behavioral(description: str, *, relation_type: str | None = None, entity_ids: tuple[str, ...] = ()) -> Evidence:
    return Evidence("behavioral", description, relation_type=relation_type, entity_ids=entity_ids)


def supporting(description: str, *, entity_ids: tuple[str, ...] = ()) -> Evidence:
    return Evidence("supporting", description, entity_ids=entity_ids)


def contradiction(description: str, *, entity_ids: tuple[str, ...] = ()) -> Evidence:
    return Evidence("contradiction", description, entity_ids=entity_ids)

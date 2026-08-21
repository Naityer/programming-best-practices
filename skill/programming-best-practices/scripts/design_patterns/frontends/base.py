"""Common contract every language frontend implements (spec §7).

One deliberate deviation from the spec's literal signature:
`build_relations` takes every parsed `SourceUnit` in the repository, not just
one. Spec §5.2 and §17 both give examples where Target/Adapter/Adaptee live in
three different files — resolving `LegacyAdapter -> PaymentGateway` needs a
project-wide symbol table, not a per-file view. The engine still never sees a
language: it only ever gets back a `CodeGraph`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..ir import DiscriminatorBranch, Entity, Relation

#: spec §6 — caps confidence.py's ceiling for anything this frontend reports.
#: "A": semantic (types + resolved symbols + call graph). "B": AST + local
#: symbol table + import resolution. "C": lexical fallback — a frontend at
#: this level must never claim its output can reach "high" confidence.
FrontendLevel = str  # "A" | "B" | "C"


@dataclass
class SourceUnit:
    """One parsed file's contribution, before cross-file linking."""

    file: str
    language: str
    entities: list[Entity] = field(default_factory=list)
    discriminator_branches: list[DiscriminatorBranch] = field(default_factory=list)


class LanguageFrontend(Protocol):
    level: FrontendLevel

    def supports(self, path: Path) -> bool:
        ...

    def parse(self, source: str, path: Path) -> SourceUnit:
        ...

    def build_relations(self, units: list[SourceUnit]) -> list[Relation]:
        ...

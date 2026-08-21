# Language mapping

Per-language notes on how a real construct maps onto the closed IR vocabulary
(`scripts/design_patterns/ir.py`'s `ENTITY_KINDS`/`RELATION_TYPES`) live as
data in `scripts/design_patterns/frontends/language_profiles.py`
(`LanguageProfile` per language), not duplicated here — read that module for
the authoritative, structured version.

This file is the prose companion spec §7 asks for: what a future frontend for
each language needs to get right, beyond what the data table captures.

## Python — implemented (`frontends/python.py`, Level B)

Uses `stdlib ast` only, never imports the audited project. `IMPLEMENTS` is
derived structurally from `abc.ABC`/`abc.ABCMeta`/`typing.Protocol` bases and
from `@abstractmethod`-decorated or trivially-abstract-shaped methods (`pass`,
`...`, or a bare `raise NotImplementedError`) — never from a class's name.

## Java/JVM — not implemented

`interface`/`abstract class` map directly onto `IMPLEMENTS`/`INHERITS`.
Kotlin's `data class`, `object`, `sealed class`, and `by` delegation need to
collapse onto the same concepts (spec §7: "Kotlin debe mapear ... hacia los
mismos conceptos del IR") rather than becoming new IR vocabulary.

## JavaScript/TypeScript — not implemented

TypeScript's `interface`/`abstract class` map the same way as Java. Plain
JavaScript must not require a classical hierarchy at all: an interchangeable
function or closure passed as a parameter is a legitimate `strategy`/`state`
role (spec §7's explicit example).

## .NET — not implemented

`event` is a strong, real Observer signal — not a naming convention, a
language mechanism — and should map onto `REGISTERS`/`NOTIFIES` directly.
`delegate` can represent Strategy or Command depending on whether it is
reassigned across the object's lifetime (same test `detect_state`/
`detect_strategy` already apply via `TRANSITIONS_TO`).

## Go — not implemented

No explicit `implements`. `IMPLEMENTS` must be inferred by comparing an
interface's method set against a struct's method set — real structural
compatibility, not a keyword to look for.

## Rust — not implemented

`trait`/`impl` map onto `IMPLEMENTS`. Spec §7 is explicit that State may
appear as a `trait` **or** as a plain `enum` with variants — the detector must
recognize the structural intent (a value that discriminates behavior and
transitions), not only the OOP shape `detect_state` currently expects.

## C/C++ — not implemented

Virtual/pure-virtual methods map onto `IMPLEMENTS`/`INHERITS`; function
pointers and `std::function` members are the composition signal `field_
references()` looks for in every other language. When a template or a type
relation cannot be resolved, `confidence.py`'s `symbols_resolved=False` path
must be used — never invent the relation (spec §7).

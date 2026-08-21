"""Per-language mapping notes from spec §7, kept as data so a future
tree-sitter-backed frontend (or a semantic Level-A frontend) has a single
place to look up how a language's real constructs map onto the closed IR
vocabulary (ir.py). Nothing in this corte executes these profiles — only
`frontends/python.py` is wired into the engine today (design-patterns-module/
02-decisiones.md, D4). Kept here, not inline in prose, so `catalog.py`-style
validation can eventually check a real frontend against it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    language: str
    #: real language constructs that map to IMPLEMENTS (not INHERITS)
    interface_constructs: tuple[str, ...]
    #: real language constructs that signal Observer without needing a name
    observer_signals: tuple[str, ...]
    #: real language constructs that signal Strategy/Command without a name
    interchangeable_signals: tuple[str, ...]
    notes: str


PROFILES: dict[str, LanguageProfile] = {
    "python": LanguageProfile(
        language="python",
        interface_constructs=("abc.ABC", "abc.ABCMeta", "typing.Protocol", "@abstractmethod"),
        observer_signals=(),
        interchangeable_signals=("callable parameter/attribute", "first-class function"),
        notes="Implemented in frontends/python.py (Level B, stdlib ast, no imports of the audited project).",
    ),
    "java": LanguageProfile(
        language="java",
        interface_constructs=("interface", "abstract class"),
        observer_signals=(),
        interchangeable_signals=(),
        notes="Not implemented in this corte. Normalize extends/implements, fields, constructors, "
              "method calls, new, @Override to the same IMPLEMENTS/INHERITS/CONTAINS/CALLS/INSTANTIATES "
              "vocabulary python.py already emits.",
    ),
    "kotlin": LanguageProfile(
        language="kotlin",
        interface_constructs=("interface", "sealed class"),
        observer_signals=(),
        interchangeable_signals=("object", "delegation (`by`)"),
        notes="Not implemented. Map `data class`/`object`/`sealed class`/`by` delegation onto the same IR "
              "concepts as Java, per spec §7 (\"Kotlin debe mapear ... hacia los mismos conceptos del IR\").",
    ),
    "typescript": LanguageProfile(
        language="typescript",
        interface_constructs=("interface", "abstract class"),
        observer_signals=(),
        interchangeable_signals=("function type", "closure", "callback"),
        notes="Not implemented. Spec §7: JavaScript must not require classical hierarchies — an "
              "interchangeable function can represent Strategy.",
    ),
    "csharp": LanguageProfile(
        language="csharp",
        interface_constructs=("interface", "abstract class"),
        observer_signals=("event",),
        interchangeable_signals=("delegate",),
        notes="Not implemented. Spec §7: `event` is a strong Observer signal; `delegate` can represent "
              "Strategy or Command.",
    ),
    "go": LanguageProfile(
        language="go",
        interface_constructs=("implicit interface satisfaction",),
        observer_signals=(),
        interchangeable_signals=("first-class function", "implicit interface"),
        notes="Not implemented. Spec §7: no explicit `implements` — IMPLEMENTS must be inferred from "
              "method-set compatibility between an interface and a struct.",
    ),
    "rust": LanguageProfile(
        language="rust",
        interface_constructs=("trait", "dyn Trait", "Box<dyn Trait>"),
        observer_signals=(),
        interchangeable_signals=("trait object", "enum variant"),
        notes="Not implemented. Spec §7: State may appear as a `trait` OR as an `enum` — the detector must "
              "recognize the structural intent, not just the GoF-OOP shape.",
    ),
    "cpp": LanguageProfile(
        language="cpp",
        interface_constructs=("pure virtual class",),
        observer_signals=(),
        interchangeable_signals=("function pointer", "std::function"),
        notes="Not implemented. Spec §7: an unresolved template/type relation must lower confidence to "
              "medium/low, never invent the relation.",
    ),
}

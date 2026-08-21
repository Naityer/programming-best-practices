# Design pattern detection

Read this when evaluating architecture, design patterns, pattern misuse,
refactoring opportunities, coupling, or object collaboration (spec §24).

## What the analyzer does and does not decide

`scripts/analyze_design_patterns.py` is **tier 1** of the decision hierarchy:
deterministic, structural, no LLM. It never emits a pattern on name evidence
alone — see `scripts/design_patterns/confidence.py` for the enforced ceiling,
and `scripts/design_patterns/detectors/` for what each of the 22 catalog
entries actually checks (structure, relations — never
`class_name.endswith("Adapter")`).

Its output states mean:

| Status | What it means | Becomes a finding? |
|---|---|---|
| `detected` | Pattern present, invariants hold | No |
| `partial` | Substantial structure, not enough to claim complete | No |
| `ambiguous` | Two catalog `conflicts_with` patterns explain the same structure | No (dimension + limitation) |
| `misimplemented` | Intent demonstrated, an invariant is violated | Yes, if concrete impact |
| `refactor-opportunity` | No pattern present, but a repeated, observed problem could be simplified by one | Yes |

A `detected` or `partial` result is not something to act on. Read the
`evidence` array before treating any `misimplemented`/`refactor-opportunity`
result as real — every entry there names a concrete relation or repeated
structural fact, never a name-based inference.

## Tier 2 — what you (the agent) add

You are the second tier: medium-complexity judgment the deterministic
detector cannot make on its own. Concretely:

- Read the source around a `misimplemented` or `refactor-opportunity` finding
  before confirming or dismissing it (`--semantic-review`, same as every
  other finding in this skill — see `automation.md`).
- For `ambiguous` results, you may narrow the choice if the source makes it
  unambiguous to a human reader (e.g. a docstring that states the intent
  clearly, or a call site whose behavior the analyzer could not trace).
  Record your reasoning as the review's `reason`; do not silently pick one.
- Do not recommend a pattern that was not raised as a `refactor-opportunity`
  by the analyzer, and do not recommend it without the repeated, observed
  problem the analyzer named. `SKILL.md`'s existing rule already says this
  for every recommendation in this skill: *"Do not recommend a pattern,
  interface, factory, abstraction, or rewrite without a concrete recurring
  problem it simplifies."* This module is that rule's structural detector.

## Tier 3 — what only a human decides

Escalate instead of guessing when:

- An `ambiguous` result stays ambiguous after reading the source — two
  patterns are genuinely, legitimately indistinguishable at the code's
  current state (spec §12's whole point).
- A `misimplemented` finding would change public behavior to fix.
- A `refactor-opportunity` implies restructuring more than the flagged sites.
- Anything touching `Singleton` — the catalog's `opportunity_signal` for it
  is explicitly "no recomendar automáticamente" (spec §11); a detected
  Singleton is reported, never suggested as a fix for something else.

## Severity

A design-pattern finding defaults to `low`/`medium` (spec §20). Only
correlate it to `high`/`blocker` when a DIFFERENT module's evidence supports
it — a `misimplemented` Singleton plus a demonstrated race from a
concurrency/security finding, or a `flyweight` refactor-opportunity plus a
measured memory finding from `performance.md`'s profiling. Never invent the
security or performance benefit yourself (spec §13/§20/§21).

## Where the detection logic actually lives

- `scripts/design_patterns/ir.py` — the language-agnostic model every
  detector reads (spec §5).
- `scripts/design_patterns/catalog.py` + `catalog.json` — the 22 patterns'
  roles and conflicts, knowledge not algorithms (spec §8).
- `scripts/design_patterns/detectors/{creational,structural,behavioral}.py`
  — the actual structural checks (spec §9, §11).
- `scripts/design_patterns/engine.py` — merges conflicting detections into
  `ambiguous` instead of guessing (spec §10, §12).
- `scripts/design_patterns/opportunities.py` — the refactor-opportunity
  detector (spec §13); the only part of this corte that produces findings.
- `scripts/design_patterns/uml.py` — generates `uml/*.mmd`/`*.puml` from the
  bound roles, never a copied image (spec §15).

## Corte limitations (be honest about these when reporting)

This delivery (see `Workspace/design-patterns-module/02-decisiones.md`, D1)
collects only HARD structural evidence, plus the discriminator-repetition
check for refactor-opportunities. Consequences to disclose when relevant:

- Adapter, Decorator, and Proxy cannot be told apart without behavioral
  evidence and are reported as `ambiguous` when their shared structural shape
  fires (spec §12). State and Strategy ARE separated, using the presence or
  absence of a `TRANSITIONS_TO` relation as structural (not behavioral)
  evidence.
- Only Python is analyzed (`frontends/python.py`, AST-based, Level B). Other
  languages produce a `limitation`, never a fabricated result — see
  `frontends/language_profiles.py` for what each would need.

# Core principles

## Contents

1. Priorities
2. Repository conventions
3. Design heuristics
4. Functions, comments, and errors
5. Changes and compatibility
6. Do not apply blindly

## Priorities

Improve maintainability, clarity, testability, and security with the smallest change that correctly solves the observed problem. Preserve external behavior during refactoring unless behavior change is the task.

Use this decision order:

1. Correctness and data integrity
2. Security and authorization
3. Required behavior and compatibility
4. Simplicity and explicitness
5. Readability and maintainability
6. Proven extensibility needs
7. Cosmetics

Do not refactor healthy code merely to make it different. Prefer deleting unnecessary complexity over wrapping it in another abstraction.

## Repository conventions

Read `AGENTS.md`, contribution guides, manifests, formatter/linter configuration, architecture tests, public schemas, and nearby code before judging a change. Repository-specific rules override generic preferences unless they create a correctness or security defect.

Keep infrastructure commands native to the project. Preserve public APIs, serialization, database behavior, error contracts, CLI output, and supported versions unless the task changes them.

## Design heuristics

Use SOLID as diagnostic heuristics, not scores:

- **SRP:** keep behavior that changes for the same reason together; split unrelated change reasons.
- **OCP:** introduce extension points only where demonstrated variation exists.
- **LSP:** preserve documented and observable contract expectations for substitutes.
- **ISP:** expose contracts shaped around consumers rather than oversized interfaces.
- **DIP:** keep important policy independent from replaceable infrastructure details.

Prefer high cohesion and low coupling. Make dependencies, side effects, state transitions, ownership, and failure modes explicit. Isolate I/O from deterministic policy where practical.

## Functions, comments, and errors

- Give each function one coherent intention; do not enforce arbitrary line limits.
- Name behavior and domain meaning, not implementation mechanics.
- Use guard clauses when they clarify exceptional paths and reduce nesting.
- Avoid boolean parameters that silently select unrelated behaviors; prefer explicit operations when the distinction matters.
- Avoid unexpected mutation, global mutable state, excessive parameter lists, and mixed abstraction levels.
- Let code explain what happens. Use comments to explain why, constraints, invariants, and non-obvious tradeoffs.
- Catch broad exceptions only at deliberate boundaries. Preserve causal context and do not silently discard failures.
- Avoid exposing internals to users or placing secrets and personal data in errors or logs.

## Changes and compatibility

Prefer local, conceptually complete, reversible changes. Avoid unrelated cleanup. Separate broad refactoring from behavior changes when feasible. Add regression coverage for fixed bugs and validate callers when changing a contract.

## Do not apply blindly

- Do not introduce an interface for every class.
- Do not extract every short function.
- Do not remove all duplication before understanding whether it is accidental or coincidental.
- Do not replace every conditional or switch with polymorphism.
- Do not add factories around trivial construction.
- Do not create speculative extension points or framework layers.
- Do not use Singleton as a default; prefer explicit composition and dependency ownership.
- Do not optimize without evidence.
- Do not chase arbitrary coverage percentages.
- Do not rewrite working code to match personal style.
- Do not hide a breaking change inside a refactor.


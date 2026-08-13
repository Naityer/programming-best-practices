# Testing and test quality

## Contents

1. Testing strategy
2. Behavior and structure
3. Coverage and mutation
4. Test oracles
5. Automatic generation
6. Stack matrix
7. Acceptance rules

## Testing strategy

Treat tests as production code. Test observable behavior and public contracts rather than private methods, call order, or implementation details. Use the lowest test level that gives the required confidence:

- Unit/component tests for deterministic behavior and boundaries.
- Integration tests for persistence, framework wiring, external adapters, and serialization.
- Contract tests for producer/consumer compatibility.
- A small number of E2E tests for critical journeys.

Use Arrange/Act/Assert or Given/When/Then. Cover happy paths, boundaries, invalid inputs, error paths, regressions, state transitions, authorization, concurrency-sensitive behavior, and cleanup.

If a simple unit is unusually hard to test, inspect coupling and hidden dependencies before building elaborate mocks.

## Coverage and mutation

Treat line coverage, branch coverage, and mutation score as different signals. Coverage proves execution, not assertion strength. Mutation testing asks whether tests detect plausible defects.

Respect project thresholds. When no threshold exists:

- Do not invent one.
- Identify critical uncovered branches and survived mutants.
- Explain risk by behavior, not percentage.
- Do not write trivial tests solely to raise coverage.

Run mutation testing only in DEEP or when explicitly requested because it is expensive. Scope it to changed or critical code before considering a full repository run.

## Test oracles

Every generated test must declare one oracle:

### Regression oracle

Derive the expected value from current observed behavior. Use to preserve behavior during refactoring. Do not claim it proves business correctness.

### Specification oracle

Derive assertions from a traceable requirement, OpenAPI contract, schema, invariant, docstring, existing acceptance test, or business rule. Record the source and exact rule. Prefer this oracle for correctness.

### Property oracle

Derive general invariants such as ordering, round-trip behavior, conservation, idempotence, monotonicity, bounds, or equivalence. Record the property and input domain.

Reject an assertion when its only justification is the current implementation but it is labeled as specification-backed.

## Automatic generation

Generate tests only after explicit user authorization. Automatic generators execute analyzed code and may trigger side effects.

1. Identify the target and oracle.
2. Prefer an isolated disposable container or sandbox without production credentials or network access.
3. If isolation is unavailable, ask before execution or generate tests without running them.
4. Inspect assertions semantically.
5. Run the generated tests.
6. Measure branch coverage where supported.
7. Use mutation testing to evaluate strength when the profile permits.
8. Remove flaky, redundant, environment-dependent, or implementation-coupled cases.

Never accept generated tests merely because they compile and pass.

## Stack matrix

| Stack | Runner | Coverage | Property testing | Mutation | Optional generation |
| --- | --- | --- | --- | --- | --- |
| Java/JVM | JUnit 5/TestNG | JaCoCo | jqwik/QuickTheories | PIT | Randoop, EvoSuite, UnitTestBot |
| Python | pytest/unittest | coverage.py/pytest-cov | Hypothesis | mutmut | Pynguin/UnitTestBot |
| JS/TS | Vitest/Jest/Mocha/node:test | native/Istanbul/c8 | fast-check | StrykerJS | UnitTestBot where supported |
| .NET | xUnit/NUnit/MSTest | Coverlet | FsCheck/Hedgehog | Stryker.NET | UnitTestBot where supported |
| Go | go test | go cover | testing/quick/rapid | go-mutesting/gremlins if configured | Prefer properties and fuzzing |
| Rust | cargo test | llvm-cov/tarpaulin | proptest/quickcheck | cargo-mutants | Prefer properties and fuzzing |
| C/C++ | GoogleTest/Catch2/CTest | llvm-cov/gcov | RapidCheck | mull where configured | UnitTestBot where supported |

Treat generators and mutation tools as optional. Do not install or execute them without approval.

## Acceptance rules

A useful test is deterministic, isolated at its intended boundary, behavior-focused, readable, and able to fail for the defect it protects against. For every bug fix, prefer a regression test that fails before the fix and passes after it. For refactoring, keep characterization tests clearly labeled when no specification oracle exists.


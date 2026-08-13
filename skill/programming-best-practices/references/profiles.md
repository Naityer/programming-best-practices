# Audit profiles

## Contents

1. Shared preflight
2. FAST
3. STANDARD
4. DEEP
5. Status model
6. Gates and completion

## Shared preflight

Read repository instructions and manifests, inspect Git status, detect stacks, locate existing quality configuration, and inventory available commands. Never install a missing tool during discovery.

Honor an explicit user scope. Otherwise use changed Git files when present and the full repository when clean. Exclude dependencies, generated code, vendored sources, caches, and build outputs unless relevant.

## FAST

Use during development and fix iteration. Target changed or affected code.

- Compile or type-check the relevant target.
- Run the native linter and formatter in check-only mode.
- Run affected unit/component tests.
- Run critical Semgrep rules and Gitleaks when already available and applicable.

FAST should complete quickly. If affected-test selection is unsupported, run the smallest reliable test target rather than guessing.

## STANDARD

Use by default for an audit or important change.

Include FAST plus:

- complete relevant test suite;
- branch coverage when supported;
- configured static analysis and duplication checks;
- dependency vulnerability checks;
- architecture tests;
- SonarQube/SonarScanner only when already configured or explicitly approved.

Do not silently broaden a user-limited scope. Explain when a tool inherently scans the repository.

## DEEP

Use only when explicitly requested.

Include STANDARD plus:

- scoped mutation testing, then broader mutation only if justified;
- Trivy filesystem/configuration/license scanning;
- full-repository dependency and secret analysis;
- complexity, duplication, cycle, architecture, dead-code, and hotspot review;
- semantic design and security review;
- authorized test generation and differential testing where suitable.

Estimate cost before long-running scans. Ask before downloads, containers, network access, or generated-code execution.

## Status model

Record every planned tool as one of:

- `passed`: completed and its configured gate passed;
- `findings`: completed and reported issues;
- `failed`: tool or build failed before producing trustworthy results;
- `timed_out`: exceeded the agreed limit;
- `skipped`: intentionally excluded with a reason;
- `unavailable`: required executable/configuration is missing.

Only `passed` means that check passed. Never convert the other states to success.

## Gates and completion

Respect gates already defined by the repository or explicitly supplied by the user. Without gates, do not fail arbitrary coverage, complexity, or mutation percentages. Objective blockers may make the audit outcome `fail`; incomplete tools make it `incomplete`, not `pass`.

Report:

- configured gates and results;
- dimensions and raw metrics without an overall score;
- blockers independently of metrics;
- limitations and unavailable evidence;
- exact commands run.


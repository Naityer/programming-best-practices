# Tooling matrix

## Contents

1. Selection rules
2. Universal tools
3. Java/JVM
4. Python
5. JavaScript/TypeScript
6. .NET
7. Go
8. Rust
9. C/C++
10. Installation policy

## Selection rules

Prefer the repository's wrapper and configuration: `mvnw`/Gradle Wrapper, project virtual environment, package-manager lockfile, `dotnet`, `go`, `cargo`, or CMake presets. Treat the commands below as candidates; inspect manifests before executing them. Never run a formatter in write mode during audit.

Capture tool version, command, exit code, duration, scope, status, and report path. Use JSON, XML, or SARIF output when available. Do not infer a pass from missing output.

## Universal tools

| Purpose | Preferred tools | Notes |
| --- | --- | --- |
| Multi-language aggregation | SonarQube Community Build/SonarScanner | Use only when configured or approved; coverage is imported |
| AST rules/SAST | Semgrep CE | Prefer pinned/configured rules; note CE analysis limits |
| Duplication | PMD CPD or configured equivalent | Interpret duplicated tokens in context |
| Dependencies | OSV-Scanner | Prefer lockfiles/resolved graphs |
| Secrets | Gitleaks | History scanning can be expensive and needs scope awareness |
| Filesystem/config/security | Trivy | DEEP unless repository already requires it |
| Semantic security | CodeQL | Optional when available and licensed for the repository |
| Design-pattern detection | Internal design-pattern analyzer (`analyze_design_patterns.py`) | Quality; STANDARD/DEEP; see [design-patterns/detection-rules.md](design-patterns/detection-rules.md) |
| Pattern misuse | Internal design-pattern analyzer | Quality; STANDARD/DEEP; structural evidence only, never name-based |
| Pattern refactoring opportunities | Internal design-pattern analyzer + semantic review | Quality; STANDARD/DEEP; needs no network, modifies nothing in the repository |

## Java/JVM

Detect `pom.xml`, `mvnw*`, `build.gradle*`, `gradlew*`.

- Build/test: `./mvnw test`, `./gradlew test`, or repository tasks.
- Static analysis: configured compiler checks, PMD, SpotBugs, Checkstyle, Error Prone, Semgrep, Sonar.
- Coverage: JaCoCo report through Maven/Gradle.
- Mutation: PIT through the configured plugin; never invent plugin versions in the project.
- Architecture: ArchUnit tests.
- Generation: Randoop/UnitTestBot; EvoSuite only when compatible and explicitly selected.

## Python

Detect `pyproject.toml`, `setup.cfg`, `tox.ini`, `pytest.ini`, requirements and lockfiles.

- Tests: `python -m pytest` or the configured runner.
- Lint/format check: `ruff check .`, `ruff format --check .`, or configured alternatives.
- Types: mypy, pyright, or repository command.
- Coverage: `coverage run -m pytest` plus `coverage report`, or pytest-cov.
- Mutation: `mutmut run` with a constrained target.
- Properties: Hypothesis.
- Generation: Pynguin only inside isolation; it executes imported code.

## JavaScript/TypeScript

Detect `package.json` and lockfiles. Use the matching package manager and declared scripts; do not mix npm, pnpm, Yarn, or Bun.

- Tests: configured Vitest, Jest, Mocha, node:test, or package script.
- Lint: configured ESLint command.
- Types/build: `tsc --noEmit` or package script.
- Coverage: native runner coverage, c8, or Istanbul.
- Mutation: StrykerJS through the project's configuration.
- Properties: fast-check.
- Generation: UnitTestBot only where its current support matches the project.

## .NET

Detect `*.sln`, `*.csproj`, `*.fsproj`, `global.json`.

- Build/test: `dotnet build` and `dotnet test` with repository options.
- Analysis: compiler analyzers, StyleCop/Roslyn analyzers, Semgrep, Sonar.
- Coverage: Coverlet through configured collector/package.
- Mutation: Stryker.NET.
- Properties: FsCheck or Hedgehog.
- Architecture: existing architecture tests or NetArchTest where configured.

## Go

Detect `go.mod`, `go.work`.

- Format check: compare `gofmt -l` output; do not rewrite in audit.
- Build/test: `go test ./...`; add `-race` when cost and platform permit.
- Static analysis: `go vet ./...`, Staticcheck if configured.
- Coverage: `go test -coverprofile=cover.out ./...` and `go tool cover`.
- Fuzz/property: native fuzzing, `testing/quick`, or rapid.
- Mutation: optional configured tool such as gremlins; do not make it a base dependency.

## Rust

Detect `Cargo.toml`, `Cargo.lock`.

- Format check: `cargo fmt --check`.
- Build/test: `cargo check --all-targets`, `cargo test`.
- Static analysis: `cargo clippy --all-targets -- -D warnings` only when repository policy treats warnings as errors; otherwise omit `-D warnings`.
- Coverage: cargo-llvm-cov or tarpaulin when configured.
- Mutation: cargo-mutants.
- Properties: proptest or quickcheck.
- Security: cargo-audit/cargo-deny or OSV-Scanner as configured.

## C/C++

Detect `CMakeLists.txt`, `CMakePresets.json`, Meson files, Makefiles, and compile databases.

- Build/test: CMake presets and CTest, Meson test, or repository commands.
- Static analysis: clang-tidy with the correct compilation database; configured compiler warnings.
- Coverage: llvm-cov or gcov matching the compiler toolchain.
- Tests: GoogleTest, Catch2, CTest, or repository harness.
- Properties: RapidCheck when configured.
- Mutation: Mull when configured and compatible.
- Generation: UnitTestBot only in an isolated compatible environment.

## Installation policy

When a needed tool is unavailable:

1. Mark it `unavailable`; continue with independent checks.
2. Explain why the selected profile needs it and the expected cost/side effects.
3. Verify current official documentation and compatibility with the detected OS, runtime, build system, and license.
4. Show the exact command, download, container, configuration files, and network access involved.
5. Request explicit approval.
6. Install only that tool and verify its version.
7. Do not edit project configuration merely to make a tool run unless separately authorized.
8. Never install every tool in this matrix preemptively.


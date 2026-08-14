---
name: programming-best-practices
description: Audit and improve software correctness, maintainability, readability, test quality, architecture, dependencies, security, and performance using repository-native conventions and instrumented evidence. Use for code-quality audits, code reviews, refactoring requests, best-practice checks, test generation or evaluation, coverage and mutation analysis, security review, performance audits and optimization work (profiling, benchmarking, bundle size, regression against a recorded baseline), static-analysis orchestration, and requests to fix quality findings across Java/JVM, Python, JavaScript/TypeScript, .NET, Go, Rust, or C/C++ repositories.
---

# Programming Best Practices

## Operating contract

Treat audit and mutation as separate modes.

- Default to **audit mode**. Read, inspect, execute non-mutating checks, and report findings. Do not edit source code, tests, configuration, or dependencies.
- Enter **fix mode** only when the user explicitly asks to change, refactor, fix, or generate code. Keep the smallest behavior-preserving diff unless the requested behavior must change.
- Generate tests only when explicitly requested. Label their oracle as `regression`, `specification`, or `property`.
- Install tools, download analyzers, start containers, or execute generated/untrusted code only after explicit approval. Request approval for the concrete tool and command, not for a generic toolchain.
- Never commit, push, publish, open a pull request, or change remote resources unless explicitly requested.
- Preserve unrelated working-tree changes. Review the final diff in fix mode.

Prefer this ordering:

`correctness > security > behavior > simplicity > readability > maintainability > hypothetical extensibility > cosmetics`

Use instrumented evidence before heuristic opinion. Treat unavailable, skipped, timed-out, and failed tools as incomplete evidence, never as a pass. Do not produce a universal quality score or invent thresholds.

## Workflow

1. **Discover and plan.** Read repository instructions, then run `python scripts/plan_audit.py --root <repo> --profile <profile> --output <temporary>/plan.json`. Inspect every command, working directory, timeout, missing tool, and authorization boundary.
2. **Select scope.** Honor the user's scope. Otherwise inspect changed Git files when present; fall back to the repository. Verify each planned check's effective_scope; repository-wide suites must say so even when analyzers are limited to changed files. Exclude generated, vendored, cache, dependency, and build-output directories unless the request targets them.
3. **Select profile.** Use STANDARD by default, FAST while iterating on a fix, and DEEP only when explicitly requested. Read [profiles.md](references/profiles.md).
4. **Load only relevant guidance.** Read the references routed below for the detected stack and requested work.
5. **Execute safely.** Run `python scripts/run_audit.py <plan.json> --output-dir <temporary>/execution --execute`. Add `--allow-project-writes`, `--allow-network`, or `--allow-generated-code` only when each capability was explicitly authorized.
6. **Normalize evidence.** Use `normalize_tool_output.py` for supported external reports. Preserve raw output outside the target repository and redact secrets from canonical artifacts.
7. **Review semantically.** Inspect context around findings. Write explicit confirm or dismiss decisions with reasons and pass them through --semantic-review when building the final report. Reject false positives, identify uncovered correctness risks, and distinguish observable problems from stylistic preference.
8. **Prioritize.** Use `blocker`, `high`, `medium`, or `low` severity and independent `high`, `medium`, or `low` confidence. Prefer tool or specification evidence over LLM inference.
9. **Fix only when authorized.** Make local, reviewable changes; add behavior-focused tests; run the narrow checks first and the relevant broader checks afterward.
10. **Build and render.** Run `python scripts/build_report.py <execution.json> --output-dir <new-directory>`, adding semantic findings or external fragments when applicable. Produce Markdown, normalized JSON, and SARIF without overwriting previous results.

## Reference routing

- Read [core-principles.md](references/core-principles.md) for priorities, conventions, SOLID, comments, errors, and anti-overengineering rules.
- Read [code-quality.md](references/code-quality.md) when assessing smells, refactorings, coupling, cohesion, or design patterns.
- Read [testing.md](references/testing.md) for test levels, coverage, mutation testing, test generation, and oracle classification.
- Read [security.md](references/security.md) for untrusted input, authorization, secrets, dependencies, logging, files, URLs, concurrency, or sensitive data.
- Read [performance.md](references/performance.md) when the request is about speed, latency, memory, bundle size, profiling, benchmarking, or a performance regression.
- Read [profiles.md](references/profiles.md) before choosing checks or interpreting partial execution.
- Read [automation.md](references/automation.md) before planning, executing, normalizing, installing tools, or generating tests.
- Read [tooling-matrix.md](references/tooling-matrix.md) for stack-specific commands and optional analyzers.
- Read [reporting.md](references/reporting.md) before producing or merging findings. Validate against [audit-result.schema.json](references/audit-result.schema.json).

## Review rules

- Report only actionable findings with a concrete impact. Omit personal preferences already handled by formatters.
- Cite precise files and lines. Explain why the current behavior is risky and what minimal remediation resolves it.
- Keep severity separate from confidence. A severe hypothesis with weak evidence remains low confidence.
- Deduplicate tool findings that share a root cause. Retain the strongest evidence and list corroborating sources.
- Treat a hardcoded credential, exploitable authorization bypass, likely data corruption, severe race, or accidental breaking API as a blocker when supported by evidence.
- Treat coverage as a signal. Respect repository gates; without configured gates, report uncovered risk rather than failing arbitrary percentages.
- Treat performance the same way: compare against the repository's recorded baseline, never an invented budget. Without a baseline, report the measurements and state that no verdict is possible.
- Do not recommend a pattern, interface, factory, abstraction, or rewrite without a concrete recurring problem it simplifies.
- In audit mode, end with findings ordered by severity, then open questions/limitations, validation performed, and artifact paths.
- When no findings remain, state what was checked and what could not be checked. Never claim the codebase is fully safe or correct.



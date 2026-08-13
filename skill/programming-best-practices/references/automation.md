# Automated audit workflow

## Contents

1. Plan
2. Review authorization boundaries
3. Execute
4. Normalize and render
5. Test-generation pipeline
6. Installation
7. Failure handling

## Plan

Generate a deterministic plan with:

    python scripts/plan_audit.py --root <repo> --profile standard --output <temporary>/plan.json

Inspect every check's argv, cwd, required, gate, effective_scope, workspace_effects, network, generated_code, timeout, output format, and reason. Planning never installs a tool. Missing tools remain unavailable.

Use an output path outside the audited repository when strict read-only operation is required.

## Review authorization boundaries

Execution requires --execute. Add only separately authorized capabilities:

- --allow-project-writes permits tests/builds that may create caches or runtime artifacts.
- --allow-network permits vulnerability databases, remote Sonar, or other networked checks.
- --allow-generated-code permits execution of generated/untrusted tests.

Do not infer one permission from another. Test generation does not imply network permission; an audit does not imply project writes.

## Execute

    python scripts/run_audit.py <plan.json> --output-dir <temporary>/execution --execute

The runner never invokes a shell; accepts only detected executables; confines each cwd to the repository; requires output outside the repository; enforces timeouts and dependencies; captures stdout/stderr; and explicitly skips unauthorized capabilities.

For normal project tests/builds, review and add --allow-project-writes. For strict read-only validation, omit it; those checks become skipped.

## Normalize and render

Supported adapters: Semgrep, Gitleaks, Ruff JSON, OSV-Scanner, Trivy, coverage.py, JaCoCo, Cobertura, LCOV, Go coverage profiles, LLVM coverage JSON, PIT, mutmut, Stryker, and cargo-mutants.

Normalize an external report when needed:

    python scripts/normalize_tool_output.py --tool semgrep --input semgrep.json --root <repo> --output fragment.json

Build the final report; known runner outputs are normalized automatically:

    python scripts/build_report.py <execution.json> --fragment <optional-fragment.json> --semantic-findings <optional-findings.json> --semantic-review <optional-review.json> --output-dir <new-output-directory>

The builder derives tool status from parsed output, merges dimensions, evaluates configured gates, applies semantic confirmations or dismissals, generates stable IDs and fingerprints, and renders Markdown, JSON, and SARIF. A semantic review contains a decisions array; match by fingerprint or by rule_id, file and line, use action confirm or dismiss, require a reason, and allow confirm overrides only for title, severity, confidence, impact, or recommendation. It never overwrites an existing output directory.

## Test-generation pipeline

Plan before generating:

    python scripts/plan_test_pipeline.py --root <repo> --target <module-or-class> --oracle-type specification --oracle-source requirements.md

The pipeline includes four gates:

1. Generate into an isolated artifact directory.
2. Review assertions semantically and verify the declared oracle.
3. Copy only approved tests when code changes were authorized.
4. Run native tests, branch coverage, and mutation checks.

Regression oracles preserve observed behavior but do not prove correctness. Specification oracles require a traceable source. Property oracles require an explicit invariant. Pynguin and other generators execute target code; use isolation without production credentials.

## Installation

Do not implement a universal installer. When a selected check is unavailable:

1. Keep it unavailable.
2. Verify its current official documentation, compatibility, license, download, configuration, and network effects.
3. Show the exact command and files affected.
4. Request approval for that tool only.
5. Install and verify its version.
6. Regenerate the plan.

The repository's tools/install_skill.py installs only this skill, not third-party analyzers.

## Failure handling

- A supported non-zero finding exit is findings.
- Startup/configuration errors are failed.
- Expired checks are timed_out.
- Missing commands are unavailable.
- Policy exclusions are skipped.
- A failed prerequisite skips dependent checks.
- Required incomplete checks make the audit incomplete; supported blockers or failed configured gates make it fail. Completed configured gates can produce pass; otherwise the outcome is informational.


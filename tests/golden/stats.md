# Statistics: stats-history

- Root: `<root>`
- Generated: 2026-08-14T17:00:00Z
- Source runs considered: 2

## Current run

- Run: `.quality-audit/20260805T090000Z`
- Generated: 2026-08-05T09:00:00Z
- Profile: standard · Scope: repository · Outcome: **informational**

| Severity | Count |
|---|---|
| blocker | 0 |
| high | 1 |
| medium | 0 |
| low | 0 |

## Review — confirm/dismiss ratios

No single reliability score is produced; each ratio above is reported with its raw confirmed/dismissed counts and a 95% Wilson confidence interval. Ratios below the minimum sample size are null with sample_size_warning=true rather than a misleading 100%/0%.

| Group | Reviewed | Confirmed | Dismissed | Confirmation rate (95% CI) | False-positive / hallucination rate (95% CI) |
|---|---|---|---|---|---|
| Tool-sourced findings | 1 | 1 | 0 | 100.0% (20.6%–100.0%) | 0.0% (0.0%–79.3%) |
| Agent LLM-only findings | 0 | 0 | 0 | insufficient sample | insufficient sample |

Runs with a review ledger: 1 / 2. Unreviewed findings in the considered scope: 0.

## By tool

| Tool | Runs seen | Findings | Reviewed | Confirmation rate | Avg duration (ms) | Measures |
|---|---|---|---|---|---|---|
| universal.semgrep (semgrep) | 2 | 2 | 1 | 100.0% (20.6%–100.0%) | 110 | Static pattern rules matched against source files in the configured ruleset. |

## Trends

| Metric | n | Mean | Stdev | Slope/day | Direction |
|---|---|---|---|---|---|
| finding_counts.blocker | 2 | 0 | 0 | 0 | insufficient_data |
| finding_counts.high | 2 | 1 | 0 | 0 | insufficient_data |
| finding_counts.low | 2 | 0 | 0 | 0 | insufficient_data |
| finding_counts.medium | 2 | 0 | 0 | 0 | insufficient_data |
| dimensions.coverage.line_percent | 2 | 64 | 5.6569 | 2 | insufficient_data |

## Anomalies

None detected.

## Limitations

- 1 of 2 runs have no review-ledger.json; their findings are excluded from review ratios.
- No plan.json supplied; per-tool codebase coverage is not computable.

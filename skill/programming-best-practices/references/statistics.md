# Statistics

## Contents

1. What this answers that a single audit cannot
2. Artifacts
3. The review ledger
4. Statistical design
5. Reading the review ratios
6. Limits — what stays uncomputed on purpose

## What this answers that a single audit cannot

`report.json` answers "what is true right now." `build_stats.py` reads the
run history that `.quality-audit/<timestamp>/` already accumulates on disk —
one directory per prior `build_report.py` run — and answers questions that
need more than one point: which tools' findings hold up under review, how a
metric is moving, and where two runs disagree. It never executes a tool and
never re-scans source; it only reads artifacts that already exist.

Run it after at least one report exists:

```
python scripts/build_stats.py --root <repo> --output-dir <new-directory>
```

Add `--plan <plan.json>` (from `plan_audit.py`) to get a real per-tool
codebase-coverage denominator; without it, `coverage_of_codebase.computable`
is `false` with a reason, never a guessed percentage. Add `--emit-svg` to
also write each chart as a standalone `charts/*.svg` file.

## Artifacts

Written to a new `<repo>/.quality-audit-stats/<timestamp>/` directory —
deliberately a sibling of `.quality-audit/`, not nested inside it, so future
history discovery (`glob(".quality-audit/*/report.json")`) never mistakes the
aggregator's own output for an audit run:

- `stats.json`: the canonical, versioned artifact. This is what a future UI
  should consume — `stats.md`/`stats.html` are a presentation layer built
  directly from it, not a second source of truth.
- `stats.md`, `stats.html`: human-readable renderings, the second with inline
  SVG bar/line charts and a tool × review-outcome contingency table. Fully
  self-contained — no CDN, no external fetch — so it renders offline.
- `charts/*.svg` (with `--emit-svg`): the same charts as standalone files.

Validate `stats.json` against
[stats-result.schema.json](stats-result.schema.json) before trusting it in
automation.

## The review ledger

`build_report.py` writes `review-ledger.json` next to `report.json`,
**only** when `--semantic-review` was supplied, even with zero decisions —
the absence of the file and an empty `decisions` array mean different things
to `build_stats.py`. It records every confirm/dismiss decision with a
snapshot of the finding *as it stood at the moment of the decision*
(fingerprint, category, severity, confidence, and — critically —
`evidence_source_types`, captured before `confirm` appends its own `llm`
evidence item). Validate it against
[review-ledger.schema.json](review-ledger.schema.json).

This is what makes "how many tool findings were validated true" answerable
at all: `_apply_review()` used to drop dismissed findings with only a
one-line prose note, and confirmations left no queryable trail. Without the
ledger, none of the review ratios below are computable — they come back
`null` with a `limitations` entry naming exactly that, they are never
guessed from what the report happens to still contain.

## Statistical design

Every number below either answers a stated question with a stated method, or
comes back `null` with a reason. None of it is a synthesized quality score —
that is the same rule `SKILL.md` states for audits, applied here.

**Series and trend (`trends.finding_counts.*`, `trends.dimensions.*`).**
Mean and sample standard deviation (`n-1`) over the runs where the metric is
present; `stdev` is `null` below `n=2`, never `0.0` — a single point has no
defined variance. `direction` compares an ordinary-least-squares slope
(value vs. days since the first run, not run index, so irregular audit
cadence doesn't distort it) against its own standard error — a standard
significance check, not an invented percentage threshold:

| Condition | `direction` |
| --- | --- |
| `n < 3` | `insufficient_data` |
| `\|slope\| ≤ standard_error(slope)` | `not_distinguishable_from_noise` |
| significant, but the metric has no registered polarity | `unknown_polarity` |
| significant, slope moves the metric the *good* way | `improving` |
| significant, slope moves the metric the *bad* way | `worsening` |

Polarity ("is higher better?") is a small hand-curated table in
`build_stats.py` (`METRIC_POLARITY`) — `coverage.*_percent` and
`mutation.score_percent` are higher-is-better, `finding_counts.*` and
`mutation.survived` are lower-is-better. A metric absent from that table
reports its raw slope with `unknown_polarity` rather than a guess.

**Review ratios (`review.*`, `by_tool.*.review`).** Confirmation rate and
false-positive rate from ledger decisions, each with a raw
`confirmed`/`dismissed`/`reviewed` count and a **95% Wilson confidence
interval** — more reliable than a normal approximation at the small sample
sizes typical of a project that just started using this skill, and it can't
report a nonsensical value outside `[0, 1]`. Below `--min-sample` (default
5) reviewed decisions, both the rate and its interval are `null` with
`sample_size_warning: true`, so a 1-of-1 decision never reads the same as a
40-of-50 one.

**Duration (`by_tool.*.avg_duration_ms`, `.duration_ms_stddev`).** Mean and
stdev of `duration_ms` across runs where the check actually executed
(`skipped`/`unavailable` runs are excluded, they would bias the mean toward
zero for reasons unrelated to the tool's real cost). This tracks audit cost
over time, not code quality — a rising mean or a widening stdev means the
check itself deserves attention (timeout tuning, flakiness), not the
repository.

**Findings-by-tool / severity bar charts and the tool × review-outcome
table.** Plain counts, rendered as inline SVG (`render_stats.py`) with no
third-party charting library, so the output stays dependency-free and works
offline in any audited repository.

## Reading the review ratios

`review.tool_findings` and `review.agent_llm_only_findings` answer two
different questions and are reported separately, on purpose:

- **`tool_findings.false_positive_rate`** — of tool-sourced findings that
  were reviewed, how many were judged wrong. This is the classic
  static-analysis false-positive rate.
- **`agent_llm_only_findings.false_positive_rate`** — read this one as the
  **agent hallucination rate**: of findings whose evidence was *exclusively*
  `source_type: "llm"` (no tool, specification, or property backing) at the
  moment of review, how many were dismissed as unsupported.

A finding with mixed `tool` + `llm` evidence counts toward the first group,
never the second — it had real backing, so dismissing it says something
about the tool, not about an unsupported agent claim.

`review.note` restates in the artifact itself why there is no single
"reliability" figure: blending these two failure modes into one number would
hide which one to actually go fix, and `SKILL.md` already prohibits
synthesizing a universal score from evidence like this.

## Limits — what stays uncomputed on purpose

- **Not a confusion matrix.** The tool × review-outcome table has only two
  of the four classic cells: confirmed (true-positive-like) and dismissed
  (false-positive-like). Nothing here observes issues a tool never flagged,
  so there is no true-negative or false-negative count — showing one would
  fabricate data the audit never collected. `render_stats.py` captions the
  table as a contingency table, explicitly, every time.
- **No chi-square test** between tool and review outcome. Typical review
  history (tens of decisions, not thousands) doesn't give that test honest
  power, so it is not offered rather than offered misleadingly.
- **`coverage_of_codebase` per tool** requires `--plan`; without it, it is
  `{"computable": false, "reason": "requires --plan; not supplied"}`, never
  a percentage backed by nothing.
- **`measurement_domain`** is a hand-curated registry keyed by
  `output_format` (what a check actually measures — several checks in one
  ecosystem share a generic executable name like `go`, `cargo`, `dotnet`, so
  the executable itself is not a reliable key). A tool absent from the
  registry gets `null` and a `limitations` entry, never a guessed
  description.
- **No multi-repository rollup.** `stats.json` is scoped to one repository
  (`repository`/`root` fields make that explicit); a fleet-level view
  aggregates multiple `stats.json` files itself. This skill stays
  stack-agnostic and does not assume a fleet topology.

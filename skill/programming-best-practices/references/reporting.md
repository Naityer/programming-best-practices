# Reporting contract

## Contents

1. Artifacts
2. Canonical model
3. Finding rules
4. Tool runs
5. Outcome
6. SARIF mapping
7. Secret handling

## Artifacts

Write each run to a new `.quality-audit/<timestamp>/` directory:

- `report.json`: normalized canonical result;
- `report.md`: human-readable report;
- `report.sarif`: SARIF 2.1.0 for code-scanning consumers.

Do not overwrite a prior run or edit `.gitignore` automatically. Validate the input against `audit-result.schema.json` before rendering.

## Canonical model

Use `schema_version: "1.0.0"` and provide:

- `audit`: repository, profile, scope, mode, generated time, and outcome;
- `summary`: counts and optional raw metrics by dimension, without a global score;
- `tools`: every planned/executed check and its explicit status;
- `findings`: actionable results;
- `limitations`: missing evidence, unsupported analysis, and constraints.

## Finding rules

Each finding requires:

- stable `id` and `fingerprint`;
- `rule_id`, `title`, `category`;
- independent `severity` and `confidence`;
- at least one location;
- at least one evidence item;
- concrete `impact` and `recommendation`.

An evidence item uses `source_type: tool|specification|property|llm`, names its source, and includes a concise message. Tool evidence may include metric/value. Specification evidence includes a traceable source. Never label observed implementation output as specification evidence.

Apply documented semantic `confirm|dismiss` decisions before rendering. Record dismissals as limitations with their reasons. Deduplicate retained findings by fingerprint. Preserve corroborating evidence and prefer evidence in this order: tool, specification/property, LLM. Do not discard distinct vulnerable flows merely because they share a rule.

## Tool runs

Use `passed|findings|failed|timed_out|skipped|unavailable`. Include command, version, configured-gate flag, and effective scope when known. Derive `findings` from parsed output when a tool returns zero despite reporting issues. Include exit code and duration when executed. A missing tool is `unavailable`, not `passed`.

## Outcome

Use:

- `fail` when supported blockers exist or an explicit repository gate fails;
- `incomplete` when required evidence failed, timed out, or was unavailable;
- `pass` when configured gates pass, no blocker exists, and required evidence completed;
- `informational` when no applicable gate exists and the report only characterizes risk.

Without configured gates, do not transform percentages into a failure. A blocker can still produce `fail`.

## SARIF mapping

Map severity to SARIF level:

- blocker/high → `error`
- medium → `warning`
- low → `note`

Use `rule_id` as the SARIF rule identifier, `fingerprint` in `partialFingerprints`, and store confidence, category, impact, evidence sources, and recommendation in properties. Use repository-relative forward-slash URIs.

## Secret handling

Never include raw detected credentials. Redact token-like values from titles, messages, commands, and evidence. Preserve only type, location, detector, and a non-secret fingerprint. Keep raw scanner output out of distributable reports when it may contain sensitive material.


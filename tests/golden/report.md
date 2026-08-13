# Code quality audit

- Repository: `golden-sample`
- Profile: **STANDARD**
- Scope: `src/app.py`
- Mode: `audit`
- Outcome: **INFORMATIONAL**
- Generated: 2026-08-13T12:00:00Z

## Summary

| Blocker | High | Medium | Low |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 1 | 0 |

### Dimensions

- coverage: {"branch": 72}

## Findings

### [MEDIUM] Boundary behavior is not asserted

- Rule: `testing.boundary`
- Category: `test-quality`
- Confidence: `high`
- Location: `src/app.py:10`
- Fingerprint: `golden-fingerprint`

Impact: A comparison mutation can change behavior at the eligibility boundary.

Recommendation: Add specification-backed tests for ages 64 and 65.

Evidence:

- **specification / requirements.md**: Age 65 is included in the discount rule.

Oracle: `specification` — requirements.md

## Tool execution

| Tool | Status | Gate | Effective scope | Version | Command/reason |
| --- | --- | --- | --- | --- | --- |
| mutmut | unavailable | false | repository |  | `not installed` |
| pytest | passed | false | repository | 8.0 | `python -m pytest` |

## Limitations

- Mutation testing was unavailable.

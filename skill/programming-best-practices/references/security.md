# Security review

## Contents

1. Threat boundaries
2. Required checks
3. Secrets and sensitive data
4. Dependencies and supply chain
5. Logging and errors
6. Severity and evidence
7. Safe execution

## Threat boundaries

Identify untrusted input, identities, authorization decisions, trust transitions, persistence, file and network access, process execution, deserialization, cryptography, concurrency, and external integrations. Review only relevant controls, but never skip an applicable boundary because the task is described as refactoring.

## Required checks

Inspect for:

- injection into SQL, shells, templates, interpreters, paths, logs, and headers;
- missing or object-level authorization and confused-deputy flows;
- authentication/session weaknesses and unsafe defaults;
- path traversal, unsafe archive extraction, symbolic-link attacks, and permissive file access;
- unsafe deserialization, parser bombs, and unbounded resource consumption;
- SSRF, redirect abuse, missing URL allowlists, and missing network timeouts;
- cryptographic misuse, weak randomness, hardcoded keys, and home-grown protocols;
- error disclosure and fail-open behavior;
- races, check-then-act bugs, lost updates, and non-atomic security decisions;
- sensitive data retention, overexposure, insecure transport, and missing deletion controls.

Validate inputs positively against expected type, range, length, structure, and business invariants. Validation is not a substitute for parameterization, escaping at the correct sink, or authorization.

## Secrets and sensitive data

Treat a credible live credential in source, configuration, build artifacts, or Git history as a blocker. Do not reproduce the secret in reports. Record only type, location, detector, and a redacted fingerprint. Recommend revocation/rotation in addition to code removal.

Use Gitleaks or an existing repository scanner when available. Do not scan history if the user restricts the scope or the repository is exceptionally large without explaining the cost.

Never send private code, secrets, or dependency manifests to an external service without authorization.

## Dependencies and supply chain

Prefer lockfiles and resolved dependency graphs. Use OSV-Scanner by default when available; use ecosystem-native audits, Trivy, or OWASP Dependency-Check when the stack or existing configuration warrants them. Record database freshness and tool version where available.

A vulnerability match is evidence, not automatic exploitability. Review reachability, affected component, deployment context, fix version, and compensating controls. Do not downgrade a known exploitable issue merely because no public exploit was observed locally.

## Logging and errors

Preserve diagnostic context while avoiding credentials, tokens, session identifiers, personal data, payment data, and cryptographic material. Log security-relevant events with stable identifiers and enough metadata for reconstruction. Do not expose stack traces, queries, paths, or internal topology to untrusted clients.

Catch broad errors only at a boundary that maps, logs, retries, rolls back, or terminates them deliberately.

## Severity and evidence

Use blocker for supported findings that enable direct authorization bypass, credential compromise, severe data loss/corruption, or remote code execution in the deployment context. Use high for realistically exploitable significant impact, medium for constrained impact or important defense gaps, and low for hardening with limited direct impact.

Keep confidence independent. Tool matches require contextual confirmation; semantic findings require a concrete path from source to sink or violated security invariant.

## Safe execution

Static inspection is preferred. Ask before installing scanners, updating vulnerability databases, starting containers, accessing networks, scanning Git history, or executing untrusted/generated code. Use a disposable environment with least privilege and no production credentials for dynamic checks.


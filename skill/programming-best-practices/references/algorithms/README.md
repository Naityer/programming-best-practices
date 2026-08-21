# Algorithm Intelligence

Use `scripts/analyze_algorithms.py` for static, offline analysis without importing or executing the audited project.

Profiles:

- `FAST` omits Algorithm Intelligence.
- `STANDARD` builds local IR and follows direct local callees.
- `DEEP` follows a bounded three-hop local call graph and retains conservative unknowns.

The artifact contains occurrences plus `analysis`: Universal/Algorithmic IR, simplified CFG/DFG, operation indexes, complexity summaries and external-cache evidence. Python uses `ast`; JVM, JS/TS, .NET, Go, Rust and C/C++ use the pinned Tree-sitter runtime in `tree-sitter-runtime.json`. Missing grammars degrade to low-confidence evidence and never authorize `SAFE` corrections.

```text
python scripts/analyze_algorithms.py \
  --root <repository> \
  --output <artifact-dir>/algorithms.json \
  --profile standard
```

Optional `--profiling-evidence` and `--security-evidence` inputs are local JSON facts. Profiling can strengthen evidence but never grants write permission. A complexity issue becomes `security-risk` only when authorized evidence proves both external control and attack amplification.

Selection order is fixed: facts → Problem Signature → hard requirements → counterevidence → alternative competition → contextual ranking. Big-O alone is insufficient. A hard `UNKNOWN` or `CONTRADICTED` requirement prevents `SAFE`.

The canonical knowledge source is `catalog.json`; `catalog-case-contracts.json` supplies positive, negative, misuse, alternative and edge contracts for every entry. The catalog stores knowledge and library mappings, never copyable algorithm or cryptographic implementations.


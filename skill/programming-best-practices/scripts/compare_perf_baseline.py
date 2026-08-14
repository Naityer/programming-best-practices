#!/usr/bin/env python3
"""Compare performance measurements against a recorded baseline.

    python scripts/compare_perf_baseline.py current.json --baseline .perf-baseline.json \
        --tolerance 0.10 --output fragment.json

Turns two measurement documents into canonical findings, so a performance
regression travels through the same pipeline as any other finding.

**Why comparison and not budgets.** `SKILL.md` forbids inventing thresholds, and
performance tooling is where that rule is broken most often: a bundle budget of
"250 KB" or a "p95 under 200 ms" pulled from nowhere fails builds without
anybody having agreed to the number. A baseline is different — it is the
project's own previously measured behaviour, committed to the repository. The
only claim made here is *this got slower than it was*, which is a fact about the
repository rather than an opinion about it.

Absent a baseline the tool reports the measurements and says so. That is
`incomplete` evidence, never a pass.

Input documents are flat or nested JSON of numbers; every numeric leaf is
compared by its dotted path, so it works for `bundle-size` output, benchmark
JSON, or a hand-rolled probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

# Claves cuyo aumento es una MEJORA, no una regresión (aciertos de caché,
# rendimiento en operaciones por segundo, cobertura...). Se comparan invertidas.
HIGHER_IS_BETTER = ("ops_per_second", "ops", "throughput", "hit_rate", "percent_covered", "fps")

# Ruido: identificadores y contadores que no son medidas de rendimiento.
IGNORED_LEAVES = ("schema_version", "file_count", "count")


def _numeric_leaves(node: Any, prefix: str = "") -> Iterator[tuple[str, float]]:
    """Todo número del documento, indexado por su ruta con puntos."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numeric_leaves(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _numeric_leaves(value, f"{prefix}[{index}]")
    elif isinstance(node, bool):
        return          # `bool` es subclase de `int`: no es una medida
    elif isinstance(node, (int, float)):
        yield prefix, float(node)


def _higher_is_better(path: str) -> bool:
    tail = path.rsplit(".", 1)[-1].lower()
    return any(token in tail for token in HIGHER_IS_BETTER)


def _severity(ratio: float) -> str:
    """Cuánto peor, en severidad. Escala declarada aquí y en ningún otro sitio."""
    if ratio >= 2.0:
        return "high"
    if ratio >= 1.5:
        return "medium"
    return "low"


def compare(current: dict[str, Any], baseline: dict[str, Any], tolerance: float) -> dict[str, Any]:
    base_values = dict(_numeric_leaves(baseline))
    findings: list[dict[str, Any]] = []
    regressions: dict[str, Any] = {}
    improvements: dict[str, Any] = {}

    for path, value in _numeric_leaves(current):
        if any(path.rsplit(".", 1)[-1] == leaf for leaf in IGNORED_LEAVES):
            continue
        before = base_values.get(path)
        if before is None or before == 0:
            continue

        better_up = _higher_is_better(path)
        # Cuánto ha empeorado, siempre >1 cuando va a peor.
        ratio = (before / value) if better_up else (value / before)
        if value == 0:
            continue

        if ratio > 1 + tolerance:
            regressions[path] = {"baseline": before, "current": value, "ratio": round(ratio, 3)}
            findings.append({
                "id": f"perf-{hashlib.sha256(path.encode()).hexdigest()[:12]}",
                "fingerprint": hashlib.sha256(f"perf|{path}".encode()).hexdigest()[:24],
                "rule_id": "performance.regression",
                "title": f"Regresión de rendimiento en {path}",
                "category": "performance",
                "severity": _severity(ratio),
                # La evidencia es una medición, no una inferencia: alta confianza
                # en el hecho. Que sea RELEVANTE es juicio humano, y por eso el
                # informe pasa después por revisión semántica.
                "confidence": "high",
                "locations": [{"file": path, "line": 1}],
                "evidence": {
                    "source_type": "tool",
                    "source": "compare-perf-baseline",
                    "message": f"{path}: {before:g} → {value:g} ({ratio:.2f}× peor)",
                },
                "impact": (
                    f"La medida empeoró un {(ratio - 1) * 100:.0f}% respecto a la línea base "
                    f"registrada en el repositorio."
                ),
                "recommendation": (
                    "Confirma que el cambio es intencionado. Si lo es, vuelve a generar la "
                    "línea base en el mismo commit para que quede constancia; si no, busca "
                    "la causa antes de fusionar."
                ),
            })
        elif ratio < 1 - tolerance:
            improvements[path] = {"baseline": before, "current": value, "ratio": round(ratio, 3)}

    return {
        "schema_version": "1.0.0",
        "tool": "compare-perf-baseline",
        "findings": findings,
        "dimensions": {
            "performance": {
                "compared": len(base_values),
                "regressions": len(regressions),
                "improvements": len(improvements),
                "tolerance": tolerance,
                "detail": {"regressions": regressions, "improvements": improvements},
            }
        },
        "limitations": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path, help="Measurements just taken")
    parser.add_argument("--baseline", type=Path, help="Recorded baseline to compare against")
    parser.add_argument("--tolerance", type=float, default=0.10,
                        help="Relative change ignored as noise (default 0.10 = 10%%)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    current = json.loads(args.current.read_text(encoding="utf-8-sig"))
    if args.baseline and args.baseline.exists():
        document = compare(current, json.loads(args.baseline.read_text(encoding="utf-8-sig")), args.tolerance)
    else:
        # Sin línea base no hay veredicto posible. Se declara como limitación,
        # que el informe trata como evidencia incompleta y nunca como aprobado.
        document = {
            "schema_version": "1.0.0",
            "tool": "compare-perf-baseline",
            "findings": [],
            "dimensions": {"performance": {"measurements": dict(_numeric_leaves(current))}},
            "limitations": [
                "No hay línea base de rendimiento; se registran las medidas pero no se "
                "puede afirmar que haya mejora ni regresión."
            ],
        }

    text = json.dumps(document, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    # Código de salida 1 cuando hay hallazgos, que es como `run_audit.py`
    # distingue "findings" de "failed" (ver su mapeo de exit codes).
    return 1 if document["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Duplicación de bloques y ciclos de importación (stdlib, solo lectura). Los usa `analyze_structure.py`."""

from __future__ import annotations

import ast
import hashlib
import posixpath
import re
from collections import defaultdict

COMMENT = re.compile(r"^\s*(#|//|/\*|\*|\*/)")
JS_IMPORT = re.compile(r"""(?:\bfrom\s+['"](\.{1,2}/[^'"]*)['"]|\bimport\s+['"](\.{1,2}/[^'"]*)['"]|\brequire\(\s*['"](\.{1,2}/[^'"]*)['"]\s*\))""")
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


_STRING_LITERAL = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`)""")
_NUMBER_LITERAL = re.compile(r"\b\d+(?:\.\d+)?\b")


def normalize_literals(text: str) -> str:
    """Cadenas y números pasan a un marcador: dos copias que solo cambian un literal («almacen» / «proveedor», 10 / 20) quedan iguales."""
    return _NUMBER_LITERAL.sub("N", _STRING_LITERAL.sub("S", text))


def find_near_duplicates(sources: dict[str, str], window: int, exact: list[dict]) -> list[dict]:
    """Copia-pega con un literal cambiado: igual que `find_duplicates` pero sin distinguir cadenas ni números, y con ventana menor.

    Lo que la pasada exacta ya ha informado (mismo fichero, líneas que se solapan) no se repite."""
    items = find_duplicates(sources, window, normalize=True, rule="near-duplication", title="Bloque de ≥{span} líneas casi idéntico a {a}:{line_a} (solo cambian literales)")
    covered: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for item in exact:
        covered[item["file"]].append((item["line"], item["line"] + int(item["value"]) - 1))
    return [item for item in items
            if not any(start <= item["line"] + int(item["value"]) - 1 and item["line"] <= end for start, end in covered.get(item["file"], []))]


def find_duplicates(sources: dict[str, str], window: int, *, normalize: bool = False, rule: str = "duplication",
                    title: str = "Bloque de ≥{span} líneas duplicado de {a}:{line_a}") -> list[dict]:
    """Bloques de `window` líneas significativas idénticas (sin espacios ni comentarios) en dos o más sitios.

    Las ventanas solapadas del mismo par de ficheros se fusionan en un solo hallazgo. Una línea significativa
    necesita >= 12 caracteres, para que los literales de datos repetidos no cuenten."""
    seen: dict[str, tuple[str, int]] = {}
    pairs: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for rel in sorted(sources):
        sig = [(n, re.sub(r"\s+", " ", normalize_literals(t) if normalize else t).strip()) for n, t in enumerate(sources[rel].splitlines(), 1)
               if len(t.strip()) >= 12 and not COMMENT.match(t)]
        for i in range(len(sig) - window + 1):
            key = hashlib.sha1("\n".join(t for _, t in sig[i:i + window]).encode()).hexdigest()
            first = seen.get(key)
            if first is None:
                seen[key] = (rel, sig[i][0])
            elif first[0] != rel or abs(first[1] - sig[i][0]) >= window:
                pairs[(first[0], rel)].append((first[1], sig[i][0]))
    items = []
    for (a, b), hits in sorted(pairs.items()):
        hits.sort(key=lambda h: h[1])
        first_a, start = hits[0]
        end = start
        groups = []
        for ha, hb in hits[1:]:
            if hb - end <= window:
                end = hb
            else:
                groups.append((first_a, start, end))
                first_a, start, end = ha, hb, hb
        groups.append((first_a, start, end))
        for line_a, line_b, last_b in groups:
            span = last_b - line_b + window
            items.append({"rule_id": f"pbp.structure.{rule}", "file": b, "line": line_b,
                          "title": title.format(span=span, a=a, line_a=line_a), "metric": "duplicated_lines",
                          "value": span, "threshold": window, "name": f"{a}:{line_a}"})
    return items


def _python_module(rel: str) -> str:
    parts = rel[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _edges(sources: dict[str, str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {rel: set() for rel in sources}
    py = {_python_module(r): r for r in sources if r.endswith(".py")}
    js = {r for r in sources if r.endswith(JS_EXT)}
    for rel, text in sources.items():
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError):
                continue
            module = _python_module(rel)
            package = module if rel.endswith("__init__.py") else module.rpartition(".")[0]
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level:
                        up = package.split(".") if package else []
                        up = up[:len(up) - (node.level - 1)]
                        base = ".".join([*up, *([base] if base else [])])
                    names = [base] + [f"{base}.{a.name}" if base else a.name for a in node.names]
                for name in names:
                    if name in py and py[name] != rel:
                        graph[rel].add(py[name])
        elif rel in js:
            folder = posixpath.dirname(rel)
            for match in JS_IMPORT.finditer(text):
                target = posixpath.normpath(posixpath.join(folder, next(g for g in match.groups() if g)))
                candidates = [target, *(target + e for e in JS_EXT), *(target + "/index" + e for e in JS_EXT),
                              re.sub(r"\.(m|c)?js$", ".ts", target)]
                for candidate in candidates:
                    if candidate in js and candidate != rel:
                        graph[rel].add(candidate)
                        break
    return graph


def find_cycles(sources: dict[str, str]) -> list[dict]:
    """Componentes fuertemente conexos (Tarjan iterativo) de tamaño > 1 en el grafo de imports internos."""
    graph = _edges(sources)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    components: list[list[str]] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        work = [(start, iter(sorted(graph[start])))]
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on.add(child)
                    work.append((child, iter(sorted(graph[child]))))
                    advanced = True
                    break
                if child in on:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(sorted(component))
    return [{"rule_id": "pbp.structure.import-cycle", "file": c[0], "line": 1,
             "title": f"Ciclo de importaciones entre {len(c)} módulos: {', '.join(c[:4])}{'…' if len(c) > 4 else ''}",
             "metric": "cycle_size", "value": len(c), "threshold": 1, "name": "|".join(c[:3])} for c in sorted(components)]

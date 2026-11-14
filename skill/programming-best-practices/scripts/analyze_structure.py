#!/usr/bin/env python3
"""Métricas estructurales de solo lectura: tamaño de módulos, responsabilidad única, complejidad y errores tragados.

Cubre lo que `algorithms` y `design-patterns` no miran: ficheros/funciones/clases demasiado grandes (señal de varias
responsabilidades), complejidad ciclomática, aridad, anidamiento, acoplamiento de entrada (imports) y excepciones
silenciadas. Los umbrales son DISPARADORES DE REVISIÓN configurables, no un veredicto ni una puntuación: cada
hallazgo es de severidad baja/media y confianza media/baja, y exige revisión semántica antes de actuar.
Python se analiza con `ast`; JavaScript/TypeScript, a nivel de fichero con expresiones regulares (sin dependencias).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

try:
    from analysis_core.files import project_files
    from structure_extra import find_cycles, find_duplicates
except ModuleNotFoundError:  # ejecución desde otro directorio de trabajo
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from analysis_core.files import project_files
    from structure_extra import find_cycles, find_duplicates

EXCLUDED = {
    ".git", ".venv", "venv", "env", "virtualenv", "node_modules", "bower_components", "vendor", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "site-packages", "dist", "build", "out", "target",
    "coverage", "htmlcov", ".quality-audit", ".quality-audit-stats", ".next", ".turbo", ".gradle", ".m2",
}
DEFAULTS = {"file_lines": 600, "function_lines": 80, "complexity": 15, "parameters": 7, "nesting": 5, "methods": 20, "imports": 30, "duplicate_lines": 12}
JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_IMPORT = re.compile(r"""(?:^\s*import\s[^;'"]*?from\s+['"]([^'"]+)['"]|^\s*import\s+['"]([^'"]+)['"]|\brequire\(\s*['"]([^'"]+)['"]\s*\))""", re.M)
JS_EMPTY_CATCH = re.compile(r"catch\s*(?:\([^)]*\))?\s*\{\s*(?://[^\n]*)?\s*\}")
BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert)
NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)


def _item(rule, file, line, title, metric, value, threshold, name=None):
    return {"rule_id": f"pbp.structure.{rule}", "file": file, "line": line, "title": title, "metric": metric,
            "value": value, "threshold": threshold, "name": name}


def _complexity(func) -> int:
    total, stack = 1, list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, BRANCHES):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            total += 1 + len(node.ifs)
        elif hasattr(ast, "match_case") and isinstance(node, ast.match_case):
            total += 1
        stack.extend(ast.iter_child_nodes(node))
    return total


def _depth(node, level=0) -> int:
    best = level
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        best = max(best, _depth(child, level + 1 if isinstance(child, NESTING) else level))
    return best


def _swallowed(handler: ast.ExceptHandler) -> bool:
    return all(isinstance(s, (ast.Pass, ast.Continue)) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in handler.body)


TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$|(^|/)tests?/[^/]*\.py$")
# Llamadas que cuentan como comprobar: assert*, check*, verify*, expect*… (incluidas las de ayudantes propios) y pytest.raises/warns/fail.
CHECKING_CALL = re.compile(r"^(assert|check|verify|expect|ensure|validate|must_|should_|fail$|raises$|warns$|approx$|deprecated_call$)", re.I)


def _call_name(call: ast.Call) -> str:
    function = call.func
    return function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""


def _tautology(node: ast.AST) -> bool:
    """`assert True`, `assert 1`, `assert x == x`, `assertTrue(True)`, `assertEqual(a, a)`: pasan siempre, pase lo que pase en el código."""
    if isinstance(node, ast.Assert):
        test = node.test
        if isinstance(test, ast.Constant):
            return bool(test.value)
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is, ast.LtE, ast.GtE)):
            return ast.dump(test.left) == ast.dump(test.comparators[0])
    if isinstance(node, ast.Call) and _call_name(node) in {"assertTrue", "assertEqual", "assertIs"} and node.args:
        if _call_name(node) == "assertTrue":
            return isinstance(node.args[0], ast.Constant) and bool(node.args[0].value)
        return len(node.args) >= 2 and ast.dump(node.args[0]) == ast.dump(node.args[1])
    return False


def _weak_tests(tree: ast.AST, rel: str) -> list[dict]:
    """Tests de Python que no pueden fallar: sin ninguna comprobación, o con comprobaciones que se cumplen siempre."""
    if not TEST_FILE.search(rel):
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
            continue
        checks = [n for n in ast.walk(node) if isinstance(n, ast.Assert) or (isinstance(n, ast.Call) and CHECKING_CALL.match(_call_name(n)))]
        meaningful = [n for n in checks if not _tautology(n)]
        if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            meaningful.append(node)  # un `raise` explícito también hace fallar el test
        if not checks:
            out.append(_item("test-no-assertion", rel, node.lineno, f"`{node.name}` no comprueba nada: no contiene ninguna aserción", "assertions", 0, 1, node.name))
        elif not meaningful:
            out.append(_item("test-tautological-assertion", rel, node.lineno, f"`{node.name}` solo contiene aserciones que se cumplen siempre", "assertions", len(checks), 1, node.name))
    return out


def analyze_python(text: str, rel: str, limits: dict) -> list[dict]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = _weak_tests(tree, rel)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > limits["function_lines"]:
                out.append(_item("function-length", rel, node.lineno, f"`{node.name}` tiene {length} líneas", "lines", length, limits["function_lines"], node.name))
            cc = _complexity(node)
            if cc > limits["complexity"]:
                out.append(_item("cyclomatic-complexity", rel, node.lineno, f"`{node.name}` tiene complejidad ciclomática {cc}", "cyclomatic", cc, limits["complexity"], node.name))
            args = node.args
            count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs) - (1 if args.args and args.args[0].arg in {"self", "cls"} else 0)
            if count > limits["parameters"]:
                out.append(_item("parameters", rel, node.lineno, f"`{node.name}` recibe {count} parámetros", "parameters", count, limits["parameters"], node.name))
            depth = _depth(node)
            if depth > limits["nesting"]:
                out.append(_item("nesting", rel, node.lineno, f"`{node.name}` anida {depth} niveles", "nesting", depth, limits["nesting"], node.name))
        elif isinstance(node, ast.ClassDef):
            methods = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in node.body)
            if methods > limits["methods"]:
                out.append(_item("many-methods", rel, node.lineno, f"La clase `{node.name}` define {methods} métodos", "methods", methods, limits["methods"], node.name))
        elif isinstance(node, ast.ExceptHandler) and _swallowed(node):
            out.append(_item("swallowed-exception", rel, node.lineno, "Excepción capturada y descartada sin registrarla ni propagarla", "swallowed", 1, 0))
    if len(modules) > limits["imports"]:
        out.append(_item("fan-out", rel, 1, f"El módulo importa {len(modules)} módulos distintos", "imports", len(modules), limits["imports"]))
    return out


def analyze_js(text: str, rel: str, limits: dict) -> list[dict]:
    out = []
    modules = {next(g for g in m.groups() if g) for m in JS_IMPORT.finditer(text)}
    if len(modules) > limits["imports"]:
        out.append(_item("fan-out", rel, 1, f"El módulo importa {len(modules)} módulos distintos", "imports", len(modules), limits["imports"]))
    for m in JS_EMPTY_CATCH.finditer(text):
        out.append(_item("swallowed-exception", rel, text.count("\n", 0, m.start()) + 1, "`catch` vacío: el error se descarta sin registrarlo ni propagarlo", "swallowed", 1, 0))
    return out


GENERATED_MARKERS = ("sourceMappingURL=", "@generated", "DO NOT EDIT", "Code generated")


def _is_generated(path: Path, rel: str, text: str) -> bool:
    """Salida de bundlers/compiladores: medirla es medir otra herramienta, no el código del proyecto."""
    parts = rel.split("/")[:-1]
    if any(part.startswith(("dist", "build", ".vite", ".output")) for part in parts):
        return True
    head = text[:2000]
    if any(marker in head or marker in text[-400:] for marker in GENERATED_MARKERS):
        return True
    if path.suffix.lower() in {".js", ".mjs", ".cjs", ".jsx"}:
        if any(path.with_suffix(ext).exists() for ext in (".ts", ".tsx")):
            return True  # .js compilado junto a su .ts
        lines = text.count(chr(10)) + 1
        average = len(text) / lines
        if average > 1000 or (average > 200 and lines < 20):
            return True  # una línea gigante = minificado o empaquetado
    return False


def analyze(root: Path, limits: dict) -> dict:
    items, files, skipped, generated = [], 0, 0, 0
    sources: dict[str, str] = {}
    for path in project_files(root, EXCLUDED):
        suffix = path.suffix.lower()
        if suffix != ".py" and suffix not in JS_SUFFIXES:
            continue
        if suffix in JS_SUFFIXES and re.search(r"\.(min|bundle)\.[cm]?js$|\.d\.ts$", path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        rel = path.relative_to(root).as_posix()
        if _is_generated(path, rel, text):
            generated += 1
            continue
        files += 1
        sources[rel] = text
        lines = text.count("\n") + 1
        if lines > limits["file_lines"]:
            items.append(_item("file-size", rel, 1, f"El fichero tiene {lines} líneas", "lines", lines, limits["file_lines"]))
        items.extend(analyze_python(text, rel, limits) if suffix == ".py" else analyze_js(text, rel, limits))
    items.extend(find_duplicates(sources, limits["duplicate_lines"]))
    items.extend(find_cycles(sources))
    limitations = [
        "Duplicación: ventanas de líneas significativas idénticas (exacta, no semántica); ciclos: solo imports internos resolubles (Python y rutas relativas JS/TS).",
        "Umbrales = disparadores de revisión configurables, no un veredicto; todo hallazgo requiere revisión semántica.",
        "JavaScript/TypeScript se mide solo a nivel de fichero (tamaño, imports, catch vacío); función/clase/complejidad solo en Python.",
    ]
    if generated:
        limitations.append(f"{generated} fichero(s) generados o empaquetados omitidos (dist*/build*/.vite*, @generated, .js compilado junto a su .ts, minificados).")
    if skipped:
        limitations.append(f"{skipped} fichero(s) ilegibles omitidos.")
    return {"schema_version": "1.0.0", "tool": "structure", "root": str(root), "files_analyzed": files, "limits": limits,
            "items": items, "limitations": limitations}


def main() -> int:
    parser = argparse.ArgumentParser(description="Métricas estructurales de solo lectura (tamaño, complejidad, SRP, errores tragados).")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for key, default in DEFAULTS.items():
        parser.add_argument(f"--max-{key.replace('_', '-')}", type=int, default=default, dest=key)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"root no es un directorio: {root}", file=sys.stderr)
        return 2
    result = analyze(root, {k: getattr(args, k) for k in DEFAULTS})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

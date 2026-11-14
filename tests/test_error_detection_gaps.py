"""Errores que el banco de pruebas de skills-package mostró sin cubrir: reglas de semgrep, ruff sin configuración propia y duplicación casi idéntica."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import SKILL, load_module
from tests.semgrep_batch import AVAILABLE, scan

scripts = SKILL / "scripts"
sys.path.insert(0, str(scripts))
structure = load_module("analyze_structure", scripts / "analyze_structure.py")
structure_extra = load_module("structure_extra", scripts / "structure_extra.py")
normalize = load_module("normalize_tool_output", scripts / "reporting" / "normalize_tool_output.py")
plan_audit = load_module("plan_audit", scripts / "plan_audit.py")

RULES = scripts / "rules" / "semgrep.yml"

PYTHON_MODIFY = "def clean(items):\n    for x in items:\n        if x is None:\n            {statement}\n"
ASYNC_FN = "async function f(client) {{\n  {body}\n}}\n"

# nombre → (fichero, código, reglas que DEBEN saltar, reglas que NO deben saltar)
CASES: dict[str, tuple[str, str, set[str], set[str]]] = {
    # assert como validación
    "assert-en-codigo": ("app/export.py", "def export(path):\n    assert path.exists(), 'missing'\n", {"assert-for-validation"}, set()),
    **{f"assert-en-{name}": (name, "def test_export(path):\n    assert path.exists()\n", set(), {"assert-for-validation"})
       for name in ("tests/test_export.py", "test_export.py", "export_test.py", "tests/helpers.py", "conftest.py")},
    # modificar mientras se itera
    **{f"modifica-{i}": ("a.py", PYTHON_MODIFY.format(statement=s), {"modify-collection-while-iterating"}, set())
       for i, s in enumerate(("del items[0]", "items.remove(x)", "items.pop()", "items.append(x)", "items.insert(0, x)", "items.clear()", "items.extend([x])"))},
    **{f"no-modifica-{i}": ("a.py", s + "\n", set(), {"modify-collection-while-iterating"})
       for i, s in enumerate((
           "for x in list(items):\n    items.remove(x)",
           "for x in items.copy():\n    items.remove(x)",
           "for x in items:\n    other.append(x)",
           "for x in items:\n    total = x",
           "for k in mapping:\n    mapping[k] = 1",
       ))},
    # igualdad laxa
    "laxa-igual": ("a.js", "if (a == b) { run(); }\n", {"loose-equality"}, set()),
    "laxa-distinto": ("a.js", "if (a != b) { run(); }\n", {"loose-equality"}, set()),
    **{f"estricta-{i}": ("a.js", s, set(), {"loose-equality"})
       for i, s in enumerate(("if (a === b) { run(); }\n", "if (a !== b) { run(); }\n", "if (a == null) { run(); }\n", "if (a != null) { run(); }\n",
                              "if (null == a) { run(); }\n", "if (null != a) { run(); }\n"))},
    # parseInt
    "parseint-sin-base": ("a.js", "const n = parseInt(texto);\n", {"parseint-without-radix"}, set()),
    "parseint-con-base": ("a.js", "const n = parseInt(texto, 10);\n", set(), {"parseint-without-radix"}),
    # código inalcanzable
    "inalcanzable-return": ("a.js", "function f() {\n  return 1;\n  console.log('x');\n}\n", {"unreachable-code"}, set()),
    "inalcanzable-throw": ("a.js", "function f() {\n  throw new Error('x');\n  cleanup();\n}\n", {"unreachable-code"}, set()),
    "alcanzable-if": ("a.js", "function f() {\n  if (x) {\n    return 1;\n  }\n  return 2;\n}\n", set(), {"unreachable-code"}),
    "alcanzable-funcion-elevada": ("a.js", "function f() {\n  return helper();\n  function helper() { return 1; }\n}\n", set(), {"unreachable-code"}),
    # promesa olvidada
    "promesa-post": ("a.js", ASYNC_FN.format(body="client.post('/guardar', datos);"), {"async-call-not-awaited"}, set()),
    "promesa-cliente-es": ("a.js", ASYNC_FN.format(body="cliente.post('/guardar', datos);"), {"async-call-not-awaited"}, set()),
    "promesa-flecha": ("a.js", "const f = async (client) => {\n  client.save({});\n};\n", {"async-call-not-awaited"}, set()),
    **{f"promesa-usada-{i}": ("a.js", ASYNC_FN.format(body=body), set(), {"async-call-not-awaited"})
       for i, body in enumerate((
           "await client.post('/x');",
           "return client.post('/x');",
           "const r = client.post('/x');\n  return r;",
           "let r;\n  r = client.post('/x');\n  return r;",
           "client.post('/x').then(ok);",
           "client.post('/x').catch(err);",
           "void client.post('/x');",
           "await Promise.all([client.post('/a'), client.put('/b')]);",
           "foo(client.post('/x'));",
       ))},
    "promesa-fuera-de-async": ("a.js", "function f(client) {\n  client.post('/x');\n}\n", set(), {"async-call-not-awaited"}),
    "promesa-receptor-ajeno": ("a.js", "async function f(reply, map, list) {\n  reply.send(1);\n  map.delete(2);\n  list.push(3);\n}\n", set(), {"async-call-not-awaited"}),
}


@unittest.skipUnless(AVAILABLE, "semgrep no está instalado")
class ErrorRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.found = scan(RULES, {name: (file, source) for name, (file, source, _, _) in CASES.items()})

    def check(self, *prefixes: str) -> None:
        names = [name for name in CASES if name.startswith(prefixes)]
        self.assertTrue(names, prefixes)
        for name in names:
            _, _, must, never = CASES[name]
            with self.subTest(case=name):
                self.assertTrue(must <= self.found[name], f"debía saltar {sorted(must - self.found[name])}; saltó {sorted(self.found[name])}")
                self.assertFalse(never & self.found[name], f"no debía saltar {sorted(never & self.found[name])}")

    def test_the_rules_are_valid(self) -> None:
        done = subprocess.run(["semgrep", "--validate", "--config", str(RULES), "--metrics=off", "--quiet"], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_assert_is_reported_in_production_code_but_not_in_tests(self) -> None:
        self.check("assert-en-")

    def test_modifying_the_iterated_collection_is_reported_but_a_copy_or_another_collection_is_not(self) -> None:
        self.check("modifica-", "no-modifica-")

    def test_loose_equality_is_reported_but_strict_and_null_checks_are_not(self) -> None:
        self.check("laxa-", "estricta-")

    def test_parseint_needs_a_radix(self) -> None:
        self.check("parseint-")

    def test_a_statement_after_return_or_throw_is_unreachable(self) -> None:
        self.check("inalcanzable-", "alcanzable-")

    def test_a_remote_call_whose_promise_is_dropped_inside_an_async_function(self) -> None:
        self.check("promesa-")


class RuffConfigurationTests(unittest.TestCase):
    def ruff_argv(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            for name, text in files.items():
                (root / name).write_text(text, encoding="utf-8")
            inventory = {"schema_version": "1", "root": str(root), "git": {}, "default_scope": {"type": "repository"}, "languages": [{"name": "python", "files": 1}],
                         "ecosystems": [{"name": "python", "build_systems": ["python"], "test_runners": []}], "configurations": list(files),
                         "tools": {"ruff": {"status": "available", "command": "ruff"}, "python": {"status": "available", "command": sys.executable}}}
            with patch.object(plan_audit, "detect", return_value=inventory):
                plan = plan_audit.create_plan(root, "standard", scope="repository")
        return next(check for check in plan["checks"] if check["id"] == "python.ruff")["argv"]

    def test_without_its_own_configuration_none_comparisons_are_added(self) -> None:
        argv = self.ruff_argv({})
        self.assertIn("--extend-select", argv)
        self.assertEqual(argv[argv.index("--extend-select") + 1], "E711,E712")

    def test_a_project_with_its_own_configuration_is_left_alone(self) -> None:
        for files in ({"ruff.toml": "line-length = 100\n"}, {".ruff.toml": "line-length = 100\n"}, {"pyproject.toml": "[tool.ruff]\nline-length = 100\n"}):
            with self.subTest(files=list(files)):
                self.assertNotIn("--extend-select", self.ruff_argv(files))

    def test_a_pyproject_without_a_ruff_section_does_not_count_as_configuration(self) -> None:
        self.assertIn("--extend-select", self.ruff_argv({"pyproject.toml": "[project]\nname = 'x'\n"}))


class NearDuplicationTests(unittest.TestCase):
    BLOCK = """
        def {name}(items):
            results = {{}}
            for item in items:
                key = item.get("{key}")
                if key not in results:
                    results[key] = {{"units": 0, "value": 0.0, "count": 0}}
                results[key]["units"] += item.get("stock", 0)
                results[key]["value"] += item.get("stock", 0) * item.get("price", 0.0)
                results[key]["count"] += 1
            return results
    """
    LONG = """
        def process(items):
            results = {}
            for item in items:
                key = item.get("warehouse")
                if key not in results:
                    results[key] = {"units": 0, "value": 0.0, "count": 0}
                results[key]["units"] += item.get("stock", 0)
                results[key]["value"] += item.get("stock", 0) * item.get("price", 0.0)
                results[key]["count"] += 1
                results[key]["last"] = item.get("updated_at", "")
                results[key]["names"] = sorted(set(results[key].get("names", [])) | {item["name"]})
                results[key]["tags"] = sorted(set(results[key].get("tags", [])) | set(item.get("tags", [])))
            return results
    """

    def items(self, sources: dict[str, str], window: int = 9) -> list[dict]:
        limits = dict(structure.DEFAULTS)
        limits["near_duplicate_lines"] = window
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in sources.items():
                (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
            return [item for item in structure.analyze(root, limits)["items"] if item["rule_id"].endswith("duplication")]

    def two_copies(self) -> str:
        return self.BLOCK.format(name="by_warehouse", key="warehouse") + self.BLOCK.format(name="by_supplier", key="supplier")

    def test_a_copy_with_a_different_literal_is_reported_as_near_duplication(self) -> None:
        found = self.items({"a.py": self.two_copies()})
        self.assertEqual([item["rule_id"] for item in found], ["pbp.structure.near-duplication"])
        self.assertIn("solo cambian literales", found[0]["title"])

    def test_an_exact_copy_is_reported_as_exact_and_not_again_as_near(self) -> None:
        found = self.items({"a.py": self.LONG, "b.py": self.LONG})
        self.assertEqual([item["rule_id"] for item in found if item["file"] == "b.py"], ["pbp.structure.duplication"])

    def test_different_code_is_not_reported(self) -> None:
        self.assertEqual(self.items({"a.py": self.BLOCK.format(name="one", key="k") + """
            def other(values):
                total = 0
                for value in values:
                    if value > 10:
                        total += value
                    elif value < 0:
                        total -= value
                return total
        """}), [])

    def test_a_smaller_block_than_the_window_is_not_reported(self) -> None:
        small = """
            def a(items):
                result = {}
                for item in items:
                    result[item] = 1
                return result

            def b(items):
                result = {}
                for item in items:
                    result[item] = 2
                return result
        """
        self.assertEqual(self.items({"a.py": small}), [])

    def test_the_window_is_configurable(self) -> None:
        self.assertEqual(len(self.items({"a.py": self.two_copies()}, window=9)), 1)
        self.assertEqual(self.items({"a.py": self.two_copies()}, window=12), [])

    def test_literal_normalization(self) -> None:
        n = structure_extra.normalize_literals
        self.assertEqual(n('x = d.get("almacen") + 10'), "x = d.get(S) + N")
        self.assertEqual(n("y = 'a' + 'b' + 3.5"), "y = S + S + N")
        self.assertEqual(n("name2 = value10"), "name2 = value10")  # los números de un identificador no se tocan
        self.assertEqual(n("`hola ${x}`"), "S")

    def test_the_normalized_finding_has_a_recommendation(self) -> None:
        item = {"rule_id": "pbp.structure.near-duplication", "file": "a.py", "line": 3, "title": "t", "metric": "duplicated_lines", "value": 9, "threshold": 9, "name": "a.py:1"}
        (finding,), _, _ = normalize.parse_structure({"items": [item]}, None)
        self.assertNotIn("Revisar el contexto", finding["recommendation"])


if __name__ == "__main__":
    unittest.main()

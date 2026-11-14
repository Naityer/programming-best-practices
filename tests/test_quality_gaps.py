"""Huecos de calidad que midió el banco de pruebas de skills-package: tests que no comprueban nada, reglas de rendimiento y planes sin Python."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module
from tests.semgrep_batch import AVAILABLE, scan

scripts = SKILL / "scripts"
sys.path.insert(0, str(scripts))
structure = load_module("analyze_structure", scripts / "analyze_structure.py")
normalize = load_module("normalize_tool_output", scripts / "reporting" / "normalize_tool_output.py")
plan_audit = load_module("plan_audit", scripts / "plan_audit.py")


def rules_of(files: dict[str, str]) -> dict[str, list[str]]:
    """{regla corta: [nombre…]} de lo que detecta analyze_structure en esos ficheros."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, text in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(text), encoding="utf-8")
        found: dict[str, list[str]] = {}
        for item in structure.analyze(root, structure.DEFAULTS)["items"]:
            found.setdefault(item["rule_id"].rsplit(".", 1)[-1], []).append(item.get("name") or "")
        return found


class WeakTestsTests(unittest.TestCase):
    def test_a_test_without_any_assertion_is_reported(self) -> None:
        found = rules_of({"tests/test_a.py": """
            def test_runs():
                value = compute(1)
        """})
        self.assertEqual(found.get("test-no-assertion"), ["test_runs"])

    def test_assertions_that_always_pass_are_reported(self) -> None:
        for body in ("assert True", "assert 1", "assert compute(2) == compute(2)", "self.assertTrue(True)", "self.assertEqual(compute(2), compute(2))"):
            with self.subTest(body=body):
                found = rules_of({"tests/test_a.py": f"""
                    def test_x(self=None):
                        {body}
                """})
                self.assertEqual(found.get("test-tautological-assertion"), ["test_x"])
                self.assertNotIn("test-no-assertion", found)

    def test_real_checks_are_not_reported(self) -> None:
        for body in (
            "assert compute(2) == 4",
            "assert compute(2)",
            "self.assertEqual(compute(2), 4)",
            "self.assertRaises(ValueError, compute, -1)",
            "with pytest.raises(ValueError):\n                compute(-1)",
            "mock.assert_called_once_with(2)",
            "check_result(compute(2))",
            "verify_invariants(compute(2))",
            "expect(compute(2)).to_equal(4)",
            "pytest.fail('no debería llegar')",
            "raise AssertionError('mal')",
            "assert True\n            assert compute(2) == 4",
        ):
            with self.subTest(body=body):
                found = rules_of({"tests/test_a.py": f"""
                    def test_x():
                        {body}
                """})
                self.assertNotIn("test-no-assertion", found)
                self.assertNotIn("test-tautological-assertion", found)

    def test_only_test_files_and_test_functions_are_looked_at(self) -> None:
        found = rules_of({
            "app/service.py": """
                def test_connection():
                    return 1
            """,
            "tests/test_a.py": """
                def helper():
                    pass

                class Fixture:
                    def setup(self):
                        pass
            """,
        })
        self.assertNotIn("test-no-assertion", found)

    def test_unittest_methods_inside_a_class_are_reported_too(self) -> None:
        found = rules_of({"tests/test_a.py": """
            import unittest

            class Case(unittest.TestCase):
                def test_nothing(self):
                    compute(1)

                def test_something(self):
                    self.assertEqual(compute(1), 1)
        """})
        self.assertEqual(found.get("test-no-assertion"), ["test_nothing"])

    def test_all_the_usual_test_file_names_count(self) -> None:
        for name in ("tests/test_a.py", "test/test_a.py", "pkg/test_a.py", "pkg/a_test.py", "tests/helpers_for_a.py"):
            with self.subTest(name=name):
                found = rules_of({name: """
                    def test_x():
                        compute(1)
                """})
                self.assertIn("test-no-assertion", found)


class WeakTestsNormalizationTests(unittest.TestCase):
    def finding(self, rule: str):
        item = {"rule_id": f"pbp.structure.{rule}", "file": "tests/test_a.py", "line": 3, "title": "t", "metric": "assertions", "value": 0, "threshold": 1, "name": "test_x"}
        (result,), _, _ = normalize.parse_structure({"items": [item]}, None)
        return result

    def test_they_are_test_quality_findings_not_maintainability(self) -> None:
        for rule in ("test-no-assertion", "test-tautological-assertion"):
            self.assertEqual(self.finding(rule)["category"], "tests", rule)

    def test_a_tautology_is_medium_and_a_missing_assertion_is_low_because_it_may_be_a_smoke_test(self) -> None:
        self.assertEqual(self.finding("test-tautological-assertion")["severity"], "medium")
        self.assertEqual(self.finding("test-no-assertion")["severity"], "low")

    def test_they_come_with_a_recommendation(self) -> None:
        for rule in ("test-no-assertion", "test-tautological-assertion"):
            self.assertNotIn("Revisar el contexto", self.finding(rule)["recommendation"])


CASES = {
    "regex-for": ("caso.py", "import re\nfor line in lines:\n    p = re.compile(r'[a-z]+')\n", {"regex-compile-in-loop"}, set()),
    "regex-while": ("caso.py", "import re\nwhile pending:\n    p = re.compile(r'[a-z]+')\n", {"regex-compile-in-loop"}, set()),
    "regex-una-vez": ("caso.py", "import re\nP = re.compile(r'[a-z]+')\nfor line in lines:\n    P.findall(line)\n", set(), {"regex-compile-in-loop"}),
    "regex-dinamica": ("caso.py", "import re\nfor word in words:\n    p = re.compile(word)\n", set(), {"regex-compile-in-loop"}),
    "consulta-en-bucle": ("caso.py", "for cid in ids:\n    cursor.execute('SELECT * FROM t WHERE id = ?', (cid,))\n", {"query-in-loop"}, set()),
    "consulta-agrupada": ("caso.py", "cursor.execute('SELECT * FROM t WHERE id IN (?, ?)', ids)\nfor fila in cursor.fetchall():\n    print(fila)\n", set(), {"query-in-loop"}),
    "execute-ajeno": ("caso.py", "for tarea in tareas:\n    executor.execute(tarea)\n", set(), {"query-in-loop"}),
    "readlines-open": ("caso.py", "n = len(open('a.txt').readlines())\n", {"read-whole-file-lines"}, set()),
    "readlines-with": ("caso.py", "with open('a.txt') as f:\n    todas = f.readlines()\n", {"read-whole-file-lines"}, set()),
    "iterar-fichero": ("caso.py", "with open('a.txt') as f:\n    for linea in f:\n        print(linea)\n", set(), {"read-whole-file-lines"}),
}


@unittest.skipUnless(AVAILABLE, "semgrep no está instalado")
class PerformanceRulesTests(unittest.TestCase):
    RULES = scripts / "rules" / "semgrep.yml"

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = scan(cls.RULES, {name: (file, source) for name, (file, source, _, _) in CASES.items()})

    def check(self, *prefixes: str) -> None:
        names = [name for name in CASES if name.startswith(prefixes)]
        self.assertTrue(names, prefixes)
        for name in names:
            _, _, must, never = CASES[name]
            with self.subTest(case=name):
                self.assertTrue(must <= self.found[name], f"debía saltar {sorted(must - self.found[name])}; saltó {sorted(self.found[name])}")
                self.assertFalse(never & self.found[name], f"no debía saltar {sorted(never & self.found[name])}")

    def test_the_rules_are_valid(self) -> None:
        done = subprocess.run(["semgrep", "--validate", "--config", str(self.RULES), "--metrics=off", "--quiet"], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_regex_compiled_in_a_loop_but_not_once_or_built_dynamically(self) -> None:
        self.check("regex-")

    def test_a_statement_per_iteration_but_not_one_grouped_query_or_unrelated_execute(self) -> None:
        self.check("consulta-", "execute-")

    def test_whole_file_into_memory_but_not_iterating_the_file(self) -> None:
        self.check("readlines-", "iterar-")

    def test_the_findings_are_performance_findings(self) -> None:
        data = {"results": [{"check_id": "x.pbp.python.regex-compile-in-loop", "path": "a.py", "start": {"line": 3},
                             "extra": {"severity": "INFO", "message": "m", "metadata": {"category": "performance", "confidence": "MEDIUM"}}}]}
        (finding,), _, _ = normalize.parse_semgrep(data, None)
        self.assertEqual(finding["category"], "performance")
        self.assertEqual(finding["rule_id"], "pbp.python.regex-compile-in-loop")


class PlanWithoutPythonSourcesTests(unittest.TestCase):
    """Un proyecto con `requirements.txt` y ningún .py (infraestructura, un front): ruff y mypy no tienen nada que comprobar."""

    def ids(self, files: dict[str, str]) -> dict[str, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, text in files.items():
                (root / relative).write_text(text, encoding="utf-8")
            return {check["id"]: check for check in plan_audit.create_plan(root, "standard")["checks"]}

    def test_without_python_files_no_type_checker_is_planned_and_ruff_says_why(self) -> None:
        checks = self.ids({"requirements.txt": "requests==2.31.0\n"})
        self.assertNotIn("python.mypy", checks)
        self.assertNotIn("python.pyright", checks)
        self.assertEqual(checks["python.ruff"]["status"], "unavailable")
        self.assertIn("No Python source files", checks["python.ruff"]["reason"])

    def test_with_python_files_nothing_changes(self) -> None:
        checks = self.ids({"requirements.txt": "requests==2.31.0\n", "app.py": "x = 1\n"})
        self.assertNotIn("No Python source files", checks["python.ruff"]["reason"])


if __name__ == "__main__":
    unittest.main()

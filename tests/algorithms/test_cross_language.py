from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
PACKAGE = SCRIPTS / "algorithms"
SPEC = importlib.util.spec_from_file_location(
    "pbp_algorithm_cross_language", PACKAGE / "__init__.py",
    submodule_search_locations=[str(PACKAGE)],
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CrossLanguageIRTests(unittest.TestCase):
    def test_equivalent_sort_calls_share_one_operation_id(self) -> None:
        fixtures = {
            "a.py": "def f(xs):\n    return sorted(xs)\n",
            "A.java": "class A { void f(){ Collections.sort(xs); } }",
            "A.kt": "fun f() { xs.sorted() }",
            "a.js": "function f(){ xs.sort(); }",
            "a.ts": "function f(){ xs.sort(); }",
            "A.cs": "class A { void F(){ xs.Sort(); } }",
            "a.go": "package main; func f(){ sort.Ints(xs) }",
            "a.rs": "fn f(){ xs.sort(); }",
            "a.c": "void f(){ sort(xs); }",
            "a.cpp": "void f(){ sort(xs); }",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in fixtures.items():
                (root / name).write_text(source, encoding="utf-8")
            result = MODULE.analyze_repository(root)
        by_file = {item["primary_location"]["file"]: item for item in result["algorithms"]}
        self.assertEqual(set(fixtures), set(by_file))
        self.assertEqual({"library.sort"}, {item["algorithm_id"] for item in by_file.values()})
        self.assertTrue(all(item["recommendation"] is None for item in by_file.values()))
        self.assertTrue(all(item["requirements"][0]["state"] == "UNKNOWN" for item in by_file.values()))


if __name__ == "__main__":
    unittest.main()

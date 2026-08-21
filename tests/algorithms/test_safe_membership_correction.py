from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from algorithms import analyze_repository


class SafeMembershipCorrectionTests(unittest.TestCase):
    SOURCE = """def f(requested):
    out = []
    for item in requested:
        if item in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
            out.append(item)
    return out
"""

    def test_bounded_primitive_literal_gets_semantics_preserving_safe_hoist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text(self.SOURCE, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        item = next(value for value in artifact["algorithms"] if value["rule_id"] == "pbp.algorithm.search.repeated-linear-membership")
        self.assertEqual("SAFE", item["recommendation"]["correction_level"])
        self.assertTrue(all(req["state"] == "PROVEN" for req in item["requirements"] if req["hard"]))
        patch = item["recommendation"]["patch"]
        self.assertEqual("multi-edit", patch["kind"])

        transformed = self.SOURCE
        replacement = next(edit for edit in patch["edits"] if edit["kind"] == "replace-expression")
        transformed = transformed.replace(replacement["original"], replacement["replacement"], 1)
        insertion = next(edit for edit in patch["edits"] if edit["kind"] == "insert-before")
        lines = transformed.splitlines(keepends=True)
        lines.insert(insertion["line"] - 1, insertion["text"])
        transformed = "".join(lines)

        original_ns: dict = {}
        transformed_ns: dict = {}
        exec(self.SOURCE, original_ns)
        exec(transformed, transformed_ns)
        probes = [[], [-1, 0, 9, 10], list(range(-5, 20)), [9, 9, 3, 12]]
        for values in probes:
            with self.subTest(values=values):
                self.assertEqual(original_ns["f"](values), transformed_ns["f"](values))

    def test_unbounded_or_runtime_membership_remains_assisted(self) -> None:
        source = "def f(available, requested):\n    for item in requested:\n        if item in available:\n            print(item)\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.py").write_text(source, encoding="utf-8")
            artifact = analyze_repository(root, use_cache=False)
        item = next(value for value in artifact["algorithms"] if value["rule_id"] == "pbp.algorithm.search.repeated-linear-membership")
        self.assertEqual("ASSISTED", item["recommendation"]["correction_level"])
        self.assertTrue(any(req["hard"] and req["state"] == "UNKNOWN" for req in item["requirements"]))


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
PACKAGE = SCRIPTS / "algorithms"
SPEC = importlib.util.spec_from_file_location("pbp_algorithm_misuse", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AtlasMisuseCaseTests(unittest.TestCase):
    def analyze(self, source: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.py").write_text(textwrap.dedent(source), encoding="utf-8")
            return MODULE.analyze_repository(root)["algorithms"]

    def test_required_negative_cases_are_evidence_backed_and_never_safe(self) -> None:
        occurrences = self.analyze(
            """
            import bisect
            import networkx as nx

            def repeated(xs, queries):
                return [q for q in queries if q in xs]

            def dedup(xs):
                out = []
                for x in xs:
                    if x not in out:
                        out.append(x)
                return out

            def bfs(start):
                queue = [start]
                while queue:
                    node = queue.pop(0)
                return node

            def fib(n):
                if n < 2:
                    return n
                return fib(n - 1) + fib(n - 2)

            bad_binary = bisect.bisect_left([3, 1, 2], 2)
            graph = nx.DiGraph()
            graph.add_edge("a", "b", weight=-1)
            path = nx.dijkstra_path(graph, "a", "b")
            """
        )
        by_rule = {item["rule_id"]: item for item in occurrences}
        expected = {
            "pbp.algorithm.search.repeated-linear-membership",
            "pbp.algorithm.dedup.quadratic-membership",
            "pbp.algorithm.graph.bfs-list-pop-zero",
            "pbp.algorithm.dp.overlapping-recursion",
            "pbp.algorithm.search.binary-unsorted-input",
            "pbp.algorithm.graph.dijkstra-negative-weight",
        }
        self.assertTrue(expected.issubset(by_rule))
        self.assertEqual("CONTRADICTED", by_rule["pbp.algorithm.search.binary-unsorted-input"]["requirements"][0]["state"])
        self.assertEqual("BLOCKED", by_rule["pbp.algorithm.graph.dijkstra-negative-weight"]["recommendation"]["correction_level"])
        self.assertNotIn("SAFE", {item.get("recommendation", {}).get("correction_level") for item in by_rule.values() if item.get("recommendation")})

    def test_tiny_literal_membership_does_not_suggest_a_hash_index(self) -> None:
        occurrences = self.analyze(
            """
            def classify(values):
                return [value for value in values if value in [1, 2, 3]]
            """
        )
        self.assertNotIn("pbp.algorithm.search.repeated-linear-membership", {item["rule_id"] for item in occurrences})


if __name__ == "__main__":
    unittest.main()

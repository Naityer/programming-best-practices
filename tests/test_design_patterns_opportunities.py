"""spec §13's own worked example, almost verbatim: the same discriminator
compared in two functions must produce a `refactor-opportunity`, never a
"no encuentro X -> deberías usar X" guess with no repeated evidence.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402
from design_patterns.opportunities import detect_opportunities as _detect_opportunities  # noqa: E402


def build_graph(source: str, filename: str = "module.py"):
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path(filename))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


def detect_opportunities(graph) -> list:
    """detect_opportunities() returns (results, limitations) since Fase 3's
    role-binding guardrail — see test_design_patterns_guardrails.py for that
    behavior. These tests only care about the results."""
    results, _ = _detect_opportunities(graph)
    return results


class StrategyOpportunityTests(unittest.TestCase):
    SOURCE = """
        class Calculator:
            def calculate(self, kind, x):
                if kind == "fast":
                    return x
                elif kind == "accurate":
                    return x * 2

            def validate(self, kind, x):
                if kind == "fast":
                    return True
                elif kind == "accurate":
                    return x > 0
    """

    def test_repeated_discriminator_across_two_methods_is_a_strategy_opportunity(self) -> None:
        graph = build_graph(self.SOURCE)
        opportunities = detect_opportunities(graph)
        self.assertEqual(1, len(opportunities))
        result = opportunities[0]
        self.assertEqual("refactor-opportunity", result.status)
        self.assertEqual("strategy", result.pattern_id)
        self.assertEqual("medium", result.confidence)
        self.assertEqual(2, len(result.roles))
        self.assertEqual("repeated conditional dispatch on the same discriminator", result.refactoring["smell"])

    def test_a_single_occurrence_is_not_a_repetition(self) -> None:
        graph = build_graph("""
            class Calculator:
                def calculate(self, kind, x):
                    if kind == "fast":
                        return x
                    elif kind == "accurate":
                        return x * 2
        """)
        self.assertEqual([], detect_opportunities(graph))


class StateOpportunityTests(unittest.TestCase):
    def test_lifecycle_like_values_classify_as_state_opportunity(self) -> None:
        graph = build_graph("""
            class Job:
                def log(self, status, message):
                    if status == "pending":
                        return "queued: " + message
                    elif status == "running":
                        return "in progress: " + message

                def notify(self, status, message):
                    if status == "pending":
                        return "will notify: " + message
                    elif status == "running":
                        return "notifying: " + message
        """)
        opportunities = detect_opportunities(graph)
        self.assertEqual(1, len(opportunities))
        self.assertEqual("state", opportunities[0].pattern_id)
        self.assertEqual("refactor-opportunity", opportunities[0].status)


class NoOpportunityInventedTests(unittest.TestCase):
    def test_no_discriminator_no_opportunity(self) -> None:
        graph = build_graph("""
            class Plain:
                def do_it(self):
                    return 42
        """)
        self.assertEqual([], detect_opportunities(graph))


if __name__ == "__main__":
    unittest.main()

"""Fase 3 guardrails (design-patterns-module/03-plan.md, Parte B): explicit
verification checkpoints, not just trust that detector code is correct.
"""

from __future__ import annotations

import unittest

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.catalog import load_catalog  # noqa: E402
from design_patterns.engine import dropped_role_limitation, roles_are_bound, run_engine  # noqa: E402
from design_patterns.ir import CodeGraph, Entity  # noqa: E402
from design_patterns.model import Location, PatternResult  # noqa: E402


def cls(entity_id: str, name: str) -> Entity:
    return Entity(id=entity_id, language="python", kind="class", name=name, qualified_name=name, file="a.py", line=1)


class RolesAreBoundTests(unittest.TestCase):
    def _result(self, roles: dict[str, str]) -> PatternResult:
        return PatternResult(
            pattern_id="adapter", status="detected", confidence="medium",
            primary_location=Location(file="a.py", line=1), roles=roles,
        )

    def test_empty_roles_dict_is_not_bound(self) -> None:
        self.assertFalse(roles_are_bound(self._result({})))

    def test_a_role_with_an_empty_string_value_is_not_bound(self) -> None:
        self.assertFalse(roles_are_bound(self._result({"target": "Target", "adapter": ""})))

    def test_a_role_with_a_non_string_value_is_not_bound(self) -> None:
        result = self._result({"target": "Target"})
        result.roles["adapter"] = None  # type: ignore[index]
        self.assertFalse(roles_are_bound(result))

    def test_all_roles_pointing_at_real_names_is_bound(self) -> None:
        self.assertTrue(roles_are_bound(self._result({"target": "T", "adapter": "A", "adaptee": "D"})))

    def test_dropped_role_limitation_names_the_pattern_and_location(self) -> None:
        message = dropped_role_limitation(self._result({}))
        self.assertIn("adapter", message)
        self.assertIn("a.py:1", message)


class EngineDropsUnboundResultsTests(unittest.TestCase):
    """A future detector bug that manages to emit an unbound role must never
    reach design-patterns.json — the engine catches it, not just the
    detector's own discipline."""

    def test_a_rogue_detector_emitting_an_empty_role_is_dropped_with_a_limitation(self) -> None:
        wrapper = cls("w", "Wrapper")
        graph = CodeGraph([wrapper], [])

        def rogue_detector(_graph: CodeGraph):
            broken = PatternResult(
                pattern_id="adapter", status="detected", confidence="medium",
                primary_location=Location(file="a.py", line=5),
                roles={"target": "Target", "adapter": ""},  # adapter role never got bound
            )
            return [(wrapper.id, broken)]

        results, limitations = run_engine(graph, load_catalog(), {"adapter": rogue_detector})
        self.assertEqual([], results)
        self.assertEqual(1, len(limitations))
        self.assertIn("adapter", limitations[0])
        self.assertIn("role", limitations[0])

    def test_a_well_formed_detector_result_survives(self) -> None:
        wrapper = cls("w", "Wrapper")
        target = cls("t", "Target")
        graph = CodeGraph([wrapper, target], [])

        def good_detector(_graph: CodeGraph):
            ok = PatternResult(
                pattern_id="adapter", status="detected", confidence="medium",
                primary_location=Location(file="a.py", line=5),
                roles={"target": "Target", "adapter": "Wrapper"},
            )
            return [(wrapper.id, ok)]

        results, limitations = run_engine(graph, load_catalog(), {"adapter": good_detector})
        self.assertEqual(1, len(results))
        self.assertEqual([], limitations)

    def test_detector_registered_for_an_unknown_catalog_pattern_raises(self) -> None:
        graph = CodeGraph([], [])
        with self.assertRaises(ValueError):
            run_engine(graph, load_catalog(), {"not-a-real-pattern": lambda g: []})


if __name__ == "__main__":
    unittest.main()

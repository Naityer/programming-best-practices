from __future__ import annotations

import unittest

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.confidence import compute_confidence  # noqa: E402
from design_patterns.evidence import Evidence  # noqa: E402
from design_patterns.ir import CodeGraph, Entity, Relation  # noqa: E402


def cls(entity_id: str, name: str, *, language: str = "python", kind: str = "class", file: str = "a.py") -> Entity:
    return Entity(id=entity_id, language=language, kind=kind, name=name, qualified_name=name, file=file, line=1)


class EntityRelationTests(unittest.TestCase):
    def test_entity_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            Entity(id="x", language="python", kind="widget", name="X", qualified_name="X", file="a.py", line=1)

    def test_relation_rejects_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            Relation(type="FRIENDS_WITH", source_id="a", target_id="b")

    def test_relation_requires_a_target(self) -> None:
        with self.assertRaises(ValueError):
            Relation(type="CALLS", source_id="a")


class CodeGraphIndexTests(unittest.TestCase):
    def test_indices_and_navigation(self) -> None:
        a, b = cls("a", "A"), cls("b", "B")
        graph = CodeGraph([a, b], [Relation(type="INHERITS", source_id="a", target_id="b")])
        self.assertEqual(graph.by_kind["class"], [a, b])
        self.assertEqual(graph.outgoing("a", "INHERITS")[0].target_id, "b")
        self.assertEqual(graph.incoming("b", "INHERITS")[0].source_id, "a")
        self.assertEqual(graph.resolve_by_name("a")[0].id, "a")
        self.assertIsNone(graph.entity("missing"))

    def test_frontend_level_defaults_to_b(self) -> None:
        graph = CodeGraph([], [])
        self.assertEqual(graph.frontend_level, "B")


class LanguageIndependenceTests(unittest.TestCase):
    """The engine and every detector must operate purely on the IR — never on
    `Entity.language` — so one detector works for any frontend (spec §3,
    §31.6). Proven here by running a detector against a synthetic graph built
    with language="java" and no frontend involved at all.
    """

    def test_adapter_detector_fires_on_a_hand_built_java_labelled_graph(self) -> None:
        from design_patterns.detectors.structural import detect_adapter

        target = cls("target", "PaymentGateway", language="java", kind="interface")
        target_method = Entity(
            id="target.pay", language="java", kind="method", name="pay",
            qualified_name="PaymentGateway.pay", file="a.java", line=2,
        )
        adaptee = cls("adaptee", "LegacyGateway", language="java")
        adapter = cls("adapter", "LegacyGatewayAdapter", language="java")
        adapter_method = Entity(
            id="adapter.pay", language="java", kind="method", name="pay",
            qualified_name="LegacyGatewayAdapter.pay", file="a.java", line=10,
        )
        adaptee_field = Entity(
            id="adapter.field", language="java", kind="field", name="legacy",
            qualified_name="LegacyGatewayAdapter.legacy", file="a.java", line=9,
        )
        relations = [
            Relation(type="CONTAINS", source_id="target", target_id="target.pay"),
            Relation(type="IMPLEMENTS", source_id="adapter", target_id="target"),
            Relation(type="CONTAINS", source_id="adapter", target_id="adapter.pay"),
            Relation(type="CONTAINS", source_id="adapter", target_id="adapter.field", detail="legacy"),
            Relation(type="REFERENCES", source_id="adapter.field", target_id="adaptee"),
            Relation(type="DELEGATES_TO", source_id="adapter.pay", target_id="adaptee", detail="charge"),
        ]
        graph = CodeGraph(
            [target, target_method, adaptee, adapter, adapter_method, adaptee_field],
            relations, frontend_level="A",
        )
        hits = detect_adapter(graph)
        self.assertEqual(1, len(hits))
        _, result = hits[0]
        self.assertEqual("adapter", result.pattern_id)
        self.assertEqual("LegacyGatewayAdapter", result.roles["adapter"])
        self.assertEqual("PaymentGateway", result.roles["target"])
        self.assertEqual("LegacyGateway", result.roles["adaptee"])


class ConfidenceInvariantTests(unittest.TestCase):
    def test_level_c_is_always_low(self) -> None:
        evidence = [Evidence("hard", "x"), Evidence("behavioral", "y"), Evidence("behavioral", "z")]
        self.assertEqual("low", compute_confidence(
            all_hard_satisfied=True, evidence=evidence, frontend_level="C",
        ))

    def test_missing_hard_is_low(self) -> None:
        self.assertEqual("low", compute_confidence(
            all_hard_satisfied=False, evidence=[], frontend_level="B",
        ))

    def test_unresolved_symbols_is_low(self) -> None:
        self.assertEqual("low", compute_confidence(
            all_hard_satisfied=True, evidence=[], frontend_level="B", symbols_resolved=False,
        ))

    def test_contradiction_forces_low(self) -> None:
        evidence = [Evidence("hard", "x"), Evidence("contradiction", "looks like Proxy instead")]
        self.assertEqual("low", compute_confidence(
            all_hard_satisfied=True, evidence=evidence, frontend_level="B",
        ))

    def test_all_hard_zero_behavioral_is_this_cortes_ceiling_medium(self) -> None:
        self.assertEqual("medium", compute_confidence(
            all_hard_satisfied=True, evidence=[Evidence("hard", "x")], frontend_level="B",
        ))

    def test_one_behavioral_is_still_medium(self) -> None:
        evidence = [Evidence("hard", "x"), Evidence("behavioral", "y")]
        self.assertEqual("medium", compute_confidence(
            all_hard_satisfied=True, evidence=evidence, frontend_level="B",
        ))

    def test_two_behavioral_reaches_high(self) -> None:
        evidence = [Evidence("hard", "x"), Evidence("behavioral", "y"), Evidence("behavioral", "z")]
        self.assertEqual("high", compute_confidence(
            all_hard_satisfied=True, evidence=evidence, frontend_level="B",
        ))

    def test_supporting_evidence_never_moves_the_tier(self) -> None:
        """The whole point of this module (see its docstring): a class name
        or comment can never elevate confidence, because compute_confidence
        never even counts `supporting` evidence — it is invisible to the tier
        calculation regardless of how much of it is present."""
        without_supporting = compute_confidence(
            all_hard_satisfied=True, evidence=[Evidence("hard", "x")], frontend_level="B",
        )
        with_lots_of_supporting = compute_confidence(
            all_hard_satisfied=True,
            evidence=[Evidence("hard", "x")] + [Evidence("supporting", f"name hint {i}") for i in range(50)],
            frontend_level="B",
        )
        self.assertEqual(without_supporting, with_lots_of_supporting)
        self.assertNotEqual("high", with_lots_of_supporting)


if __name__ == "__main__":
    unittest.main()

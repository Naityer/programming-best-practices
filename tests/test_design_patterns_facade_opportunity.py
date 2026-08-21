import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.ir import CodeGraph, Entity, Relation
from design_patterns.opportunities import detect_opportunities


def graph(shared_count=2):
    entities = [
        Entity("a", "synthetic", "class", "Auth", "Auth", "m.py", 1),
        Entity("b", "synthetic", "class", "Billing", "Billing", "m.py", 2),
        Entity("c", "synthetic", "class", "Logger", "Logger", "m.py", 3),
        Entity("x", "synthetic", "function", "one", "one", "m.py", 10),
        Entity("y", "synthetic", "function", "two", "two", "m.py", 20),
        Entity("am", "synthetic", "method", "check", "Auth.check", "m.py", 4),
        Entity("bm", "synthetic", "method", "charge", "Billing.charge", "m.py", 5),
        Entity("cm", "synthetic", "method", "write", "Logger.write", "m.py", 6),
    ]
    relations = [
        Relation("CONTAINS", "a", target_id="am"),
        Relation("CONTAINS", "b", target_id="bm"),
        Relation("CONTAINS", "c", target_id="cm"),
        Relation("CALLS", "x", target_id="am"),
        Relation("CALLS", "x", target_id="bm"),
        Relation("CALLS", "y", target_id="am"),
        Relation("CALLS", "y", target_id="bm"),
    ]
    if shared_count == 1:
        relations.pop()
    return CodeGraph(entities, relations)


class FacadeOpportunityTests(unittest.TestCase):
    def test_repeated_shared_subsystem_orchestration_is_facade_opportunity(self):
        results, limitations = detect_opportunities(graph())
        self.assertFalse(limitations)
        self.assertEqual(["facade"], [result.pattern_id for result in results])
        self.assertEqual("refactor-opportunity", results[0].status)
        self.assertEqual("medium", results[0].confidence)

    def test_one_shared_subsystem_is_not_enough(self):
        results, _ = detect_opportunities(graph(shared_count=1))
        self.assertEqual([], results)


if __name__ == "__main__":
    unittest.main()

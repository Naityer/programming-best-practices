import unittest
from tests.helpers import scripts_on_path
scripts_on_path()
from design_patterns.ir import CodeGraph, Entity, Relation
from design_patterns.opportunities import detect_opportunities

def build(count=2):
    def e(i, kind, name, qualified, line):
        return Entity(id=i, language="synthetic", kind=kind, name=name, qualified_name=qualified, file="m.py", line=line)
    entities = [e("p", "class", "Producer", "Producer", 1), e("a", "class", "A", "A", 2), e("b", "class", "B", "B", 3), e("pm", "method", "publish", "Producer.publish", 4), e("am", "method", "update", "A.update", 5), e("bm", "method", "update", "B.update", 6)]
    relations = [Relation("CONTAINS", "p", target_id="pm"), Relation("CONTAINS", "a", target_id="am"), Relation("CONTAINS", "b", target_id="bm"), Relation("CALLS", "pm", target_id="am")]
    if count > 1:
        relations.append(Relation("CALLS", "pm", target_id="bm"))
    return CodeGraph(entities, relations)

class ObserverOpportunityTests(unittest.TestCase):
    def test_direct_calls_to_two_concrete_consumers(self):
        results, limitations = detect_opportunities(build())
        self.assertFalse(limitations)
        self.assertEqual(["observer"], [r.pattern_id for r in results])
    def test_one_consumer_is_not_enough(self):
        self.assertEqual([], detect_opportunities(build(1))[0])

if __name__ == "__main__":
    unittest.main()

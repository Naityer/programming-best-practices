import unittest
from tests.helpers import scripts_on_path
scripts_on_path()
from design_patterns.additional_opportunities import detect_additional_opportunities
from design_patterns.ir import CodeGraph, Entity, Relation

def e(i, kind, name, qname, line):
    return Entity(id=i, language="synthetic", kind=kind, name=name, qualified_name=qname, file="case.py", line=line)

class AdditionalOpportunityTests(unittest.TestCase):
    def test_iterator_requires_two_traversals_of_same_collection(self):
        entities = [e("a", "class", "Aggregate", "Aggregate", 1), e("f", "field", "items", "Aggregate.items", 2), e("m1", "method", "sum", "Aggregate.sum", 3), e("m2", "method", "find", "Aggregate.find", 4)]
        relations = [Relation("CONTAINS", "a", target_id="f"), Relation("CONTAINS", "a", target_id="m1"), Relation("CONTAINS", "a", target_id="m2"), Relation("ITERATES", "m1", target_id="f"), Relation("ITERATES", "m2", target_id="f")]
        self.assertIn("iterator", [r.pattern_id for r in detect_additional_opportunities(CodeGraph(entities, relations))])
        self.assertNotIn("iterator", [r.pattern_id for r in detect_additional_opportunities(CodeGraph(entities, relations[:-1]))])

    def test_mediator_requires_dense_three_way_references(self):
        entities = [e(i, "class", i.upper(), i.upper(), n) for n, i in enumerate("abc", 1)]
        relations = []
        line = 10
        for source, targets in {"a": "bc", "b": "ac", "c": "ab"}.items():
            for target in targets:
                field = f"{source}{target}"
                entities.append(e(field, "field", target, f"{source.upper()}.{target}", line)); line += 1
                relations += [Relation("CONTAINS", source, target_id=field), Relation("REFERENCES", field, target_id=target)]
        self.assertIn("mediator", [r.pattern_id for r in detect_additional_opportunities(CodeGraph(entities, relations))])

    def test_template_method_requires_two_shared_steps_across_classes(self):
        entities = [e("a", "class", "A", "A", 1), e("b", "class", "B", "B", 2), e("ar", "method", "run", "A.run", 3), e("a1", "method", "load", "A.load", 4), e("a2", "method", "save", "A.save", 5), e("br", "method", "run", "B.run", 6), e("b1", "method", "load", "B.load", 7), e("b2", "method", "save", "B.save", 8)]
        relations = [Relation("CONTAINS", "a", target_id="ar"), Relation("CONTAINS", "a", target_id="a1"), Relation("CONTAINS", "a", target_id="a2"), Relation("CONTAINS", "b", target_id="br"), Relation("CONTAINS", "b", target_id="b1"), Relation("CONTAINS", "b", target_id="b2"), Relation("CALLS", "ar", target_id="a1"), Relation("CALLS", "ar", target_id="a2"), Relation("CALLS", "br", target_id="b1"), Relation("CALLS", "br", target_id="b2")]
        self.assertIn("template_method", [r.pattern_id for r in detect_additional_opportunities(CodeGraph(entities, relations))])

if __name__ == "__main__": unittest.main()

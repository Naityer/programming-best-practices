import textwrap
import unittest
from pathlib import Path
from tests.helpers import scripts_on_path
scripts_on_path()
from design_patterns.frontends.python import PythonFrontend
from design_patterns.ir import CodeGraph
from design_patterns.misimplementations import detect_misimplementations

def detect(source):
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("sample.py"))
    relations, _ = frontend.build_relations([unit])
    graph = CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)
    return [result for _, result in detect_misimplementations(graph)]

class MisimplementationTests(unittest.TestCase):
    def test_adapter_with_adaptee_but_without_delegation(self):
        results = detect('''
            from abc import ABC, abstractmethod
            class Target(ABC):
                @abstractmethod
                def request(self): pass
            class Legacy:
                def old_request(self): return 1
            class BrokenAdapter(Target):
                def __init__(self, adaptee: Legacy): self.adaptee = adaptee
                def request(self): return 0
        ''')
        self.assertEqual(["adapter"], [r.pattern_id for r in results])
        self.assertTrue(results[0].refactoring["steps"])

    def test_builder_without_terminal_product(self):
        results = detect('''
            class BrokenBuilder:
                def with_a(self): return self
                def with_b(self): return self
        ''')
        self.assertEqual(["builder"], [r.pattern_id for r in results])

    def test_singleton_cache_without_construction(self):
        results = detect('''
            class BrokenSingleton:
                def __init__(self): self._cache = {}
                def instance(self, key):
                    self._cache.setdefault(key, None)
                    return self._cache[key]
        ''')
        self.assertEqual(["singleton"], [r.pattern_id for r in results])

    def test_subject_collection_without_notification(self):
        results = detect('''
            class BrokenSubject:
                def __init__(self): self.observers = []
                def attach(self, observer): self.observers.append(observer)
        ''')
        self.assertEqual(["observer"], [r.pattern_id for r in results])

    def test_names_without_partial_structure_emit_nothing(self):
        results = detect('''
            class Adapter: pass
            class Builder: pass
            class Singleton: pass
            class Subject: pass
        ''')
        self.assertEqual([], results)

if __name__ == "__main__": unittest.main()

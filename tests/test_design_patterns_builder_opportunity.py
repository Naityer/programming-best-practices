import textwrap
import unittest
from pathlib import Path
from tests.helpers import scripts_on_path
scripts_on_path()
from design_patterns.frontends.python import PythonFrontend
from design_patterns.ir import CodeGraph
from design_patterns.opportunities import detect_opportunities

def detect(source):
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("builder_case.py"))
    relations, _ = frontend.build_relations([unit])
    graph = CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)
    return [result for result in detect_opportunities(graph)[0] if result.pattern_id == "builder"]

PRODUCT = '''
    class Report:
        def __init__(self, title, body, author, theme):
            self.title = title
            self.body = body
            self.author = author
            self.theme = theme
'''

class BuilderOpportunityTests(unittest.TestCase):
    def test_complex_product_constructed_at_two_class_sites(self):
        results = detect(PRODUCT + '''
            class Api:
                def make(self): return Report("t", "b", "a", "dark")
            class Cli:
                def make(self): return Report("t", "b", "a", "light")
        ''')
        self.assertEqual(1, len(results))
        self.assertTrue(results[0].refactoring["steps"])

    def test_one_construction_site_is_not_repetition(self):
        results = detect(PRODUCT + '''
            class Api:
                def make(self): return Report("t", "b", "a", "dark")
        ''')
        self.assertEqual([], results)

if __name__ == "__main__": unittest.main()

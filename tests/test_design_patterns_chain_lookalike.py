from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.behavioral import detect_chain_of_responsibility  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class ChainLookalikeTests(unittest.TestCase):
    def test_wrapper_to_concrete_sibling_is_not_chain(self) -> None:
        graph = build_graph("""
            class Handler:
                def handle(self):
                    raise NotImplementedError
            class RealHandler(Handler):
                def handle(self):
                    return "done"
            class Wrapper(Handler):
                def __init__(self, real: RealHandler):
                    self.real = real
                def handle(self):
                    return self.real.handle()
        """)
        self.assertEqual([], detect_chain_of_responsibility(graph))

    def test_next_handler_typed_as_interface_is_chain(self) -> None:
        graph = build_graph("""
            class Handler:
                def handle(self):
                    raise NotImplementedError
            class ConcreteHandler(Handler):
                def __init__(self, next_handler: Handler):
                    self.next_handler = next_handler
                def handle(self):
                    return self.next_handler.handle()
        """)
        self.assertTrue(detect_chain_of_responsibility(graph))


if __name__ == "__main__":
    unittest.main()

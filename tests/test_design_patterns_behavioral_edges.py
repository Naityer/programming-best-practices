from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.behavioral import (  # noqa: E402
    detect_chain_of_responsibility,
    detect_command,
    detect_iterator,
    detect_mediator,
    detect_memento,
    detect_observer,
)
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class BehavioralPartialCoverageTests(unittest.TestCase):
    def test_handler_without_next_handler_is_withheld(self) -> None:
        graph = build_graph("""
            class Handler:
                def handle(self):
                    raise NotImplementedError
            class ConcreteHandler(Handler):
                def handle(self):
                    return "done"
        """)
        self.assertEqual([], detect_chain_of_responsibility(graph))

    def test_command_without_invoker_is_withheld(self) -> None:
        graph = build_graph("""
            class Command:
                def execute(self):
                    raise NotImplementedError
            class SaveCommand(Command):
                def execute(self):
                    return "saved"
        """)
        self.assertEqual([], detect_command(graph))

    def test_iterator_without_collection_back_reference_is_withheld(self) -> None:
        graph = build_graph("""
            class Cursor:
                pass
            class Aggregate:
                def iterator(self):
                    return Cursor()
        """)
        self.assertEqual([], detect_iterator(graph))

    def test_mediator_without_colleague_back_references_is_withheld(self) -> None:
        graph = build_graph("""
            class Mediator:
                def __init__(self, left, right):
                    self.left = left
                    self.right = right
            class Left:
                pass
            class Right:
                pass
        """)
        self.assertEqual([], detect_mediator(graph))

    def test_memento_without_caretaker_is_withheld(self) -> None:
        graph = build_graph("""
            class Snapshot:
                pass
            class Editor:
                def snapshot(self):
                    return Snapshot()
        """)
        self.assertEqual([], detect_memento(graph))

    def test_observer_without_fan_out_notification_is_withheld(self) -> None:
        graph = build_graph("""
            class Subject:
                def __init__(self, observers):
                    self.observers = observers
                def state(self):
                    return "ready"
        """)
        self.assertEqual([], detect_observer(graph))


if __name__ == "__main__":
    unittest.main()

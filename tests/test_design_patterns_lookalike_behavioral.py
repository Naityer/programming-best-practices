from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.behavioral import (  # noqa: E402
    detect_command,
    detect_memento,
    detect_mediator,
    detect_observer,
    detect_state,
    detect_strategy,
    detect_template_method,
    detect_visitor,
)
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class BehavioralLookalikeTests(unittest.TestCase):
    def test_observer_fanout_is_not_mediator(self) -> None:
        graph = build_graph("""
            class Observer:
                def update(self):
                    pass
            class Subject:
                def __init__(self, observers):
                    self.observers = []
                def subscribe(self, observer):
                    self.observers.append(observer)
                def notify(self):
                    for observer in self.observers:
                        observer.update()
        """)
        self.assertTrue(detect_observer(graph))
        self.assertEqual([], detect_mediator(graph))

    def test_template_sequence_is_not_strategy(self) -> None:
        graph = build_graph("""
            class Process:
                def run(self):
                    self.prepare()
                    self.execute()
                def prepare(self):
                    raise NotImplementedError
                def execute(self):
                    raise NotImplementedError
            class ImportProcess(Process):
                def prepare(self):
                    return "prepared"
        """)
        self.assertTrue(detect_template_method(graph))
        self.assertEqual([], detect_strategy(graph))

    def test_visitor_dispatch_is_not_command(self) -> None:
        graph = build_graph("""
            class Visitor:
                def visit_first(self, element):
                    return element
                def visit_second(self, element):
                    return element
            class First:
                def accept(self, visitor: Visitor):
                    return visitor.visit_first(self)
            class Second:
                def accept(self, visitor: Visitor):
                    return visitor.visit_second(self)
        """)
        self.assertTrue(detect_visitor(graph))
        self.assertEqual([], detect_command(graph))

    def test_memento_snapshot_is_not_state(self) -> None:
        graph = build_graph("""
            class Snapshot:
                pass
            class Editor:
                def snapshot(self):
                    return Snapshot()
            class History:
                def __init__(self, snapshot: Snapshot):
                    self.snapshot = snapshot
        """)
        self.assertTrue(detect_memento(graph))
        self.assertEqual([], detect_state(graph))

    def test_command_receiver_is_not_mediator(self) -> None:
        graph = build_graph("""
            class Command:
                def execute(self):
                    raise NotImplementedError
            class Receiver:
                def save(self):
                    return "saved"
            class SaveCommand(Command):
                def __init__(self, receiver: Receiver):
                    self.receiver = receiver
                def execute(self):
                    return self.receiver.save()
            class Invoker:
                def __init__(self, command: Command):
                    self.command = command
        """)
        self.assertTrue(detect_command(graph))
        self.assertEqual([], detect_mediator(graph))

    def test_strategy_without_transitions_is_not_state(self) -> None:
        graph = build_graph("""
            class Algorithm:
                def run(self):
                    raise NotImplementedError
            class Fast(Algorithm):
                def run(self):
                    return "fast"
            class Safe(Algorithm):
                def run(self):
                    return "safe"
            class Context:
                def __init__(self, algorithm: Algorithm):
                    self.algorithm = algorithm
                def run(self):
                    return self.algorithm.run()
        """)
        self.assertTrue(detect_strategy(graph))
        self.assertEqual([], detect_state(graph))


if __name__ == "__main__":
    unittest.main()

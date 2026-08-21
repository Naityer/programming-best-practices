from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.catalog import load_catalog  # noqa: E402
from design_patterns.detectors import registry  # noqa: E402
from design_patterns.detectors.structural import detect_adapter, detect_decorator, detect_proxy  # noqa: E402
from design_patterns.engine import run_engine  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, limitations = frontend.build_relations([unit])
    if limitations:
        raise AssertionError(limitations)
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class AdapterDecoratorProxyCoverageTests(unittest.TestCase):
    def test_translated_contract_is_adapter_only(self) -> None:
        graph = build_graph("""
            class Target:
                def request(self, data):
                    raise NotImplementedError

            class LegacyService:
                def legacy_request(self, payload):
                    return payload

            class ServiceAdapter(Target):
                def __init__(self, service: LegacyService):
                    self.service = service
                def request(self, data):
                    return self.service.legacy_request({"data": data})
        """)
        self.assertEqual(1, len(detect_adapter(graph)))
        self.assertEqual([], detect_decorator(graph))
        self.assertEqual([], detect_proxy(graph))

    def test_same_contract_is_ambiguous_between_decorator_and_proxy(self) -> None:
        graph = build_graph("""
            class Service:
                def operation(self):
                    raise NotImplementedError

            class RealService(Service):
                def operation(self):
                    return "real"

            class WrappedService(Service):
                def __init__(self, real: RealService):
                    self.real = real
                def operation(self):
                    return self.real.operation()
        """)
        results, _ = run_engine(graph, load_catalog(), registry())
        matches = [result for result in results if result.roles.get("proxy") == "WrappedService"
                   or result.roles.get("decorator") == "WrappedService"]
        self.assertEqual(1, len(matches))
        self.assertEqual("ambiguous", matches[0].status)
        self.assertTrue(matches[0].contradictions)

    def test_name_only_adapter_is_not_a_pattern(self) -> None:
        graph = build_graph("""
            class ReportAdapter:
                def render(self):
                    return "report"
        """)
        self.assertEqual([], detect_adapter(graph))
        self.assertEqual([], detect_decorator(graph))
        self.assertEqual([], detect_proxy(graph))

    def test_wrapper_without_adaptee_is_partial_and_withheld(self) -> None:
        graph = build_graph("""
            class Target:
                def request(self):
                    raise NotImplementedError

            class IncompleteAdapter(Target):
                def request(self):
                    return "not delegated"
        """)
        self.assertEqual([], detect_adapter(graph))
        self.assertEqual([], detect_decorator(graph))
        self.assertEqual([], detect_proxy(graph))


if __name__ == "__main__":
    unittest.main()

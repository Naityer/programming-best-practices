from __future__ import annotations

import unittest

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.model import Location, PatternResult  # noqa: E402
from design_patterns.uml import artifact_name, build_uml_contract, render_mermaid, render_plantuml  # noqa: E402


def adapter_result() -> PatternResult:
    return PatternResult(
        pattern_id="adapter", status="detected", confidence="medium",
        primary_location=Location(file="src/payment.py", line=42),
        roles={"target": "PaymentGateway", "adapter": "LegacyGatewayAdapter", "adaptee": "LegacyGateway"},
    )


class MermaidTests(unittest.TestCase):
    def test_renders_class_diagram_with_bound_role_names(self) -> None:
        text = render_mermaid(adapter_result())
        self.assertTrue(text.startswith("classDiagram"))
        self.assertIn("class PaymentGateway", text)
        self.assertIn("<<interface>> PaymentGateway", text)
        self.assertIn("class LegacyGatewayAdapter", text)
        self.assertIn("class LegacyGateway", text)
        self.assertIn("LegacyGatewayAdapter ..|> PaymentGateway : implements", text)
        self.assertIn('LegacyGatewayAdapter "1" --> "1" LegacyGateway : wraps', text)

    def test_never_renders_a_role_placeholder_only_real_bound_names(self) -> None:
        text = render_mermaid(adapter_result())
        self.assertNotIn("target", text.split("\n")[0])
        for role_name in ("target", "adapter", "adaptee"):
            self.assertNotIn(f"class {role_name}", text)


class PlantUmlTests(unittest.TestCase):
    def test_renders_start_and_end_markers(self) -> None:
        text = render_plantuml(adapter_result())
        self.assertTrue(text.startswith("@startuml"))
        self.assertTrue(text.rstrip().endswith("@enduml"))
        self.assertIn("interface PaymentGateway", text)
        self.assertNotIn("class PaymentGateway", text)
        self.assertIn("LegacyGatewayAdapter ..|> PaymentGateway : implements", text)
        self.assertIn('LegacyGatewayAdapter "1" --> "1" LegacyGateway : wraps', text)


class StructuredUmlContractTests(unittest.TestCase):
    def test_adapter_preserves_unbound_client_and_typed_relations(self) -> None:
        uml = build_uml_contract(adapter_result())
        nodes = {node["role"]: node for node in uml["nodes"]}
        self.assertEqual("UML 2.5.1", uml["notation"])
        self.assertFalse(nodes["client"]["bound"])
        self.assertIsNone(nodes["client"]["name"])
        self.assertEqual("interface", nodes["target"]["classifier"])
        relations = {(rel["source_role"], rel["target_role"]): rel for rel in uml["relationships"]}
        self.assertEqual("dependency", relations[("client", "target")]["type"])
        self.assertEqual("realization", relations[("adapter", "target")]["type"])
        wraps = relations[("adapter", "adaptee")]
        self.assertEqual("association", wraps["type"])
        self.assertEqual("1", wraps["source_multiplicity"])
        self.assertEqual("1", wraps["target_multiplicity"])

    def test_plain_reference_is_not_promoted_to_composition(self) -> None:
        uml = build_uml_contract(adapter_result())
        self.assertNotIn("composition", {rel["type"] for rel in uml["relationships"]})


class FacadeDynamicSubsystemTests(unittest.TestCase):
    def test_facade_edges_include_every_numbered_subsystem_role(self) -> None:
        result = PatternResult(
            pattern_id="facade", status="detected", confidence="medium",
            primary_location=Location(file="a.py", line=1),
            roles={"facade": "OrderFacade", "subsystem_1": "Inventory", "subsystem_2": "Billing"},
        )
        text = render_mermaid(result)
        self.assertIn("OrderFacade --> Inventory : contains", text)
        self.assertIn("OrderFacade --> Billing : contains", text)


class ArtifactNameTests(unittest.TestCase):
    def test_zero_padded_sequence(self) -> None:
        self.assertEqual("adapter-001", artifact_name(adapter_result(), 1))
        self.assertEqual("adapter-012", artifact_name(adapter_result(), 12))


class NoCanonicalEdgesFallbackTests(unittest.TestCase):
    def test_pattern_with_no_canonical_edges_still_lists_its_roles(self) -> None:
        result = PatternResult(
            pattern_id="not-a-real-pattern", status="detected", confidence="low",
            primary_location=Location(file="a.py", line=1), roles={"whatever": "SomeClass"},
        )
        text = render_mermaid(result)
        self.assertIn("class SomeClass", text)


if __name__ == "__main__":
    unittest.main()

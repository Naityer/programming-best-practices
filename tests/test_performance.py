"""Tests de la categoría `performance`: planificación, medición y comparación."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SKILL, load_module

scripts = SKILL / "scripts"
sys.path.insert(0, str(scripts))
plan_audit = load_module("plan_audit", scripts / "plan_audit.py")
measure_artifacts = load_module("measure_artifacts", scripts / "measure_artifacts.py")
compare_perf_baseline = load_module("compare_perf_baseline", scripts / "compare_perf_baseline.py")
normalize_tool_output = load_module("normalize_tool_output", scripts / "normalize_tool_output.py")


def _js_project(root: Path, *, with_dist: bool = True, scripts_map: dict | None = None) -> None:
    (root / "package.json").write_text(
        json.dumps({"scripts": scripts_map or {"build": "vite build", "test": "vitest"}}),
        encoding="utf-8",
    )
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    (root / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    if with_dist:
        dist = root / "dist" / "assets"
        dist.mkdir(parents=True)
        (dist / "index.js").write_text("x" * 500, encoding="utf-8")
        (dist / "index.css").write_text("y" * 100, encoding="utf-8")
        (dist / "index.js.map").write_text("z" * 9000, encoding="utf-8")


class PlanPerformanceTests(unittest.TestCase):
    def test_bundle_size_is_planned_from_standard_and_depends_on_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root)
            fast = {item["id"] for item in plan_audit.create_plan(root, "fast")["checks"]}
            standard = {item["id"]: item for item in plan_audit.create_plan(root, "standard")["checks"]}

            self.assertNotIn("js.bundle-size", fast)
            self.assertIn("js.bundle-size", standard)
            # Medir no tiene sentido sin haber construido antes.
            self.assertEqual(standard["js.bundle-size"]["depends_on"], ["js.build"])
            self.assertEqual(standard["js.bundle-size"]["category"], "performance")
            self.assertEqual(standard["js.build"]["category"], "performance")

    def test_build_declares_workspace_effects_and_measuring_does_not(self) -> None:
        """La autorización tiene que reflejar quién escribe de verdad."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root)
            checks = {item["id"]: item for item in plan_audit.create_plan(root, "standard")["checks"]}
            self.assertEqual(checks["js.build"]["workspace_effects"], "cache")
            self.assertEqual(checks["js.bundle-size"]["workspace_effects"], "none")
            # Medir sobre artefactos del disco es local: no debe pedir red.
            # Se excluye `web.runtime-probe`, que navega a una URL y por eso
            # declara `network` y exige `--allow-network` (y otras categorías la
            # necesitan legítimamente: `universal.osv` consulta la base de CVEs).
            for check in checks.values():
                if check["category"] == "performance" and check["id"] != "web.runtime-probe":
                    self.assertFalse(check["network"], f"{check['id']} no debería pedir red")

    def test_bundle_size_is_unavailable_without_a_build_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root, with_dist=False)
            checks = {item["id"]: item for item in plan_audit.create_plan(root, "standard")["checks"]}
            self.assertEqual(checks["js.bundle-size"]["status"], "unavailable")
            self.assertTrue(checks["js.bundle-size"]["reason"])

    def test_deep_adds_benchmarks_and_the_plan_stays_data_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root, scripts_map={"build": "vite build", "bench": "vitest bench"})
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            (root / "benchmarks").mkdir()
            deep = plan_audit.create_plan(root, "deep")["checks"]
            ids = {item["id"] for item in deep}
            self.assertIn("js.benchmark", ids)
            self.assertIn("python.benchmark", ids)
            for check in deep:
                self.assertIsInstance(check["argv"], list)
                for argument in check["argv"]:
                    self.assertIsInstance(argument, str)
                    self.assertNotIn(";", argument)   # nunca una cadena de shell


class MeasureArtifactsTests(unittest.TestCase):
    def test_measures_sizes_and_ignores_source_maps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root)
            document = measure_artifacts.measure(root / "dist", root)
            self.assertEqual(document["tool"], "bundle-size")
            self.assertEqual(document["file_count"], 2)          # el .map no cuenta
            self.assertEqual(document["total_bytes"], 600)
            self.assertEqual(document["by_extension"][".js"]["bytes"], 500)
            self.assertEqual(document["largest"][0]["path"], "assets/index.js")

    def test_normalizer_records_the_bundle_without_inventing_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root)
            report = root / "bundle.json"
            report.write_text(json.dumps(measure_artifacts.measure(root / "dist", root)), encoding="utf-8")
            result = normalize_tool_output.normalize("bundle-size", report, root)
            # Un tamaño no es un defecto sin nada con lo que compararlo.
            self.assertEqual(result["findings"], [])
            self.assertEqual(result["dimensions"]["performance"]["bundle"]["total_bytes"], 600)


class ComparePerfBaselineTests(unittest.TestCase):
    def test_reports_a_regression_when_a_measurement_gets_worse(self) -> None:
        result = compare_perf_baseline.compare(
            {"total_bytes": 2000, "load_ms": 100},
            {"total_bytes": 1000, "load_ms": 100},
            0.10,
        )
        self.assertEqual(len(result["findings"]), 1)
        finding = result["findings"][0]
        self.assertEqual(finding["category"], "performance")
        self.assertEqual(finding["rule_id"], "performance.regression")
        self.assertEqual(finding["severity"], "high")            # 2x peor
        self.assertEqual(result["dimensions"]["performance"]["regressions"], 1)

    def test_noise_inside_the_tolerance_is_not_a_regression(self) -> None:
        result = compare_perf_baseline.compare({"load_ms": 104}, {"load_ms": 100}, 0.10)
        self.assertEqual(result["findings"], [])

    def test_an_improvement_is_never_reported_as_a_finding(self) -> None:
        result = compare_perf_baseline.compare({"load_ms": 50}, {"load_ms": 100}, 0.10)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["dimensions"]["performance"]["improvements"], 1)

    def test_metrics_where_higher_is_better_are_compared_inverted(self) -> None:
        """Menos operaciones por segundo es PEOR, aunque el número baje."""
        worse = compare_perf_baseline.compare({"ops_per_second": 50}, {"ops_per_second": 100}, 0.10)
        self.assertEqual(len(worse["findings"]), 1)
        better = compare_perf_baseline.compare({"ops_per_second": 200}, {"ops_per_second": 100}, 0.10)
        self.assertEqual(better["findings"], [])

    def test_nested_documents_are_compared_leaf_by_leaf(self) -> None:
        result = compare_perf_baseline.compare(
            {"repos": {"atlas": {"list_ms": 900}}},
            {"repos": {"atlas": {"list_ms": 300}}},
            0.10,
        )
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["locations"][0]["file"], "repos.atlas.list_ms")

    def test_without_a_baseline_it_declares_a_limitation_instead_of_passing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current.json"
            current.write_text(json.dumps({"load_ms": 100}), encoding="utf-8")
            sys.argv = ["compare_perf_baseline.py", str(current)]
            self.assertEqual(compare_perf_baseline.main(), 0)


if __name__ == "__main__":
    unittest.main()


class WebRuntimeProbeTests(unittest.TestCase):
    """La sonda de navegador: el diagnóstico que detecta un bucle que no descansa."""

    def _document(self, **overrides) -> dict:
        target = {
            "url": "http://127.0.0.1:9/app", "reachable": True, "idle_seconds": 5,
            "idle_frames": 0, "idle_frames_per_second": 0.0, "idle_requests": 0,
            "long_tasks": 0, "dom_interactive_ms": 120, "load_ms": 300,
            "request_count": 4, "transferred_bytes": 1000, "dom_nodes": 50,
        }
        target.update(overrides)
        return {"schema_version": "1.0.0", "tool": "web-runtime",
                "targets": {"app": target}, "limitations": []}

    def test_a_loop_that_never_idles_is_reported_without_needing_a_baseline(self) -> None:
        findings, dimensions, _ = normalize_tool_output.parse_web_runtime(
            self._document(idle_frames=301, idle_frames_per_second=60.2), None,
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule_id"], "performance.idle_render_loop")
        self.assertEqual(findings[0]["severity"], "high")
        self.assertEqual(dimensions["performance"]["web_runtime"]["app"]["idle_frames"], 301)

    def test_a_quiet_page_produces_no_finding(self) -> None:
        findings, _, _ = normalize_tool_output.parse_web_runtime(self._document(), None)
        self.assertEqual(findings, [])

    def test_a_few_trailing_frames_are_not_reported(self) -> None:
        """Una transición terminando no es un bucle enloquecido."""
        findings, _, _ = normalize_tool_output.parse_web_runtime(
            self._document(idle_frames=12, idle_frames_per_second=2.4), None,
        )
        self.assertEqual(findings, [])

    def test_an_unreachable_target_is_a_limitation_not_a_pass(self) -> None:
        document = self._document()
        document["targets"]["app"] = {"url": "http://127.0.0.1:9/app", "reachable": False}
        document["limitations"] = ["app: No se pudo cargar"]
        findings, _, limitations = normalize_tool_output.parse_web_runtime(document, None)
        self.assertEqual(findings, [])          # no se inventa un veredicto
        self.assertEqual(len(limitations), 1)   # pero se declara que falta evidencia

    def test_probe_is_planned_only_in_deep_and_only_with_declared_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _js_project(root)
            without = {c["id"]: c for c in plan_audit.create_plan(root, "deep")["checks"]}
            self.assertEqual(without["web.runtime-probe"]["status"], "unavailable")
            self.assertIn(".perf-targets.json", without["web.runtime-probe"]["reason"])

            (root / ".perf-targets.json").write_text(
                json.dumps({"web": [{"name": "app", "url": "http://127.0.0.1:8000/"}]}), encoding="utf-8",
            )
            standard = {c["id"]: c for c in plan_audit.create_plan(root, "standard")["checks"]}
            deep = {c["id"]: c for c in plan_audit.create_plan(root, "deep")["checks"]}
            # Necesita un servicio levantado: no es algo de cada iteración.
            self.assertEqual(standard["web.runtime-probe"]["minimum_profile"], "deep")
            probe = deep["web.runtime-probe"]
            self.assertEqual(probe["category"], "performance")
            # Navega a una URL: exige --allow-network. Pero no escribe nada.
            self.assertTrue(probe["network"])
            self.assertEqual(probe["workspace_effects"], "none")


class ReportWiringTests(unittest.TestCase):
    """Un adaptador sin registrar deja la medicion fuera del informe."""

    def test_every_performance_adapter_reaches_the_report(self) -> None:
        build_report = load_module("build_report", scripts / "build_report.py")
        for kind in ("bundle-size", "pytest-benchmark", "web-runtime"):
            # Sin esto el check se ejecuta, pasa, y su medida se pierde: la
            # auditoria diria "correcto" sin haber mirado nada.
            self.assertIn(kind, normalize_tool_output.JSON_PARSERS,
                          f"{kind} no tiene adaptador")
            self.assertIn(kind, build_report.SUPPORTED_FORMATS,
                          f"{kind} no esta registrado en build_report")

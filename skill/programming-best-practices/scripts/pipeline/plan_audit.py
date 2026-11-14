#!/usr/bin/env python3
"""Create a deterministic FAST, STANDARD, or DEEP audit plan."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from detect_project import detect

PROFILE_RANK = {"fast": 1, "standard": 2, "deep": 3}


def _tool(inventory: dict[str, Any], name: str) -> str | None:
    item = inventory["tools"].get(name, {})
    return item.get("command") if item.get("status") == "available" else None


def _check(
    check_id: str,
    tool: str,
    category: str,
    argv: list[str] | None,
    *,
    ecosystem: str = "universal",
    minimum_profile: str = "fast",
    timeout: int = 300,
    required: bool = False,
    output_format: str = "text",
    workspace_effects: str = "none",
    network: bool = False,
    generated_code: bool = False,
    reason: str = "",
    environment: dict[str, str] | None = None,
    depends_on: list[str] | None = None,
    cwd: str = ".",
    gate: bool | None = None,
    effective_scope: str = "repository",
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "tool": tool,
        "category": category,
        "ecosystem": ecosystem,
        "minimum_profile": minimum_profile,
        "argv": argv or [],
        "timeout_seconds": timeout,
        "required": required,
        "gate": required if gate is None else gate,
        "effective_scope": effective_scope,
        "output_format": output_format,
        "workspace_effects": workspace_effects,
        "network": network,
        "generated_code": generated_code,
        "status": status or ("planned" if argv else "unavailable"),
        "reason": reason if not argv else "",
        "environment": environment or {},
        "depends_on": depends_on or [],
        "cwd": cwd,
    }


def _best_package(root: Path, package_files: list[str]) -> str | None:
    """Sin package.json en la raíz (monorrepo), el subpaquete con más scripts auditables, no el primero por orden alfabético."""
    wanted = {"test", "build", "typecheck", "lint"}

    def score(item: str) -> int:
        try:
            return len(wanted & set(json.loads((root / item).read_text(encoding="utf-8")).get("scripts", {})))
        except (OSError, json.JSONDecodeError, AttributeError):
            return 0

    ranked = sorted(package_files, key=lambda item: (-score(item), item))
    return ranked[0] if ranked else None


def _package_scripts(root: Path, configurations: list[str]) -> tuple[str | None, set[str]]:
    package_files = [item for item in configurations if item.endswith("package.json")]
    root_package = "package.json" if "package.json" in package_files else _best_package(root, package_files)
    if not root_package:
        return None, set()
    try:
        data = json.loads((root / root_package).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return root_package, set()
    scripts = data.get("scripts", {})
    return root_package, set(scripts) if isinstance(scripts, dict) else set()


def _python_checks(root: Path, inv: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    # Dos intérpretes distintos, y el orden importa:
    #
    #   `python`         → el del PROYECTO (detect_project prefiere su .venv).
    #   `python-runtime` → el que ejecuta LA SKILL (sys.executable).
    #
    # Para compilar y ejecutar los tests del repositorio auditado manda el suyo:
    # con el de la skill, `pytest` no encuentra el paquete que está auditando y
    # falla con ModuleNotFoundError. Eso se reportaría como "los tests fallan"
    # cuando en realidad no llegaron a arrancar — un falso positivo que acusa al
    # repositorio de un defecto que no tiene.
    #
    # (Los scripts propios de la skill —medir artefactos, sonda de navegador— sí
    # usan `python-runtime`: necesitan las dependencias de la skill, no las del
    # proyecto.)
    py = _tool(inv, "python") or _tool(inv, "python-runtime")
    configs = set(inv["configurations"])
    has_tests = any(item == "tests" or item.startswith("tests/") for item in _top_level_entries(root))
    checks = [
        _check("python.compile", "python", "correctness", [py, "-m", "compileall", "-q", "."] if py else None,
               ecosystem="python", required=True, workspace_effects="cache",
               reason="Python runtime is unavailable."),
    ]
    pytest_available = _tool(inv, "pytest") or (py if any(Path(item).name in {"pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"} for item in configs) else None)
    pytest_argv = [py, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"] if py and pytest_available and has_tests else None
    checks.append(_check("python.tests", "pytest", "tests", pytest_argv, ecosystem="python", required=has_tests,
                         workspace_effects="runtime", timeout=900,
                         reason="No tests detected or pytest is unavailable."))
    ruff = _tool(inv, "ruff")
    checks.append(_check("python.ruff", "ruff", "maintainability", [ruff, "check", "--no-cache", "--output-format", "json", "."] if ruff else None,
                         ecosystem="python", output_format="ruff-json", reason="Ruff is unavailable."))
    for type_tool in ("mypy", "pyright"):
        executable = _tool(inv, type_tool)
        if executable:
            # Si el proyecto ya declara QUÉ comprobar (`files`/`packages`/
            # `modules` en su config de mypy), se le deja mandar y no se le pasa
            # ninguna ruta. Pasar `.` a secas la sobreescribe y arrastra todo el
            # repositorio: sobre un layout `src/` normal eso hace que mypy vea
            # `conftest.py` dos veces bajo dos nombres de módulo y aborte con
            # "Source file found twice" — un fallo de la herramienta que se
            # reportaría como un defecto del código.
            argv = [executable]
            if type_tool == "mypy" and not _mypy_declares_targets(root, inv["configurations"]):
                argv.append(".")
            checks.append(_check(f"python.{type_tool}", type_tool, "correctness", argv, ecosystem="python", timeout=600))
            break
    if PROFILE_RANK[profile] >= 2:
        coverage = _tool(inv, "coverage")
        checks.append(_check("python.coverage-run", "coverage-py", "coverage",
                             [coverage, "run", "--branch", "-m", "pytest", "-q", "-p", "no:cacheprovider"] if coverage and has_tests else None,
                             ecosystem="python", minimum_profile="standard", output_format="text",
                             workspace_effects="runtime", timeout=1200,
                             environment={"COVERAGE_FILE": "{artifact}/.coverage"},
                             reason="coverage.py or tests are unavailable."))
        checks.append(_check("python.coverage-report", "coverage-py", "coverage",
                             [coverage, "json", "--data-file={artifact:python.coverage-run}/.coverage", "-o", "{artifact}/coverage.json"] if coverage and has_tests else None,
                             ecosystem="python", minimum_profile="standard", output_format="coverage-py",
                             workspace_effects="none", timeout=120,
                             depends_on=["python.coverage-run"],
                             reason="coverage.py or tests are unavailable."))
    if PROFILE_RANK[profile] >= 3:
        mutmut = _tool(inv, "mutmut")
        checks.append(_check("python.mutation", "mutmut", "test-strength", [mutmut, "run"] if mutmut else None,
                             ecosystem="python", minimum_profile="deep", output_format="mutmut",
                             workspace_effects="runtime", timeout=3600,
                             reason="mutmut is unavailable."))
        # `pytest-benchmark` es un plugin, no un ejecutable: `shutil.which` no lo
        # ve, así que la señal es que exista un directorio de benchmarks. Sin él,
        # `--benchmark-only` no seleccionaría nada y el check seria ruido.
        has_benchmarks = any(
            Path(item).name in {"benchmarks", "bench"} for item in _top_level_entries(root)
        )
        bench_argv = (
            [py, "-B", "-m", "pytest", "--benchmark-only", "-q", "-p", "no:cacheprovider",
             "--benchmark-json={artifact}/benchmark.json"]
            if py and has_benchmarks else None
        )
        checks.append(_check("python.benchmark", "pytest-benchmark", "performance", bench_argv,
                             ecosystem="python", minimum_profile="deep", output_format="pytest-benchmark",
                             workspace_effects="runtime", timeout=1800,
                             reason="No benchmarks/ directory or Python runtime is unavailable."))
    return checks


def _ordered_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordena por id, pero SIN adelantar un check a algo de lo que depende.

    Antes se ordenaba solo alfabéticamente, y eso rompía las dependencias que el
    propio plan declara: `python.coverage-report` va antes que
    `python.coverage-run` en el alfabeto, así que se ejecutaba primero, el
    ejecutor veía su prerequisito sin pasar y lo saltaba. Resultado: cobertura
    medida y luego tirada a la basura, en silencio y en cada ejecución.

    (`js.bundle-size` tras `js.build` funcionaba solo por suerte del alfabeto.)

    Orden topológico estable: se respeta el orden alfabético entre iguales, así
    que el plan sigue siendo determinista, que es lo que permite compararlo entre
    ejecuciones. Un ciclo entre dependencias no cuelga: se emite igualmente y el
    ejecutor lo saltará por prerequisito no cumplido.
    """
    by_id = {check["id"]: check for check in checks}
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def place(check_id: str) -> None:
        if check_id in placed or check_id in visiting:
            return          # ya colocado, o ciclo: no se insiste
        visiting.add(check_id)
        for dependency in by_id[check_id].get("depends_on", []):
            if dependency in by_id:
                place(dependency)
        visiting.discard(check_id)
        placed.add(check_id)
        ordered.append(by_id[check_id])

    for check_id in sorted(by_id):
        place(check_id)
    return ordered


def _mypy_declares_targets(root: Path, configurations: list[str]) -> bool:
    """`True` si el proyecto ya dice a mypy qué comprobar.

    Se mira `files`/`packages`/`modules` en `pyproject.toml`, `mypy.ini`,
    `.mypy.ini` o `setup.cfg`. Es una lectura de texto a propósito: leer TOML
    o INI de verdad no aporta nada aquí y ataría el planificador a un parser.
    """
    candidates = ("pyproject.toml", "mypy.ini", ".mypy.ini", "setup.cfg")
    for name in candidates:
        if name not in {Path(item).name for item in configurations} and not (root / name).is_file():
            continue
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "[tool.mypy]" not in text and "[mypy]" not in text:
            continue
        section = text.split("[tool.mypy]", 1)[-1].split("[mypy]", 1)[-1]
        if any(f"\n{key}" in f"\n{section}" for key in ("files", "packages", "modules")):
            return True
    return False


def _top_level_entries(root: Path) -> list[str]:
    try:
        return sorted(path.name for path in root.iterdir())
    except OSError:
        return []


def _javascript_checks(root: Path, inv: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    config, scripts = _package_scripts(root, inv["configurations"])
    ecosystem = next((item for item in inv["ecosystems"] if item["name"] == "javascript-typescript"), {})
    manager = (ecosystem.get("build_systems") or ["npm"])[0]
    project_dir = Path(config).parent.as_posix() if config else "."
    executable = _tool(inv, manager)
    run = [executable, "run"] if executable and manager == "npm" else ([executable] if executable else [])
    checks: list[dict[str, Any]] = []
    for name, category, required in (("typecheck", "correctness", True), ("lint", "maintainability", False), ("test", "tests", True)):
        argv = [*run, name] if run and name in scripts else None
        checks.append(_check(f"js.{name}", manager, category, argv, ecosystem="javascript-typescript",
                             required=required and bool(config), workspace_effects="cache" if name != "test" else "runtime",
                             timeout=1200, cwd=project_dir, reason=f"Package script '{name}' or {manager} is unavailable."))
    if PROFILE_RANK[profile] >= 2:
        # Tamaño de lo que se entrega al navegador. Dos pasos porque el reparto
        # de responsabilidades del plan lo exige: construir MUTA el árbol de
        # salida (`workspace_effects="cache"`, así que exige
        # `--allow-project-writes`), mientras que medir solo lee.
        build_argv = [*run, "build"] if run and "build" in scripts else None
        checks.append(_check("js.build", manager, "performance", build_argv,
                             ecosystem="javascript-typescript", minimum_profile="standard",
                             workspace_effects="cache", timeout=1800, cwd=project_dir,
                             reason=f"Package script 'build' or {manager} is unavailable."))
        python = _tool(inv, "python-runtime") or _tool(inv, "python")
        measure = str(Path(__file__).resolve().parent / "measure_artifacts.py")
        out_dir = _build_output_dir(root, project_dir)
        measure_argv = (
            [python, measure, "--root", str(root), "--dir", out_dir, "--output", "{artifact}/bundle-size.json"]
            if python and build_argv and out_dir else None
        )
        checks.append(_check("js.bundle-size", "bundle-size", "performance", measure_argv,
                             ecosystem="javascript-typescript", minimum_profile="standard",
                             output_format="bundle-size", workspace_effects="none", timeout=120,
                             depends_on=["js.build"], cwd=project_dir,
                             reason="No build script, Python runtime, or known output directory."))
    if PROFILE_RANK[profile] >= 3:
        stryker = _tool(inv, "stryker")
        checks.append(_check("js.mutation", "stryker", "test-strength", [stryker, "run"] if stryker else None,
                             ecosystem="javascript-typescript", minimum_profile="deep", output_format="stryker",
                             workspace_effects="runtime", timeout=3600, cwd=project_dir, reason="StrykerJS is unavailable."))
        bench_argv = [*run, "bench"] if run and "bench" in scripts else None
        checks.append(_check("js.benchmark", manager, "performance", bench_argv,
                             ecosystem="javascript-typescript", minimum_profile="deep",
                             workspace_effects="runtime", timeout=1800, cwd=project_dir,
                             reason="No 'bench' package script."))
    return checks


"""Objetivos de rendimiento declarados por el repositorio.

Formato de `.perf-targets.json`, en la raíz:

    {"web": [{"name": "mapa", "url": "http://127.0.0.1:8000/webui/graph.html"}]}

Un fichero versionado y no un argumento de línea de comandos porque una URL de
desarrollo es una convención DEL REPOSITORIO, igual que sus scripts de
`package.json`: viaja con el código, se revisa en el diff y no hay que
recordarla. Es el mismo principio que ya sigue el resto de la skill al leer la
configuración nativa del proyecto.
"""
PERF_TARGETS_FILE = ".perf-targets.json"


def _perf_targets(root: Path) -> dict[str, Any]:
    path = root / PERF_TARGETS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _web_runtime_check(root: Path, inv: dict[str, Any], profile: str) -> dict[str, Any]:
    """Sonda de navegador: ¿descansa la página cuando nadie la toca?

    Es el único check que necesita RED y un servicio ya levantado, así que
    `run_audit.py` lo salta salvo que se autorice explícitamente con
    `--allow-network`. Y por eso vive en DEEP: no es algo que deba correr en
    cada iteración.
    """
    targets = _perf_targets(root).get("web") or []
    python = _tool(inv, "python-runtime") or _tool(inv, "python")
    # Playwright es una librería, no un ejecutable en PATH: se comprueba
    # importándola con el mismo intérprete que ejecutaría la sonda.
    has_playwright = False
    if python:
        try:
            has_playwright = subprocess.run(
                [python, "-c", "import playwright"],
                capture_output=True, timeout=30, check=False,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            has_playwright = False

    argv = None
    reason = ""
    if not targets:
        reason = f"No hay objetivos web declarados en {PERF_TARGETS_FILE}."
    elif not python:
        reason = "No hay intérprete de Python disponible."
    elif not has_playwright:
        reason = "Playwright no está instalado (pip install playwright && playwright install chromium)."
    else:
        script = str(Path(__file__).resolve().parent / "probe_web_runtime.py")
        argv = [python, script, "--output", "{artifact}/web-runtime.json"]
        for target in targets:
            if not isinstance(target, dict) or not target.get("url"):
                continue
            argv += ["--url", str(target["url"]), "--name", str(target.get("name") or "target")]

    return _check(
        "web.runtime-probe", "web-runtime", "performance", argv,
        minimum_profile="deep", output_format="web-runtime",
        workspace_effects="none", network=True, timeout=600,
        reason=reason,
    )


# Convención de cada empaquetador. Se comprueba cuál existe de verdad en vez de
# suponer: medir un directorio equivocado daría un cero silencioso.
_BUILD_OUTPUT_DIRS = ("dist", "build", "out", ".output/public", ".next", "public/build")


def _build_output_dir(root: Path, project_dir: str) -> str | None:
    """Directorio de salida ya existente, relativo a `root`, o `None`."""
    base = (root / project_dir) if project_dir != "." else root
    for candidate in _BUILD_OUTPUT_DIRS:
        path = base / candidate
        if path.is_dir():
            return path.relative_to(root).as_posix()
    return None


def _simple_ecosystem_checks(inv: dict[str, Any], profile: str, name: str) -> list[dict[str, Any]]:
    tool = lambda value: _tool(inv, value)
    if name == "go":
        go = tool("go")
        checks = [
            _check("go.vet", "go", "correctness", [go, "vet", "./..."] if go else None, ecosystem=name, required=True, workspace_effects="cache", reason="Go is unavailable."),
            _check("go.tests", "go", "tests", [go, "test", "./..."] if go else None, ecosystem=name, required=True, workspace_effects="runtime", reason="Go is unavailable."),
        ]
        if PROFILE_RANK[profile] >= 2:
            checks.append(_check("go.coverage", "go", "coverage", [go, "test", "-coverprofile={artifact}/go-cover.out", "./..."] if go else None,
                                 ecosystem=name, minimum_profile="standard", output_format="go-cover", workspace_effects="runtime", reason="Go is unavailable."))
        return checks
    if name == "rust":
        cargo = tool("cargo")
        checks = [
            _check("rust.check", "cargo", "correctness", [cargo, "check", "--all-targets"] if cargo else None, ecosystem=name, required=True, workspace_effects="cache", reason="Cargo is unavailable."),
            _check("rust.clippy", "cargo", "maintainability", [cargo, "clippy", "--all-targets"] if cargo else None, ecosystem=name, workspace_effects="cache", reason="Cargo is unavailable."),
            _check("rust.tests", "cargo", "tests", [cargo, "test"] if cargo else None, ecosystem=name, required=True, workspace_effects="runtime", reason="Cargo is unavailable."),
        ]
        if PROFILE_RANK[profile] >= 2:
            llvm_cov = tool("cargo-llvm-cov")
            checks.append(_check("rust.coverage", "cargo-llvm-cov", "coverage",
                                 [cargo, "llvm-cov", "--json", "--output-path", "{artifact}/llvm-cov.json"] if cargo and llvm_cov else None,
                                 ecosystem=name, minimum_profile="standard", output_format="llvm-cov",
                                 workspace_effects="runtime", timeout=1800, reason="cargo-llvm-cov is unavailable."))
        mutants = tool("cargo-mutants")
        if PROFILE_RANK[profile] >= 3:
            checks.append(_check("rust.mutation", "cargo-mutants", "test-strength", [mutants, "--json"] if mutants else None,
                                 ecosystem=name, minimum_profile="deep", output_format="cargo-mutants", workspace_effects="runtime", timeout=3600, reason="cargo-mutants is unavailable."))
        return checks
    if name == "dotnet":
        dotnet = tool("dotnet")
        checks = [
            _check("dotnet.build", "dotnet", "correctness", [dotnet, "build", "--no-restore"] if dotnet else None, ecosystem=name, required=True, workspace_effects="cache", reason=".NET SDK is unavailable."),
            _check("dotnet.tests", "dotnet", "tests", [dotnet, "test", "--no-restore"] if dotnet else None, ecosystem=name, required=True, workspace_effects="runtime", timeout=1200, reason=".NET SDK is unavailable."),
        ]
        if PROFILE_RANK[profile] >= 2:
            checks.append(_check("dotnet.coverage", "dotnet", "coverage",
                                 [dotnet, "test", "--no-restore", "--collect:XPlat Code Coverage", "--results-directory", "{artifact}"] if dotnet else None,
                                 ecosystem=name, minimum_profile="standard", output_format="cobertura",
                                 workspace_effects="runtime", timeout=1800, reason=".NET SDK is unavailable."))
        return checks
    if name == "c-cpp":
        cmake, ctest, tidy = tool("cmake"), tool("ctest"), tool("clang-tidy")
        return [
            _check("cpp.build", "cmake", "correctness", [cmake, "--build", "--preset", "default"] if cmake and "CMakePresets.json" in {Path(x).name for x in inv["configurations"]} else None,
                   ecosystem=name, required=True, workspace_effects="cache", reason="A configured CMake preset is unavailable."),
            _check("cpp.tests", "ctest", "tests", [ctest, "--test-dir", "build", "--output-on-failure"] if ctest else None,
                   ecosystem=name, required=True, workspace_effects="runtime", reason="CTest is unavailable."),
            _check("cpp.clang-tidy", "clang-tidy", "maintainability", [tidy, "-p", "build"] if tidy else None,
                   ecosystem=name, reason="clang-tidy is unavailable."),
        ]
    if name == "jvm":
        maven, gradle = tool("maven"), tool("gradle")
        build_systems = next((item["build_systems"] for item in inv["ecosystems"] if item["name"] == "jvm"), [])
        command = [maven, "test"] if "maven" in build_systems and maven else ([gradle, "test"] if gradle else None)
        checks = [_check("jvm.tests", "maven" if "maven" in build_systems else "gradle", "tests", command,
                         ecosystem=name, required=True, workspace_effects="runtime", timeout=1800, reason="Maven/Gradle is unavailable.")]
        if PROFILE_RANK[profile] >= 3:
            checks.append(_check("jvm.mutation", "pit", "test-strength", None, ecosystem=name, minimum_profile="deep",
                                 output_format="pit", workspace_effects="runtime", timeout=3600,
                                 reason="Run the repository-configured PIT task; no safe generic plugin injection is performed."))
        return checks
    return []


def _scope_targets(root: Path, inventory: dict[str, Any], selected_scope: str) -> list[str]:
    if selected_scope == "repository":
        return ["."]
    if selected_scope == "changed-files":
        files = inventory.get("default_scope", {}).get("files", [])
        return sorted(item for item in files if (root / item).is_file())
    scope_value = selected_scope
    if selected_scope.startswith("target:"):
        raw_target = selected_scope.split(":", 1)[1]
        target_candidates = [
            root / raw_target,
            root / f"{raw_target}.py",
            root / (raw_target.replace(".", "/") + ".py"),
        ]
        existing = next((item for item in target_candidates if item.exists()), None)
        if existing is None:
            return ["."]
        scope_value = existing.relative_to(root).as_posix()
    candidate = (root / scope_value).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("scope must remain inside the repository") from exc
    if not candidate.exists():
        raise ValueError(f"scope does not exist: {selected_scope}")
    return [relative.as_posix() or "."]

def create_plan(root: Path, profile: str = "standard", scope: str | None = None) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    inventory = detect(root)
    selected_scope = scope or inventory["default_scope"]["type"]
    scope_targets = _scope_targets(root, inventory, selected_scope)
    checks: list[dict[str, Any]] = []
    ecosystems = {item["name"] for item in inventory["ecosystems"]}
    if "python" in ecosystems:
        checks.extend(_python_checks(root, inventory, profile))
    if "javascript-typescript" in ecosystems:
        checks.extend(_javascript_checks(root, inventory, profile))
    for name in sorted(ecosystems & {"jvm", "dotnet", "go", "rust", "c-cpp"}):
        checks.extend(_simple_ecosystem_checks(inventory, profile, name))

    semgrep = _tool(inventory, "semgrep")
    local_config = next((item for item in inventory["configurations"] if Path(item).name in {".semgrep.yml", ".semgrep.yaml"}), None)
    bundled = Path(__file__).resolve().parent.parent / "rules" / "semgrep.yml"
    semgrep_config = str(root / local_config) if local_config else str(bundled)
    semgrep_argv = [semgrep, "scan", "--json", "--config", semgrep_config, *scope_targets] if semgrep and scope_targets else None
    checks.append(_check(
        "universal.semgrep", "semgrep", "security", semgrep_argv,
        output_format="semgrep", timeout=900, effective_scope=selected_scope,
        status="skipped" if semgrep and not scope_targets else None,
        reason="No existing files are in scope." if semgrep and not scope_targets else "Semgrep is unavailable.",
    ))

    gitleaks = _tool(inventory, "gitleaks")
    for index, target in enumerate(scope_targets or ["."]):
        check_id = "universal.gitleaks" if len(scope_targets) <= 1 else f"universal.gitleaks.{index + 1:04d}"
        argv = [gitleaks, "dir", target, "--no-banner", "--redact", "--report-format", "json", "--report-path", "{artifact}/gitleaks.json"] if gitleaks and scope_targets else None
        checks.append(_check(
            check_id, "gitleaks", "secrets", argv, output_format="gitleaks", timeout=600,
            effective_scope=selected_scope,
            status="skipped" if gitleaks and not scope_targets else None,
            reason="No existing files are in scope." if gitleaks and not scope_targets else "Gitleaks is unavailable.",
        ))

    if PROFILE_RANK[profile] >= 2:
        osv = _tool(inventory, "osv-scanner")
        has_dependencies = any(Path(item).name in {"pom.xml", "pyproject.toml", "requirements.txt", "package.json", "go.mod", "Cargo.lock", "packages.lock.json"} for item in inventory["configurations"])
        checks.append(_check("universal.osv", "osv-scanner", "dependencies",
                             [osv, "scan", "source", "-r", ".", "--format", "json"] if osv and has_dependencies else None,
                             minimum_profile="standard", output_format="osv-scanner", network=True, timeout=900,
                             reason="OSV-Scanner or a dependency manifest is unavailable."))

        # Design-pattern detection (spec §16 in design-patterns-module/): an
        # internal analyzer, not an external tool — same idiom as
        # js.bundle-size (measure_artifacts.py above), resolving the SKILL's
        # own interpreter via python-runtime, never the audited project's.
        # No network, no project writes, no execution of the audited code.
        design_patterns_python = _tool(inventory, "python-runtime") or _tool(inventory, "python")
        design_patterns_script = str(Path(__file__).resolve().parent.parent / "analyze_design_patterns.py")
        # spec §17: a changed-files scope still needs the WHOLE repo read for
        # dependency context (Target/Adaptee can live outside the diff), but
        # findings must stay anchored to the requested scope. `--focus`
        # narrows the OUTPUT; the analyzer always reads every file under
        # --root. effective_scope says so explicitly rather than claiming a
        # plain "changed-files" that would misdescribe what was read.
        design_patterns_scoped = selected_scope == "changed-files" and scope_targets and scope_targets != ["."]
        design_patterns_argv = None
        if design_patterns_python:
            design_patterns_argv = [
                design_patterns_python, design_patterns_script, "--root", str(root),
                "--output", "{artifact}/design-patterns.json", "--uml-dir", "{artifact}/uml",
            ]
            if design_patterns_scoped:
                for target in scope_targets:
                    design_patterns_argv += ["--focus", target]
        checks.append(_check(
            "universal.design-patterns", "design-patterns", "quality", design_patterns_argv,
            minimum_profile="standard", output_format="design-patterns",
            workspace_effects="none", network=False, timeout=300,
            effective_scope=(
                "changed files + local dependency context" if design_patterns_scoped else "repository"
            ),
            status="skipped" if design_patterns_python and selected_scope == "changed-files" and not scope_targets else None,
            reason=(
                "No existing files are in scope." if design_patterns_python and selected_scope == "changed-files" and not scope_targets
                else "Python runtime is unavailable." if not design_patterns_python
                else ""
            ),
        ))
        structure_script = str(Path(__file__).resolve().parent.parent / "analyze_structure.py")
        checks.append(_check(
            "universal.structure", "structure", "maintainability",
            [design_patterns_python, structure_script, "--root", str(root), "--output", "{artifact}/structure.json"] if design_patterns_python else None,
            minimum_profile="standard", output_format="structure", workspace_effects="none", network=False, timeout=300,
            effective_scope="repository", reason="" if design_patterns_python else "Python runtime is unavailable.",
        ))
        algorithms_script = str(Path(__file__).resolve().parent.parent / "analyze_algorithms.py")
        algorithms_argv = None
        if design_patterns_python:
            algorithms_argv = [
                design_patterns_python, algorithms_script, "--root", str(root),
                "--profile", profile, "--output", "{artifact}/algorithms.json",
            ]
            if design_patterns_scoped:
                for target in scope_targets:
                    algorithms_argv += ["--focus", target]
        checks.append(_check(
            "universal.algorithms", "algorithms", "quality", algorithms_argv,
            minimum_profile="standard", output_format="algorithms",
            workspace_effects="none", network=False, timeout=600,
            effective_scope=(
                "changed files + local dependency context" if design_patterns_scoped else "repository"
            ),
            status="skipped" if design_patterns_python and selected_scope == "changed-files" and not scope_targets else None,
            reason=(
                "No existing files are in scope." if design_patterns_python and selected_scope == "changed-files" and not scope_targets
                else "Python runtime is unavailable." if not design_patterns_python
                else ""
            ),
        ))
    if PROFILE_RANK[profile] >= 3:
        trivy = _tool(inventory, "trivy")
        checks.append(_check("universal.trivy", "trivy", "security",
                             [trivy, "fs", "--format", "json", "--scanners", "vuln,misconfig,secret,license", "."] if trivy else None,
                             minimum_profile="deep", output_format="trivy", network=True, timeout=1800,
                             reason="Trivy is unavailable."))
        checks.append(_check("universal.codeql", "codeql", "security", None, minimum_profile="deep", network=True,
                             reason="CodeQL requires repository-specific database creation and applicable licensing."))

    configured_sonar = any(Path(item).name == "sonar-project.properties" for item in inventory["configurations"])
    # Sonda de navegador: la única que necesita red y un servicio ya en marcha.
    checks.append(_web_runtime_check(root, inventory, profile))

    sonar = _tool(inventory, "sonar-scanner")
    if PROFILE_RANK[profile] >= 2:
        checks.append(_check("universal.sonar", "sonar-scanner", "quality",
                             [sonar] if sonar and configured_sonar else None, minimum_profile="standard",
                             network=True, workspace_effects="cache", timeout=1800,
                             reason="SonarScanner is unavailable or sonar-project.properties is absent."))

    return {
        "schema_version": "1.0.0",
        "root": str(root),
        "profile": profile,
        "scope": selected_scope,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inventory": inventory,
        "checks": _ordered_checks(checks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=tuple(PROFILE_RANK), default="standard")
    parser.add_argument("--scope")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = create_plan(args.root, args.profile, args.scope)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())






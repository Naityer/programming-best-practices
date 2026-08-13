#!/usr/bin/env python3
"""Detect repository stacks, configuration, Git scope, and available tools."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "vendor",
    "target", "build", "dist", "out", "coverage", ".quality-audit",
}
LANGUAGE_EXTENSIONS = {
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".cs": "csharp", ".fs": "fsharp", ".vb": "visual-basic",
    ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c-cpp", ".cc": "c-cpp", ".cpp": "c-cpp",
    ".cxx": "c-cpp", ".hpp": "c-cpp", ".hh": "c-cpp",
}
TOOL_COMMANDS = {
    "git": ["git"],
    "java": ["java"], "javac": ["javac"], "maven": ["mvn", "mvnw", "mvnw.cmd"],
    "gradle": ["gradle", "gradlew", "gradlew.bat"],
    "python": ["python3", "python"], "pytest": ["pytest"], "ruff": ["ruff"],
    "mypy": ["mypy"], "pyright": ["pyright"], "coverage": ["coverage"],
    "mutmut": ["mutmut"], "pynguin": ["pynguin"], "hypothesis": ["hypothesis"],
    "node": ["node"], "npm": ["npm"], "pnpm": ["pnpm"], "yarn": ["yarn"], "bun": ["bun"],
    "eslint": ["eslint"], "stryker": ["stryker"],
    "dotnet": ["dotnet"], "go": ["go"], "staticcheck": ["staticcheck"],
    "rustc": ["rustc"], "cargo": ["cargo"], "cargo-mutants": ["cargo-mutants"], "cargo-llvm-cov": ["cargo-llvm-cov"],
    "cmake": ["cmake"], "ctest": ["ctest"], "meson": ["meson"],
    "clang-tidy": ["clang-tidy"], "llvm-cov": ["llvm-cov"], "gcov": ["gcov"],
    "semgrep": ["semgrep"], "gitleaks": ["gitleaks"], "trivy": ["trivy"],
    "osv-scanner": ["osv-scanner"], "sonar-scanner": ["sonar-scanner"],
    "pmd": ["pmd"], "cpd": ["cpd"], "codeql": ["codeql"], "randoop": ["randoop"], "evosuite": ["evosuite"], "unit-test-bot": ["utbot"],
}
CONFIG_NAMES = {
    "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "requirements.txt",
    "package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb",
    "global.json", "go.mod", "go.work", "Cargo.toml", "Cargo.lock",
    "CMakeLists.txt", "CMakePresets.json", "meson.build", "Makefile",
    "sonar-project.properties", ".semgrep.yml", ".semgrep.yaml", ".gitleaks.toml",
    "stryker.conf.json", "stryker-config.json",
}


def _run(command: list[str], cwd: Path, timeout: int = 5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _walk(root: Path) -> tuple[Counter[str], list[str]]:
    languages: Counter[str] = Counter()
    configs: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in IGNORED_DIRS)
        current_path = Path(current)
        for name in sorted(files):
            path = current_path / name
            language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
            if language:
                languages[language] += 1
            if name in CONFIG_NAMES or name.endswith((".sln", ".csproj", ".fsproj")):
                configs.append(path.relative_to(root).as_posix())
    return languages, sorted(set(configs))


def _git_info(root: Path) -> dict[str, Any]:
    git = shutil.which("git")
    if not git:
        return {"available": False, "repository": False, "changed_files": []}
    inside = _run([git, "rev-parse", "--is-inside-work-tree"], root)
    if not inside or inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"available": True, "repository": False, "changed_files": []}
    status = _run([git, "status", "--porcelain", "--untracked-files=all"], root)
    changed: list[str] = []
    if status and status.returncode == 0:
        for line in status.stdout.splitlines():
            if len(line) < 4:
                continue
            value = line[3:]
            if " -> " in value:
                value = value.split(" -> ", 1)[1]
            changed.append(value.strip('"').replace("\\", "/"))
    return {
        "available": True,
        "repository": True,
        "changed_files": sorted(set(changed)),
    }


def _find_tool(candidates: list[str], root: Path) -> dict[str, Any]:
    for candidate in candidates:
        local = root / candidate
        if local.is_file():
            return {"status": "available", "command": str(local.resolve())}
        resolved = shutil.which(candidate)
        if resolved:
            return {"status": "available", "command": resolved}
    return {"status": "unavailable", "command": None}


def _package_json_runners(root: Path, configs: list[str]) -> list[str]:
    runners: set[str] = set()
    for relative in configs:
        if not relative.endswith("package.json"):
            continue
        try:
            data = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        combined: dict[str, Any] = {}
        for key in ("dependencies", "devDependencies", "peerDependencies", "scripts"):
            value = data.get(key)
            if isinstance(value, dict):
                combined.update(value)
        text = " ".join([*combined.keys(), *(str(v) for v in combined.values())]).lower()
        for name in ("vitest", "jest", "mocha", "node --test"):
            if name in text:
                runners.add("node:test" if name == "node --test" else name)
    return sorted(runners)


def _ecosystems(root: Path, configs: list[str], languages: Counter[str]) -> list[dict[str, Any]]:
    names = {Path(item).name for item in configs}
    ecosystems: list[dict[str, Any]] = []

    if languages["java"] or languages["kotlin"] or names.intersection({"pom.xml", "build.gradle", "build.gradle.kts"}):
        builds = []
        if "pom.xml" in names:
            builds.append("maven")
        if names.intersection({"build.gradle", "build.gradle.kts"}):
            builds.append("gradle")
        ecosystems.append({"name": "jvm", "build_systems": builds, "test_runners": ["junit/testng"]})

    if languages["python"] or names.intersection({"pyproject.toml", "setup.cfg", "requirements.txt"}):
        runners = ["pytest"] if names.intersection({"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}) else ["unittest"]
        ecosystems.append({"name": "python", "build_systems": ["python"], "test_runners": runners})

    if languages["javascript"] or languages["typescript"] or "package.json" in names:
        manager = "npm"
        if "pnpm-lock.yaml" in names:
            manager = "pnpm"
        elif "yarn.lock" in names:
            manager = "yarn"
        elif "bun.lockb" in names:
            manager = "bun"
        ecosystems.append({"name": "javascript-typescript", "build_systems": [manager], "test_runners": _package_json_runners(root, configs)})

    if languages["csharp"] or languages["fsharp"] or any(item.endswith((".sln", ".csproj", ".fsproj")) for item in configs):
        ecosystems.append({"name": "dotnet", "build_systems": ["dotnet"], "test_runners": ["dotnet-test"]})

    if languages["go"] or names.intersection({"go.mod", "go.work"}):
        ecosystems.append({"name": "go", "build_systems": ["go"], "test_runners": ["go-test"]})

    if languages["rust"] or "Cargo.toml" in names:
        ecosystems.append({"name": "rust", "build_systems": ["cargo"], "test_runners": ["cargo-test"]})

    if languages["c"] or languages["c-cpp"] or names.intersection({"CMakeLists.txt", "meson.build", "Makefile"}):
        builds = [name for marker, name in (("CMakeLists.txt", "cmake"), ("meson.build", "meson"), ("Makefile", "make")) if marker in names]
        ecosystems.append({"name": "c-cpp", "build_systems": builds, "test_runners": ["ctest/configured-harness"]})

    return ecosystems


def detect(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"root is not a directory: {resolved}")
    languages, configs = _walk(resolved)
    git = _git_info(resolved)
    tools = {name: _find_tool(commands, resolved) for name, commands in sorted(TOOL_COMMANDS.items())}
    if sys.executable:
        tools["python-runtime"] = {"status": "available", "command": str(Path(sys.executable).resolve())}
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(resolved),
        "git": git,
        "default_scope": {
            "type": "changed-files" if git["changed_files"] else "repository",
            "files": git["changed_files"],
        },
        "languages": [{"name": name, "files": count} for name, count in sorted(languages.items())],
        "ecosystems": _ecosystems(resolved, configs, languages),
        "configurations": configs,
        "tools": tools,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = detect(args.root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



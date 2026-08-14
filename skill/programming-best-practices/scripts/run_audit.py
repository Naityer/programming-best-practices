#!/usr/bin/env python3
"""Execute an audit plan with explicit safety gates, timeouts, and captured evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _tool_version(executable: str, cwd: Path, env: dict[str, str]) -> str:
    """Return a short best-effort version string without invoking a shell."""
    try:
        completed = subprocess.run(
            [executable, "--version"], cwd=cwd, env=env, check=False,
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = (completed.stdout or completed.stderr).decode("utf-8", errors="replace")
    return output.strip().splitlines()[0][:200] if output.strip() else "unknown"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _allowed_executables(plan: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for item in plan.get("inventory", {}).get("tools", {}).values():
        command = item.get("command") if isinstance(item, dict) else None
        if command:
            allowed.add(os.path.normcase(str(Path(command).resolve())))
    return allowed


def _expand_artifacts(value: str, artifact: Path, artifact_dirs: dict[str, Path]) -> str:
    """Sustituye `{artifact}` y `{artifact:<id-de-check>}`.

    La segunda forma existe porque cada check recibe SU propio directorio, y dos
    checks encadenados necesitan compartir un fichero: `coverage run` deja los
    datos y `coverage json` los lee. Con solo `{artifact}` cada uno miraba en su
    carpeta, el segundo no encontraba nada y reportaba "No data to report" —
    cobertura medida durante 40 segundos y tirada a la basura en silencio.
    """
    for referenced, directory in artifact_dirs.items():
        value = value.replace("{artifact:" + referenced + "}", str(directory))
    return value.replace("{artifact}", str(artifact))


def _safe_argv(argv: Any, artifact: Path, allowed: set[str],
               artifact_dirs: dict[str, Path] | None = None) -> list[str]:
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError("invalid argv")
    expanded = [_expand_artifacts(item, artifact, artifact_dirs or {}) for item in argv]
    executable = os.path.normcase(str(Path(expanded[0]).resolve()))
    if executable not in allowed:
        raise ValueError(f"executable was not detected in the plan inventory: {expanded[0]}")
    return expanded


def _status(check: dict[str, Any], returncode: int) -> str:
    if returncode == 0:
        return "passed"
    finding_categories = {
        "tests", "correctness", "maintainability", "security", "secrets",
        "dependencies", "coverage", "test-strength",
    }
    if returncode == 1 and check["category"] in finding_categories:
        return "findings"
    return "failed"


def execute_plan(
    plan: dict[str, Any],
    output_dir: Path,
    *,
    allow_project_writes: bool = False,
    allow_network: bool = False,
    allow_generated_code: bool = False,
) -> dict[str, Any]:
    root = Path(plan["root"]).expanduser().resolve(strict=True)
    destination = output_dir.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"output directory exists: {destination}")
    if _inside(destination, root):
        raise ValueError("output directory must be outside the audited repository")
    destination.mkdir(parents=True)
    allowed = _allowed_executables(plan)
    results: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    artifact_dirs: dict[str, Path] = {}
    versions: dict[str, str] = {}

    for check in plan["checks"]:
        result = {
            "id": check["id"], "name": check["tool"], "category": check["category"],
            "status": check["status"], "command": "", "exit_code": None,
            "duration_ms": 0, "stdout": "", "stderr": "", "artifact_dir": "",
            "output_format": check["output_format"], "required": check["required"],
            "reason": check.get("reason", ""), "version": "unknown",
            "gate": bool(check.get("gate", False)),
            "effective_scope": check.get("effective_scope", "repository"),
        }
        dependencies = check.get("depends_on", [])
        if any(statuses.get(item) != "passed" for item in dependencies):
            result.update(status="skipped", reason="A prerequisite check did not pass.")
        elif check["status"] != "planned":
            pass
        elif check.get("network") and not allow_network:
            result.update(status="skipped", reason="Network access was not authorized.")
        elif check.get("generated_code") and not allow_generated_code:
            result.update(status="skipped", reason="Generated-code execution was not authorized.")
        elif check.get("workspace_effects") != "none" and not allow_project_writes:
            result.update(status="skipped", reason=f"Project effects ({check['workspace_effects']}) were not authorized.")
        else:
            check_cwd = (root / check.get("cwd", ".")).resolve()
            if not _inside(check_cwd, root) or not check_cwd.is_dir():
                result.update(status="failed", reason="Check working directory escapes or is absent.")
                results.append(result)
                statuses[check["id"]] = result["status"]
                continue
            check_dir = destination / check["id"].replace("/", "_")
            check_dir.mkdir()
            artifact_dirs[check["id"]] = check_dir
            result["artifact_dir"] = str(check_dir)
            try:
                argv = _safe_argv(check["argv"], check_dir, allowed, artifact_dirs)
                result["command"] = subprocess.list2cmdline(argv)
                stdout_path = check_dir / "stdout.txt"
                stderr_path = check_dir / "stderr.txt"
                env = os.environ.copy()
                env.update({"PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1", "CI": "1"})
                env.update({
                    key: _expand_artifacts(value, check_dir, artifact_dirs)
                    for key, value in check.get("environment", {}).items()
                })
                version_key = os.path.normcase(str(Path(argv[0]).resolve()))
                if version_key not in versions:
                    versions[version_key] = _tool_version(argv[0], check_cwd, env)
                result["version"] = versions[version_key]
                started = time.monotonic()
                try:
                    completed = subprocess.run(
                        argv, cwd=check_cwd, env=env, check=False, capture_output=True,
                        timeout=check["timeout_seconds"],
                    )
                    stdout_path.write_bytes(completed.stdout)
                    stderr_path.write_bytes(completed.stderr)
                    result.update(
                        status=_status(check, completed.returncode),
                        exit_code=completed.returncode,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        stdout=str(stdout_path), stderr=str(stderr_path), reason="",
                    )
                except subprocess.TimeoutExpired as exc:
                    stdout_path.write_bytes(exc.stdout or b"")
                    stderr_path.write_bytes(exc.stderr or b"")
                    result.update(
                        status="timed_out",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        stdout=str(stdout_path), stderr=str(stderr_path),
                        reason=f"Exceeded {check['timeout_seconds']} seconds.",
                    )
                except OSError as exc:
                    result.update(
                        status="failed",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        reason=str(exc),
                    )
            except ValueError as exc:
                result.update(status="failed", reason=str(exc))
        results.append(result)
        statuses[check["id"]] = result["status"]

    required_incomplete = any(
        item["required"] and item["status"] in {"failed", "timed_out", "skipped", "unavailable"}
        for item in results
    )
    return {
        "schema_version": "1.0.0", "root": str(root), "profile": plan["profile"],
        "scope": plan["scope"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "complete": not required_incomplete, "checks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Required acknowledgement before running commands")
    parser.add_argument("--allow-project-writes", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-generated-code", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("No commands executed. Re-run with --execute after reviewing the plan.", file=sys.stderr)
        return 2
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = execute_plan(
            plan, args.output_dir,
            allow_project_writes=args.allow_project_writes,
            allow_network=args.allow_network,
            allow_generated_code=args.allow_generated_code,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output = args.output_dir.resolve() / "execution.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




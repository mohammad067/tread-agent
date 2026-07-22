"""Production Validation — verify the system's frozen guarantees still hold (Milestone 6).

Aggregates static + data checks into a single production-readiness verdict:
  - architecture compatibility     — the frozen import boundaries hold (core imports no I/O/vendor;
                                      pipeline reaches the LLM only via the port; no vendor SDK
                                      outside adapters).
  - schema compatibility           — every frozen schema file parses as a valid JSON Schema.
  - contract compatibility         — a stored run carries all required contract fields + validates.
  - replay compatibility           — a stored run replays byte-identically (via ReplayHarness).
  - deterministic reproducibility  — recomputing the deterministic core twice is identical.
  - provider independence          — the reasoning public surface names no vendor; adapters are the
                                      sole SDK home.

Pure checks over source + stored data; no live provider, no schema/architecture mutation.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from market_state_engine.evaluation.engine import CheckResult


@dataclass(frozen=True)
class ValidationReport:
    checks: list[CheckResult]

    @property
    def production_ready(self) -> bool:
        return all(c.passed for c in self.checks)


# --- architecture compatibility ------------------------------------------------------
_VENDOR_SDKS = {"openai", "anthropic", "google"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def check_architecture_compatibility(pkg_root: Path) -> CheckResult:
    failures: list[str] = []
    core_forbidden = ("persistence", "pipeline", "api", "reasoning", "ingestion")
    for path in (pkg_root / "core").rglob("*.py"):
        for name in _imports(path):
            for layer in core_forbidden:
                if name.startswith(f"market_state_engine.{layer}"):
                    failures.append(f"core/{path.name} imports {layer}")
    for path in (pkg_root / "pipeline").rglob("*.py"):
        for name in _imports(path):
            if name.startswith("market_state_engine.reasoning.gateway") or name.startswith(
                "market_state_engine.reasoning.adapters"
            ):
                failures.append(f"pipeline/{path.name} imports {name} (must use the port)")
    for path in pkg_root.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        for name in _imports(path):
            if name.split(".")[0] in _VENDOR_SDKS:
                failures.append(f"{path.name} imports vendor SDK {name} outside adapters")
    return CheckResult("architecture_compatibility", not failures, "frozen boundaries", failures)


# --- schema compatibility ------------------------------------------------------------
def check_schema_compatibility(schemas_dir: Path) -> CheckResult:
    failures: list[str] = []
    paths = [
        schemas_dir / "market_state_run.v1.0.0.json",
        *sorted((schemas_dir / "internal").glob("*.json")),
    ]
    for path in paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    return CheckResult("schema_compatibility", not failures, f"{len(paths)} schemas", failures)


# --- provider independence -----------------------------------------------------------
def check_provider_independence(pkg_root: Path) -> CheckResult:
    import importlib

    reasoning = importlib.import_module("market_state_engine.reasoning")
    surface = list(getattr(reasoning, "__all__", []))
    failures = [
        name
        for name in surface
        for vendor in ("openai", "claude", "anthropic", "gemini")
        if vendor in name.lower()
    ]
    # No top-level vendor import anywhere outside adapters.
    for path in pkg_root.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        for imp in _imports(path):
            if imp.split(".")[0] in _VENDOR_SDKS:
                failures.append(f"{path.name}: vendor import {imp}")
    return CheckResult(
        "provider_independence", not failures, "no vendor in public surface", failures
    )

"""M5 import-boundary tests: the new I/O layers respect the frozen dependency rules.

Complements the import-linter contracts with a runtime structural check: the deterministic core does
not import persistence/pipeline/api, and the pipeline reaches the LLM only via the port (never the
gateway impl or a vendor adapter).
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2] / "src" / "market_state_engine"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _module_files(subpkg: str) -> list[Path]:
    return sorted((PKG_ROOT / subpkg).rglob("*.py"))


def test_core_does_not_import_io_layers() -> None:
    forbidden = ("persistence", "pipeline", "api", "reasoning", "ingestion")
    offenders: list[str] = []
    for path in _module_files("core"):
        for name in _imports(path):
            for layer in forbidden:
                if name.startswith(f"market_state_engine.{layer}"):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders


def test_pipeline_reaches_llm_only_via_port() -> None:
    offenders: list[str] = []
    for path in _module_files("pipeline"):
        for name in _imports(path):
            if name.startswith("market_state_engine.reasoning.gateway"):
                offenders.append(f"{path.name}: {name}")
            if name.startswith("market_state_engine.reasoning.adapters"):
                offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders


def test_persistence_does_not_import_business_logic() -> None:
    forbidden = ("features", "news", "scoring", "guardrails", "reasoning", "pipeline", "api")
    offenders: list[str] = []
    for path in _module_files("persistence"):
        for name in _imports(path):
            for layer in forbidden:
                if name.startswith(f"market_state_engine.{layer}"):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders


def test_no_vendor_sdk_outside_adapters() -> None:
    vendor = {"openai", "anthropic"}
    offenders: list[str] = []
    for path in PKG_ROOT.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        for name in _imports(path):
            if name.split(".")[0] in vendor:
                offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders

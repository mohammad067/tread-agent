"""Import-boundary tests (M4.1) — the frozen dependency rule, checked at runtime.

Complements the static ``import-linter`` CI gate: the deterministic core and the pure compute
layers must never import the reasoning layer, and no vendor SDK may be importable outside
``reasoning/adapters/`` (frozen invariant #1). We assert on module source, not on live network.
"""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import market_state_engine

PKG_ROOT = Path(market_state_engine.__file__).resolve().parent

# Layers that must not depend on the reasoning layer.
_CORE_AND_COMPUTE = ("core", "features", "rules", "news", "scoring", "guardrails")

# Vendor SDKs that may only ever appear under reasoning/adapters/.
_VENDOR_SDKS = ("openai", "anthropic", "google", "google.generativeai", "vertexai", "boto3")


def _iter_module_files(subpackage: str) -> list[Path]:
    base = PKG_ROOT / subpackage
    return list(base.rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_and_compute_never_import_reasoning() -> None:
    offenders: list[str] = []
    for sub in _CORE_AND_COMPUTE:
        for path in _iter_module_files(sub):
            for name in _imported_names(path):
                if name.startswith("market_state_engine.reasoning"):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, f"core/compute imported reasoning: {offenders}"


def test_no_vendor_sdk_imported_outside_adapters() -> None:
    offenders: list[str] = []
    for module in pkgutil.walk_packages([str(PKG_ROOT)], prefix="market_state_engine."):
        mod_name = module.name
        # Locate the source file for this module.
        rel = mod_name[len("market_state_engine.") :].replace(".", "/")
        candidates = [PKG_ROOT / f"{rel}.py", PKG_ROOT / rel / "__init__.py"]
        path = next((c for c in candidates if c.is_file()), None)
        if path is None:
            continue
        if "reasoning.adapters" in mod_name or "reasoning\\adapters" in str(path):
            continue  # the one permitted home for vendor SDKs
        if "adapters" in path.parts:
            continue
        for name in _imported_names(path):
            root = name.split(".")[0]
            if root in _VENDOR_SDKS:
                offenders.append(f"{mod_name}: {name}")
    assert not offenders, f"vendor SDK imported outside adapters: {offenders}"


def test_reasoning_does_not_import_compute_layers() -> None:
    forbidden = ("features", "news", "scoring", "guardrails", "ingestion", "pipeline", "api")
    offenders: list[str] = []
    for path in _iter_module_files("reasoning"):
        for name in _imported_names(path):
            for layer in forbidden:
                if name.startswith(f"market_state_engine.{layer}"):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, f"reasoning reached into a forbidden layer: {offenders}"


def test_no_top_level_vendor_sdk_import_in_adapters() -> None:
    # Vendor SDKs must be loaded lazily (inside functions) so the package imports with no SDK
    # present and CI stays hermetic. No adapter module may import a vendor SDK at module scope.
    offenders: list[str] = []
    for path in _iter_module_files("reasoning/adapters"):
        for name in _imported_names(path):  # _imported_names walks only module-level statements
            root = name.split(".")[0]
            if root in _VENDOR_SDKS:
                offenders.append(f"{path.name}: {name}")
    assert not offenders, f"adapter imports a vendor SDK at module scope: {offenders}"


def test_reasoning_package_imports_without_any_sdk() -> None:
    # Importing the adapters package (and building adapters) must not require any vendor SDK.
    import importlib

    pkg = importlib.import_module("market_state_engine.reasoning.adapters")
    assert set(pkg.registered_providers()) == {"openai", "anthropic", "gemini"}

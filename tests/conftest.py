"""Shared test fixtures and paths.

Provides repo-root-relative paths to the frozen schema files and golden fixtures, plus a
jsonschema validator factory with a local file registry so cross-file ``$ref`` between the
internal schemas resolves fully offline (no network).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
INTERNAL_SCHEMAS_DIR = SCHEMAS_DIR / "internal"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def schema_registry() -> Registry:
    """A referencing Registry holding every schema, keyed by both its ``$id`` and its bare
    filename, so ``$ref: "rule_activation.v1.json"`` (used inside internal schemas) resolves
    without any network access."""
    resources: list[tuple[str, Resource[Any]]] = []
    schema_paths = [
        SCHEMAS_DIR / "market_state_run.v1.0.0.json",
        *sorted(INTERNAL_SCHEMAS_DIR.glob("*.json")),
    ]
    for schema_path in schema_paths:
        contents = _load_json(schema_path)
        resource: Resource[Any] = Resource.from_contents(contents)
        # Register under the schema's own $id.
        if "$id" in contents:
            resources.append((contents["$id"], resource))
        # Also register under the bare filename for relative refs between internal schemas.
        resources.append((schema_path.name, resource))
    return Registry().with_resources(resources)


@pytest.fixture(scope="session")
def make_validator(schema_registry: Registry):  # type: ignore[no-untyped-def]
    def _make(schema_filename: str) -> Draft202012Validator:
        if schema_filename == "market_state_run.v1.0.0.json":
            schema = _load_json(SCHEMAS_DIR / schema_filename)
        else:
            schema = _load_json(INTERNAL_SCHEMAS_DIR / schema_filename)
        return Draft202012Validator(schema, registry=schema_registry)

    return _make


@pytest.fixture(scope="session")
def load_golden_json():  # type: ignore[no-untyped-def]
    def _load(name: str) -> Any:
        return _load_json(GOLDEN_DIR / name)

    return _load


@pytest.fixture(scope="session")
def load_golden_yaml():  # type: ignore[no-untyped-def]
    def _load(name: str) -> Any:
        return _load_yaml(GOLDEN_DIR / name)

    return _load

"""Offline JSON-Schema loading for evaluation/validation (reuses the frozen schemas verbatim).

Builds a ``referencing`` registry over ``schemas/`` so cross-file ``$ref`` between the public and
internal schemas resolves with no network — the same mechanism the contract-test harness uses. This
module only *reads* the frozen schema files; it never modifies them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry(schemas_dir: Path) -> Registry:
    """A registry of every schema keyed by ``$id`` and bare filename (offline ref resolution)."""
    internal = schemas_dir / "internal"
    resources: list[tuple[str, Resource[Any]]] = []
    paths = [schemas_dir / "market_state_run.v1.0.0.json", *sorted(internal.glob("*.json"))]
    for path in paths:
        contents = _load(path)
        resource: Resource[Any] = Resource.from_contents(contents)
        if "$id" in contents:
            resources.append((contents["$id"], resource))
        resources.append((path.name, resource))
    return Registry().with_resources(resources)


def market_state_run_validator(schemas_dir: Path) -> Draft202012Validator:
    schema = _load(schemas_dir / "market_state_run.v1.0.0.json")
    return Draft202012Validator(schema, registry=build_registry(schemas_dir))


def internal_validator(schemas_dir: Path, filename: str) -> Draft202012Validator:
    schema = _load(schemas_dir / "internal" / filename)
    return Draft202012Validator(schema, registry=build_registry(schemas_dir))

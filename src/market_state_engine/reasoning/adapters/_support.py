"""Shared helpers for concrete provider adapters (M4.2).

Two seams every real adapter uses:
  - ``load_sdk``     — lazy import of a vendor SDK, done ONLY here inside ``reasoning/adapters/``
                       (frozen invariant #1). Raises ``ProviderCallError`` if the package is absent,
                       so a missing SDK degrades like any other call failure rather than crashing at
                       import time. CI never installs a vendor SDK — adapters are exercised via an
                       injected client, so ``load_sdk`` is only reached on a real deployment.
  - ``system_and_user`` — split the neutral ``RenderedPrompt`` into the (system, user) pair most
                       vendors expect. The whole rendered text is the user turn; a fixed neutral
                       system instruction pins JSON-only output. This wraps, never rewrites, the
                       prompt semantics (ADR-007 D-4).
"""

from __future__ import annotations

import importlib
from types import ModuleType

from ..errors import ProviderCallError
from ..types import RenderedPrompt

# Neutral system instruction: vendor-independent, semantic-preserving. Adapters may place it in the
# vendor's system slot; it adds no market content, only the output-format contract.
JSON_ONLY_SYSTEM = (
    "You are a structured-output engine. Respond with a single valid JSON object and nothing else. "
    "Do not add markdown fences, prose, or commentary."
)


def load_sdk(module_name: str, provider: str) -> ModuleType:
    """Import a vendor SDK lazily; a missing package is a call failure, not an import-time crash."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ProviderCallError(f"{provider}: SDK '{module_name}' is not installed") from exc


def system_and_user(prompt: RenderedPrompt) -> tuple[str, str]:
    """Return (system, user) messages for the neutral prompt without altering its semantics."""
    return JSON_ONLY_SYSTEM, prompt.text

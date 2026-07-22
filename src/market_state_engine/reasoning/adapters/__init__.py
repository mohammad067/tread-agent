"""Provider adapters — the ONLY place a vendor SDK may ever be imported (frozen invariant #1).

M4.2 lands the concrete adapters (OpenAI, Claude, Gemini) plus the offline ``FakeProvider`` double
and the config-driven registration/factory. Vendor SDKs are imported lazily inside each adapter (in
``_support.load_sdk``), never at module import — so this package imports cleanly with no SDK present
and CI stays hermetic. Retry, failover, circuit breaker, health monitor, and replay are NOT here
(deferred to later M4 batches).
"""

from __future__ import annotations

from .base import ProviderAdapter
from .claude_provider import ClaudeProvider
from .factory import build_adapter, build_adapters, registered_providers
from .fake import FakeProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider
from .replay import ReplayProvider

__all__ = [
    "ClaudeProvider",
    "FakeProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "ProviderAdapter",
    "ReplayProvider",
    "build_adapter",
    "build_adapters",
    "registered_providers",
]

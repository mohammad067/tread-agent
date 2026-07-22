"""``ProviderAdapter`` — the narrow interface every vendor adapter implements (ADR-007 D-2).

One operation: ``complete(RenderedPrompt, CallParams) -> RawProviderResult``. An adapter translates
the neutral prompt into its vendor's envelope, maps structured-output / token-accounting / error
semantics to neutral types, and must not contain business logic or alter prompt semantics. Concrete
adapters (and any vendor SDK import) arrive in M4.2 — this file defines the boundary only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..types import CallParams, RawProviderResult, RenderedPrompt


@runtime_checkable
class ProviderAdapter(Protocol):
    @property
    def name(self) -> str:
        """Vendor id (e.g. ``openai``) — matches the config entry, recorded on every Call Record."""
        ...

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult: ...

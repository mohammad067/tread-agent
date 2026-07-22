"""Provider-neutral value objects exchanged across the LLM boundary.

These carry no vendor semantics: ``RenderedPrompt`` is byte-identical regardless of which vendor
will receive it, ``CallParams`` are the config-derived knobs an adapter applies, and
``RawProviderResult`` is the neutral shape every adapter maps its vendor response into.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderedPrompt:
    """Provider-neutral rendered prompt text plus its version and content hash.

    ``prompt_hash`` is computed on ``text`` only, so the same request yields the same hash across
    vendors — the property that makes cross-provider replay comparisons valid (frozen invariant #4).
    """

    text: str
    version: str
    prompt_hash: str


@dataclass(frozen=True)
class CallParams:
    """Config-derived call knobs an adapter applies to the neutral prompt."""

    model_id: str
    max_tokens: int
    temperature: float
    timeout_seconds: int


@dataclass(frozen=True)
class RawProviderResult:
    """Neutral result an adapter returns after mapping its vendor's response.

    ``text`` is the raw model output (expected to be JSON for the structured jobs); token counts
    and ``finish_reason`` are ``None`` when a vendor does not report them.
    """

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None

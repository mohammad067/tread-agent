"""``ReplayProvider`` — serve recorded Call Records back through the ``ProviderAdapter`` interface.

Replay/regression without the internet (ADR-007 D-9, frozen invariant #6): a ``ReplayProvider``
wraps one provider's recorded attempts and, on ``complete``, returns exactly what that provider
returned in the recorded run — the recorded response, tokens, and finish reason — or re-raises the
recorded failure (timeout / error) so the Gateway's failover behaves just as it did live. The
Gateway cannot tell a ReplayProvider from a live one; it is selected exactly like any other adapter.

Attempts are keyed by ``prompt_hash`` (the neutral prompt is identical across vendors and
processes), then consumed **in recorded order** for that hash so a retried/repeated prompt replays
its successive outcomes faithfully. A ``complete`` for an unknown prompt hash is a call failure
(nothing is recorded to reproduce) — surfaced as ``ProviderCallError``, never a fabricated result.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable

from ..errors import ProviderCallError, ProviderTimeoutError
from ..models import CallRecord
from ..outcome import Outcome
from ..types import CallParams, RawProviderResult, RenderedPrompt


class ReplayProvider:
    def __init__(self, name: str, records: Iterable[CallRecord]) -> None:
        self._name = name
        # prompt_hash -> queue of this provider's records for that prompt, in recorded order.
        self._by_hash: dict[str, deque[CallRecord]] = defaultdict(deque)
        for record in records:
            if record.provider == name:
                self._by_hash[record.prompt_hash].append(record)

    @property
    def name(self) -> str:
        return self._name

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        queue = self._by_hash.get(prompt.prompt_hash)
        if not queue:
            raise ProviderCallError(
                f"{self._name}: no recorded call for prompt_hash {prompt.prompt_hash}"
            )
        record = queue.popleft()
        return _result_from_record(self._name, record)


def _result_from_record(provider: str, record: CallRecord) -> RawProviderResult:
    """Reproduce a recorded attempt: return the recorded result, or re-raise its failure."""
    if record.outcome == Outcome.TIMEOUT.value:
        raise ProviderTimeoutError(f"{provider}: replayed timeout")
    if record.outcome in (Outcome.ERROR.value, Outcome.CIRCUIT_OPEN.value):
        raise ProviderCallError(f"{provider}: replayed {record.outcome}")
    # Success: re-serialize the recorded response with the same canonical form the live provider's
    # text would have produced (sorted keys), so parse + hash reproduce byte-identically.
    text = json.dumps(record.response, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return RawProviderResult(
        text=text,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        finish_reason=record.finish_reason,
    )

"""FakeProvider tests (M4.2): canned offline double, fixed / queued / error modes."""

from __future__ import annotations

import pytest

from market_state_engine.reasoning.adapters.base import ProviderAdapter
from market_state_engine.reasoning.adapters.fake import FakeProvider
from market_state_engine.reasoning.errors import ProviderCallError
from market_state_engine.reasoning.types import CallParams, RawProviderResult, RenderedPrompt

PROMPT = RenderedPrompt(text="hi", version="sentiment/v1", prompt_hash="h")
PARAMS = CallParams(model_id="m", max_tokens=10, temperature=0.0, timeout_seconds=5)


def test_fake_implements_adapter_interface() -> None:
    assert isinstance(FakeProvider(text="{}"), ProviderAdapter)


def test_fake_returns_fixed_text() -> None:
    fp = FakeProvider(name="fake", text='{"ok": 1}')
    result = fp.complete(PROMPT, PARAMS)
    assert result.text == '{"ok": 1}'
    assert result.finish_reason == "stop"
    assert fp.name == "fake"


def test_fake_records_calls() -> None:
    fp = FakeProvider(text="{}")
    fp.complete(PROMPT, PARAMS)
    fp.complete(PROMPT, PARAMS)
    assert len(fp.calls) == 2
    assert fp.calls[0][0] is PROMPT
    assert fp.calls[0][1] is PARAMS


def test_fake_queue_scripts_a_sequence() -> None:
    fp = FakeProvider(
        results=[
            RawProviderResult(text="a"),
            RawProviderResult(text="b"),
        ]
    )
    assert fp.complete(PROMPT, PARAMS).text == "a"
    assert fp.complete(PROMPT, PARAMS).text == "b"


def test_fake_raises_when_configured() -> None:
    fp = FakeProvider(raise_exc=ProviderCallError("boom"))
    with pytest.raises(ProviderCallError):
        fp.complete(PROMPT, PARAMS)


def test_fake_with_no_canned_response_raises() -> None:
    with pytest.raises(ProviderCallError):
        FakeProvider().complete(PROMPT, PARAMS)


def test_fake_result_object_passthrough() -> None:
    res = RawProviderResult(text="x", input_tokens=5, output_tokens=1, finish_reason="stop")
    assert FakeProvider(result=res).complete(PROMPT, PARAMS) is res

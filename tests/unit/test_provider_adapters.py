"""Provider adapter tests (M4.2): each vendor adapter maps its response/errors to neutral types.

No vendor SDK is installed in CI; adapters are exercised through an injected stub client that mimics
each vendor's response shape. This tests the mapping + error contract — the adapter's whole job —
without any network access (frozen invariant #10).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from market_state_engine.reasoning.adapters.claude_provider import ClaudeProvider
from market_state_engine.reasoning.adapters.gemini_provider import GeminiProvider
from market_state_engine.reasoning.adapters.openai_provider import OpenAIProvider
from market_state_engine.reasoning.errors import ProviderCallError
from market_state_engine.reasoning.types import CallParams, RenderedPrompt

PROMPT = RenderedPrompt(text='{"x": 1}', version="sentiment/v1", prompt_hash="deadbeef")
PARAMS = CallParams(model_id="m-1", max_tokens=256, temperature=0.0, timeout_seconds=20)


# --- OpenAI --------------------------------------------------------------------------
class _OpenAIStub:
    def __init__(self, content: str = '{"ok": true}', *, raise_exc: Exception | None = None):
        self._content = content
        self._raise = raise_exc
        self.captured: dict[str, object] = {}

        outer = self

        class _Completions:
            def create(self, **kwargs: object) -> object:
                outer.captured = kwargs
                if outer._raise is not None:
                    raise outer._raise
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=outer._content),
                            finish_reason="stop",
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3),
                )

        self.chat = SimpleNamespace(completions=_Completions())


def test_openai_maps_response() -> None:
    adapter = OpenAIProvider("openai", "OPENAI_API_KEY", client=_OpenAIStub('{"a": 1}'))
    result = adapter.complete(PROMPT, PARAMS)
    assert result.text == '{"a": 1}'
    assert result.input_tokens == 11
    assert result.output_tokens == 3
    assert result.finish_reason == "stop"
    assert adapter.name == "openai"


def test_openai_sends_json_mode_and_params() -> None:
    stub = _OpenAIStub()
    OpenAIProvider("openai", "OPENAI_API_KEY", client=stub).complete(PROMPT, PARAMS)
    assert stub.captured["model"] == "m-1"
    assert stub.captured["max_tokens"] == 256
    assert stub.captured["response_format"] == {"type": "json_object"}


def test_openai_maps_vendor_error() -> None:
    adapter = OpenAIProvider("openai", "K", client=_OpenAIStub(raise_exc=RuntimeError("429")))
    with pytest.raises(ProviderCallError):
        adapter.complete(PROMPT, PARAMS)


def test_openai_null_content_becomes_empty() -> None:
    adapter = OpenAIProvider("openai", "K", client=_OpenAIStub(content=None))  # type: ignore[arg-type]
    assert adapter.complete(PROMPT, PARAMS).text == ""


# --- Claude --------------------------------------------------------------------------
class _ClaudeStub:
    def __init__(self, text: str = '{"ok": true}', *, raise_exc: Exception | None = None):
        self._text = text
        self._raise = raise_exc
        self.captured: dict[str, object] = {}
        outer = self

        class _Messages:
            def create(self, **kwargs: object) -> object:
                outer.captured = kwargs
                if outer._raise is not None:
                    raise outer._raise
                return SimpleNamespace(
                    content=[SimpleNamespace(text=outer._text)],
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=20, output_tokens=5),
                )

        self.messages = _Messages()


def test_claude_maps_response_and_concatenates_blocks() -> None:
    stub = _ClaudeStub('{"b": 2}')
    result = ClaudeProvider("anthropic", "ANTHROPIC_API_KEY", client=stub).complete(PROMPT, PARAMS)
    assert result.text == '{"b": 2}'
    assert result.input_tokens == 20
    assert result.output_tokens == 5
    assert result.finish_reason == "end_turn"


def test_claude_uses_system_slot() -> None:
    stub = _ClaudeStub()
    adapter = ClaudeProvider("anthropic", "K", client=stub)
    assert adapter.name == "anthropic"
    adapter.complete(PROMPT, PARAMS)
    assert "system" in stub.captured
    assert stub.captured["messages"] == [{"role": "user", "content": PROMPT.text}]


def test_claude_maps_vendor_error() -> None:
    adapter = ClaudeProvider("anthropic", "K", client=_ClaudeStub(raise_exc=RuntimeError("500")))
    with pytest.raises(ProviderCallError):
        adapter.complete(PROMPT, PARAMS)


# --- Gemini --------------------------------------------------------------------------
class _GeminiModelStub:
    def __init__(self, outer: _GeminiSdkStub) -> None:
        self._outer = outer

    def generate_content(self, contents: object, **kwargs: object) -> object:
        self._outer.captured = kwargs
        if self._outer._raise is not None:
            raise self._outer._raise
        return SimpleNamespace(
            text=self._outer._text,
            candidates=[SimpleNamespace(finish_reason=1)],
            usage_metadata=SimpleNamespace(prompt_token_count=30, candidates_token_count=7),
        )


class _GeminiSdkStub:
    def __init__(self, text: str = '{"ok": true}', *, raise_exc: Exception | None = None):
        self._text = text
        self._raise = raise_exc
        self.captured: dict[str, object] = {}
        self.system_instruction: object = None

    def GenerativeModel(self, model_name: str, system_instruction: str) -> object:
        self.system_instruction = system_instruction
        return _GeminiModelStub(self)


def test_gemini_maps_response() -> None:
    stub = _GeminiSdkStub('{"c": 3}')
    result = GeminiProvider("gemini", "GOOGLE_API_KEY", client=stub).complete(PROMPT, PARAMS)
    assert result.text == '{"c": 3}'
    assert result.input_tokens == 30
    assert result.output_tokens == 7
    assert result.finish_reason == "1"  # stringified


def test_gemini_sets_system_instruction_and_json_mime() -> None:
    stub = _GeminiSdkStub()
    adapter = GeminiProvider("gemini", "K", client=stub)
    assert adapter.name == "gemini"
    adapter.complete(PROMPT, PARAMS)
    assert stub.system_instruction is not None
    gen_cfg = stub.captured["generation_config"]
    assert gen_cfg["response_mime_type"] == "application/json"  # type: ignore[index]


def test_gemini_maps_vendor_error() -> None:
    adapter = GeminiProvider("gemini", "K", client=_GeminiSdkStub(raise_exc=RuntimeError("quota")))
    with pytest.raises(ProviderCallError):
        adapter.complete(PROMPT, PARAMS)

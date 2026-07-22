"""``OpenAIProvider`` — OpenAI adapter (ADR-007 D-2). Vendor SDK imported ONLY here.

Translates the neutral ``RenderedPrompt`` into an OpenAI Chat Completions call (JSON-mode), maps the
response text / token usage / finish reason to a neutral ``RawProviderResult``, and maps any vendor
exception to ``ProviderCallError``. No retry/failover/circuit logic (that is the Gateway's, later).

Offline-testable: the client is injected. On a real deploy the client is lazily constructed from the
SDK with the API key read from the env var named in config (secrets never in code — ADR-007 D-3).
"""

from __future__ import annotations

import os
from typing import Any

from ..errors import ProviderCallError
from ..types import CallParams, RawProviderResult, RenderedPrompt
from ._support import load_sdk, system_and_user


class OpenAIProvider:
    def __init__(self, name: str, api_key_env: str, client: Any | None = None) -> None:
        self._name = name
        self._api_key_env = api_key_env
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self._api_key_env)  # pragma: no cover - real-deploy path
        if not api_key:  # pragma: no cover
            raise ProviderCallError(f"{self._name}: env var {self._api_key_env} is unset")
        sdk = load_sdk("openai", self._name)  # pragma: no cover
        self._client = sdk.OpenAI(api_key=api_key)  # pragma: no cover
        return self._client  # pragma: no cover

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        system, user = system_and_user(prompt)
        try:
            response = self._get_client().chat.completions.create(
                model=params.model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=params.temperature,
                max_tokens=params.max_tokens,
                timeout=params.timeout_seconds,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            # Map ANY vendor error (SDK exception, HTTP error, timeout) to the neutral contract.
            raise ProviderCallError(f"{self._name}: {exc}") from exc
        return _map_response(response)


def _map_response(response: Any) -> RawProviderResult:
    """Map an OpenAI ChatCompletion (or a shape-compatible stub) to a neutral result."""
    choice = response.choices[0]
    text = choice.message.content or ""
    finish_reason = getattr(choice, "finish_reason", None)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
    output_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
    return RawProviderResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )

"""``GeminiProvider`` — Google Gemini adapter (ADR-007 D-2). Vendor SDK imported ONLY here.

Translates the neutral ``RenderedPrompt`` into a Gemini ``generate_content`` call (JSON response
mime type), maps response text / token usage / finish reason to a neutral ``RawProviderResult``, and
maps any vendor exception to ``ProviderCallError``. Offline-testable via an injected model client;
on a real deploy the client is lazily built from the SDK with the API key from the configured env.
"""

from __future__ import annotations

import os
from typing import Any

from ..errors import ProviderCallError
from ..types import CallParams, RawProviderResult, RenderedPrompt
from ._support import load_sdk, system_and_user


class GeminiProvider:
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
        sdk = load_sdk("google.generativeai", self._name)  # pragma: no cover
        sdk.configure(api_key=api_key)  # pragma: no cover
        self._client = sdk  # pragma: no cover
        return self._client  # pragma: no cover

    def complete(self, prompt: RenderedPrompt, params: CallParams) -> RawProviderResult:
        system, user = system_and_user(prompt)
        try:
            client = self._get_client()
            model = client.GenerativeModel(
                model_name=params.model_id,
                system_instruction=system,
            )
            response = model.generate_content(
                user,
                generation_config={
                    "temperature": params.temperature,
                    "max_output_tokens": params.max_tokens,
                    "response_mime_type": "application/json",
                },
                request_options={"timeout": params.timeout_seconds},
            )
        except Exception as exc:
            # Map ANY vendor error (SDK exception, HTTP error, timeout) to the neutral contract.
            raise ProviderCallError(f"{self._name}: {exc}") from exc
        return _map_response(response)


def _map_response(response: Any) -> RawProviderResult:
    """Map a Gemini GenerateContentResponse (or a shape-compatible stub) to a neutral result."""
    text = getattr(response, "text", "") or ""
    candidates = getattr(response, "candidates", None) or []
    finish_reason = None
    if candidates:
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is not None:
            finish_reason = str(finish_reason)
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) if usage is not None else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage is not None else None
    return RawProviderResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )

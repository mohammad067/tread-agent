"""Structured-output validation against the frozen ``reasoning_response.v1.json`` schema.

M1 §4: both LLM calls demand structured output validated against the internal ``ReasoningResponse``
schema. A malformed / unparseable / schema-violating response is a **call failure** (raises
``StructuredOutputError``) — never a fabricated result. Retry/failover consumption of that failure
arrives in M4.2; here we only parse + validate + build the typed response.

The validator loads the JSON Schema from disk (schemas live outside ``src/``) and validates against
the correct ``$def`` for the job (``SentimentResponse`` vs ``SynthesisResponse``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from market_state_engine.core.enums import LlmJob

from .errors import StructuredOutputError
from .models import SentimentResponse, SynthesisResponse

_RESPONSE_SCHEMA_FILE = "reasoning_response.v1.json"
_DEF_FOR_JOB: dict[LlmJob, str] = {
    LlmJob.SENTIMENT: "SentimentResponse",
    LlmJob.SYNTHESIS: "SynthesisResponse",
}


class StructuredOutputValidator:
    def __init__(self, schemas_internal_dir: Path) -> None:
        path = schemas_internal_dir / _RESPONSE_SCHEMA_FILE
        if not path.is_file():
            raise StructuredOutputError(f"response schema not found: {path}")
        self._schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    def _validator_for(self, job: LlmJob) -> Draft202012Validator:
        # Validate against the job's specific variant, not the top-level oneOf, so error messages
        # are precise and a sentiment blob can't accidentally satisfy the synthesis variant.
        sub = {**self._schema, "$ref": f"#/$defs/{_DEF_FOR_JOB[job]}"}
        sub.pop("oneOf", None)
        return Draft202012Validator(sub)

    def parse_json(self, raw_text: str) -> dict[str, Any]:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"response is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise StructuredOutputError("response JSON must be an object")
        return data

    def validate(self, job: LlmJob, data: dict[str, Any]) -> None:
        errors = sorted(self._validator_for(job).iter_errors(data), key=str)
        if errors:
            raise StructuredOutputError(
                f"{job.value} response failed schema validation: {errors[0].message}"
            )

    def build_sentiment(self, data: dict[str, Any]) -> SentimentResponse:
        self.validate(LlmJob.SENTIMENT, data)
        return SentimentResponse.model_validate(data)

    def build_synthesis(self, data: dict[str, Any]) -> SynthesisResponse:
        self.validate(LlmJob.SYNTHESIS, data)
        return SynthesisResponse.model_validate(data)

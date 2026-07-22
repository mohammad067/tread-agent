"""``PromptBuilder`` — render versioned templates into a provider-neutral ``RenderedPrompt``.

Templates live in ``prompts/{sentiment,synthesis}/vN.md`` (application-owned, versioned, hashed —
frozen invariant #4). Rendering substitutes ``{{placeholder}}`` tokens from the ``ReasoningRequest``
and computes ``prompt_hash`` over the neutral text, so the same request yields the same hash
regardless of which vendor will receive it. The builder contains no vendor formatting.

Payload sub-objects (news_digest, state_vector, sentiment) are serialized with sorted keys and a
fixed separator so the rendered text — and therefore the hash — is byte-stable across processes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from market_state_engine.core.enums import LlmJob
from market_state_engine.core.hashing import content_hash

from .errors import PromptTemplateError
from .models import ReasoningRequest
from .types import RenderedPrompt

# Default active template version per job (bumping this is a reviewed, hash-changing event).
_DEFAULT_VERSIONS: dict[LlmJob, str] = {
    LlmJob.SENTIMENT: "v1",
    LlmJob.SYNTHESIS: "v1",
}

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _pretty(value: object) -> str:
    """Stable, human-readable JSON for embedding a payload object into neutral prompt text."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)


class PromptBuilder:
    def __init__(self, prompts_dir: Path, versions: dict[LlmJob, str] | None = None) -> None:
        self._prompts_dir = prompts_dir
        self._versions = versions or dict(_DEFAULT_VERSIONS)

    def version_for(self, job: LlmJob) -> str:
        """The template identifier recorded on the Call Record, e.g. ``sentiment/v1``."""
        return f"{job.value}/{self._versions[job]}"

    def build(self, request: ReasoningRequest) -> RenderedPrompt:
        job = request.job
        template = self._load_template(job)
        variables = self._variables(request)
        text = self._render(template, variables)
        return RenderedPrompt(
            text=text,
            version=self.version_for(job),
            prompt_hash=content_hash(text),
        )

    # --- internals ---------------------------------------------------------------------
    def _template_path(self, job: LlmJob) -> Path:
        return self._prompts_dir / job.value / f"{self._versions[job]}.md"

    def _load_template(self, job: LlmJob) -> str:
        path = self._template_path(job)
        if not path.is_file():
            raise PromptTemplateError(f"prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _variables(self, request: ReasoningRequest) -> dict[str, str]:
        payload = request.payload
        c = request.constraints
        variables: dict[str, str] = {
            "run_id": request.run_id,
            "language": c.language,
            "output_schema_ref": c.output_schema_ref,
        }
        # Job-specific payload fields, serialized deterministically.
        assets = payload.get("assets")
        if isinstance(assets, list):
            variables["assets"] = ", ".join(str(a) for a in assets)
        if "news_digest" in payload:
            variables["news_digest"] = _pretty(payload["news_digest"])
        if "state_vector" in payload:
            variables["state_vector"] = _pretty(payload["state_vector"])
        if "sentiment" in payload:
            variables["sentiment"] = _pretty(payload["sentiment"])
        return variables

    def _render(self, template: str, variables: dict[str, str]) -> str:
        def _sub(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                raise PromptTemplateError(f"no value for prompt placeholder {{{{{key}}}}}")
            return variables[key]

        return _PLACEHOLDER_RE.sub(_sub, template)

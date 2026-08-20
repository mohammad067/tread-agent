"""PromptBuilder rendering tests (M4.1): vendor-neutral text, versioning, stable hash."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_state_engine.core.enums import LlmJob
from market_state_engine.reasoning.errors import PromptTemplateError
from market_state_engine.reasoning.models import ReasoningRequest
from market_state_engine.reasoning.prompt_builder import PromptBuilder

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "prompts"


def _sentiment_request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "01J8ZK3W9P4Q5R6S7T8U9V0W1X",
            "job": "sentiment",
            "payload": {
                "assets": ["BTC", "ETH"],
                "news_digest": {"run_id": "r1", "items": []},
            },
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SentimentResponse",
                "max_tokens": 512,
                "temperature": 0,
            },
        }
    )


def _synthesis_request() -> ReasoningRequest:
    return ReasoningRequest.model_validate(
        {
            "run_id": "r1",
            "job": "synthesis",
            "payload": {
                "state_vector": {"run_id": "r1", "regime": {"state": "risk_off"}},
                "sentiment": {"global_sentiment": -0.3},
            },
            "constraints": {
                "language": "fa",
                "grounding": True,
                "output_schema_ref": "reasoning_response.v1.json#/$defs/SynthesisResponse",
                "max_tokens": 1024,
                "temperature": 0,
            },
        }
    )


def test_version_string_matches_job_and_template() -> None:
    pb = PromptBuilder(PROMPTS)
    assert pb.version_for(LlmJob.SENTIMENT) == "sentiment/v3"
    assert pb.version_for(LlmJob.SYNTHESIS) == "synthesis/v1"


def test_sentiment_render_substitutes_placeholders() -> None:
    pb = PromptBuilder(PROMPTS)
    rp = pb.build(_sentiment_request())
    assert "{{" not in rp.text  # every placeholder resolved
    assert "BTC, ETH" in rp.text
    assert rp.version == "sentiment/v3"
    assert len(rp.prompt_hash) == 64  # sha-256 hex


def test_synthesis_render_substitutes_placeholders() -> None:
    pb = PromptBuilder(PROMPTS)
    rp = pb.build(_synthesis_request())
    assert "{{" not in rp.text
    assert "risk_off" in rp.text
    assert rp.version == "synthesis/v1"


def test_hash_is_deterministic_for_same_request() -> None:
    pb = PromptBuilder(PROMPTS)
    a = pb.build(_sentiment_request())
    b = pb.build(_sentiment_request())
    assert a.text == b.text
    assert a.prompt_hash == b.prompt_hash


def test_hash_is_neutral_across_vendors() -> None:
    # The rendered text carries no vendor identity, so two builders (standing in for two vendor
    # call sites) produce the same hash — the property that makes cross-provider replay valid.
    pb1 = PromptBuilder(PROMPTS)
    pb2 = PromptBuilder(PROMPTS)
    h1 = pb1.build(_sentiment_request()).prompt_hash
    h2 = pb2.build(_sentiment_request()).prompt_hash
    assert h1 == h2


def test_sentiment_v3_renders_deterministic_weights_and_evidence() -> None:
    golden = json.loads(
        (REPO / "tests" / "golden" / "reasoning_request.sentiment.json").read_text(encoding="utf-8")
    )
    request = ReasoningRequest.model_validate(golden)

    rendered = PromptBuilder(PROMPTS).build(request)

    assert rendered.version == "sentiment/v3"
    assert '"asset_weights"' in rendered.text
    assert '"evidence_text": "Core CPI exceeded consensus' in rendered.text
    assert '"BTC"' in rendered.text
    assert '"relevance": 0.75' in rendered.text
    assert '"effective_weight": 0.69825' in rendered.text
    assert '"max_effective_weight": 0.8379' in rendered.text
    assert "وزن جدید نسازید" in rendered.text
    assert "فقط برای ترتیب کلی خبرها" in rendered.text
    assert "ارتباط جدید حدس نزنید" in rendered.text


def test_different_payload_changes_hash() -> None:
    pb = PromptBuilder(PROMPTS)
    base = pb.build(_sentiment_request())
    other_req = _sentiment_request()
    other_req.payload["assets"] = ["GOLD"]
    other = pb.build(other_req)
    assert other.prompt_hash != base.prompt_hash


def test_missing_template_raises(tmp_path: Path) -> None:
    pb = PromptBuilder(tmp_path)  # empty dir → no templates
    with pytest.raises(PromptTemplateError):
        pb.build(_sentiment_request())


def test_unknown_placeholder_raises(tmp_path: Path) -> None:
    # A template referencing a placeholder the builder has no value for is a template error,
    # never a silently blank prompt (which would corrupt the hash contract).
    (tmp_path / "sentiment").mkdir()
    (tmp_path / "sentiment" / "v1.md").write_text("hello {{unknown_field}}", encoding="utf-8")
    pb = PromptBuilder(tmp_path)
    with pytest.raises(PromptTemplateError):
        pb.build(_sentiment_request())

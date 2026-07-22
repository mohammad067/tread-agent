"""Shared adapter-helper tests (M4.2): lazy SDK loader + neutral system/user split."""

from __future__ import annotations

import pytest

from market_state_engine.reasoning.adapters._support import (
    JSON_ONLY_SYSTEM,
    load_sdk,
    system_and_user,
)
from market_state_engine.reasoning.errors import ProviderCallError
from market_state_engine.reasoning.types import RenderedPrompt


def test_load_sdk_returns_module_when_present() -> None:
    # A present module (stdlib stand-in) loads without error.
    mod = load_sdk("json", "test")
    assert hasattr(mod, "dumps")


def test_load_sdk_missing_is_call_failure() -> None:
    with pytest.raises(ProviderCallError):
        load_sdk("definitely_not_a_real_sdk_xyz", "test")


def test_system_and_user_preserves_prompt_text() -> None:
    prompt = RenderedPrompt(text="NEUTRAL BODY", version="sentiment/v1", prompt_hash="h")
    system, user = system_and_user(prompt)
    assert system == JSON_ONLY_SYSTEM
    assert user == "NEUTRAL BODY"  # semantics unchanged (ADR-007 D-4)

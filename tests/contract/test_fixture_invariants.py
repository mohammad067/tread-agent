"""Fixture invariants beyond raw schema validation (fixtures spec §C.3, DTO spec §10).

These encode the normative semantics the golden fixtures must demonstrate: honest degraded
absence, causal-link -> activated-rule resolution, USD/IRR IRT-with-no-proxy, and the rule
hard sign-off gate (ADR-008 / rule-schema §7).
"""

from __future__ import annotations

from typing import Any

import pytest

MARKET_STATE_FIXTURES = [
    "market_state_run.normal.json",
    "market_state_run.degraded.json",
    "market_state_run.stale_usdirr.json",
]

# LLM-only asset fields that must be absent/null on a degraded run.
LLM_ASSET_FIELDS = ("human_summary_fa", "novelty_flags")


def _assets(doc: Any) -> list[dict[str, Any]]:
    return list(doc["assets"])


@pytest.mark.contract
def test_all_six_mvp_assets_present(load_golden_json: Any) -> None:
    expected = {"BTC", "ETH", "GOLD", "WTI", "USD_IRR", "TOTAL_MCAP"}
    for name in MARKET_STATE_FIXTURES:
        doc = load_golden_json(name)
        symbols = {a["symbol"] for a in _assets(doc)}
        assert symbols == expected, f"{name}: {symbols}"


@pytest.mark.contract
def test_degraded_fixture_has_honest_absence(load_golden_json: Any) -> None:
    """§C.3.2: the degraded fixture populates no LLM-only fields; sentiment is null."""
    doc = load_golden_json("market_state_run.degraded.json")
    assert doc["is_degraded"] is True
    for asset in _assets(doc):
        assert asset["scores"]["sentiment"] is None, asset["symbol"]
        for field in LLM_ASSET_FIELDS:
            assert field not in asset, f"{asset['symbol']} has LLM field {field}"
    codes = {f["code"] for f in doc["guardrail_flags"]}
    assert "degraded_run" in codes


@pytest.mark.contract
def test_normal_fixture_is_not_degraded_and_has_summaries(load_golden_json: Any) -> None:
    doc = load_golden_json("market_state_run.normal.json")
    assert doc["is_degraded"] is False
    for asset in _assets(doc):
        assert asset["human_summary_fa"], asset["symbol"]
        assert isinstance(asset["scores"]["sentiment"], (int, float))


@pytest.mark.contract
@pytest.mark.parametrize("fixture_name", MARKET_STATE_FIXTURES)
def test_causal_links_resolve_to_activated_rules(fixture_name: str, load_golden_json: Any) -> None:
    """§C.3.3: every causal_links[].via_rule resolves to an activated_rules[].rule_id."""
    doc = load_golden_json(fixture_name)
    activated_ids = {act["rule_id"] for asset in _assets(doc) for act in asset["activated_rules"]}
    for asset in _assets(doc):
        for link in asset["causal_links"]:
            assert link["via_rule"] in activated_ids, (
                f"{fixture_name}: {asset['symbol']} causal link via_rule "
                f"{link['via_rule']} not in activated rules {activated_ids}"
            )


@pytest.mark.contract
@pytest.mark.parametrize("fixture_name", MARKET_STATE_FIXTURES)
def test_usd_irr_is_irt_with_no_proxy_fields(fixture_name: str, load_golden_json: Any) -> None:
    """§C.3.4 / ADR-014: USD_IRR uses currency IRT and carries no proxy/rial fields."""
    doc = load_golden_json(fixture_name)
    usd_irr = next(a for a in _assets(doc) if a["symbol"] == "USD_IRR")
    assert usd_irr["price"]["currency"] == "IRT"
    # additionalProperties:false already forbids these at the schema level; assert explicitly too.
    assert "proxy_note" not in usd_irr
    assert "rial_multiplier" not in usd_irr["price"]


@pytest.mark.contract
def test_no_human_summary_en_anywhere(load_golden_json: Any) -> None:
    """ADR-014 / O1: v1.0.0 has no English summary field."""
    for name in MARKET_STATE_FIXTURES:
        doc = load_golden_json(name)
        for asset in _assets(doc):
            assert "human_summary_en" not in asset, f"{name}:{asset['symbol']}"


@pytest.mark.contract
def test_stale_usdirr_fixture_shape(load_golden_json: Any) -> None:
    """UC-4: USD_IRR stale, with reason + informal-quotes data gap."""
    doc = load_golden_json("market_state_run.stale_usdirr.json")
    usd_irr = next(a for a in _assets(doc) if a["symbol"] == "USD_IRR")
    assert usd_irr["price"]["is_stale"] is True
    assert usd_irr["price"]["stale_reason"] == "tehran_market_closed_weekend"
    assert "informal_overnight_quotes_excluded" in usd_irr["data_gaps"]


@pytest.mark.contract
def test_corrected_rule_passes_hard_gate(load_golden_yaml: Any) -> None:
    """ADR-008 / rule-schema §7: rule carries economic_rationale + reviewed_by senior_trader,
    and the gold effect is regime-guarded rather than unconditional."""
    rule = load_golden_yaml("rule.cpi_hot.corrected.yaml")
    assert rule["economic_rationale"].strip()
    assert rule["reviewed_by"] == "senior_trader"
    gold_effects = [e for e in rule["effects"] if e["asset"] == "GOLD"]
    assert gold_effects, "expected a GOLD effect"
    # A4: gold effect must be guarded (rule has regime_guard) OR downgraded to minor+uncertain.
    guarded = "regime_guard" in rule
    minor_uncertain = all(
        e["strength"] == "minor" and e.get("uncertain") is True for e in gold_effects
    )
    assert guarded or minor_uncertain

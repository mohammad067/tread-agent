"""Reliability-layer unit tests (M4.3): retry, timeout, circuit breaker, health, router.

All time is injected, so every test is deterministic and instant — no real sleeping, no wall-clock
(frozen invariant #6 / #10).
"""

from __future__ import annotations

import pytest

from market_state_engine.reasoning.errors import (
    ProviderCallError,
    ProviderTimeoutError,
    StructuredOutputError,
)
from market_state_engine.reasoning.outcome import Outcome
from market_state_engine.reasoning.provider_config import (
    BackoffCfg,
    CircuitBreakerCfg,
    ProviderCfg,
    ProviderModels,
)
from market_state_engine.reasoning.reliability.circuit_breaker import BreakerState, CircuitBreaker
from market_state_engine.reasoning.reliability.health import HealthMonitor
from market_state_engine.reasoning.reliability.retry import RetryPolicy
from market_state_engine.reasoning.reliability.router import Router
from market_state_engine.reasoning.reliability.timeout import TimeoutPolicy
from market_state_engine.reasoning.types import RawProviderResult

RESULT = RawProviderResult(text='{"ok": 1}', finish_reason="stop")
BACKOFF = BackoffCfg(type="exponential", base_ms=400, max_ms=4000)


def _provider(name: str, priority: int, weight: int = 0) -> ProviderCfg:
    return ProviderCfg(
        name=name,
        enabled=True,
        priority=priority,
        weight=weight,
        api_key_env=f"{name.upper()}_KEY",
        models=ProviderModels(sentiment="m", synthesis="m"),
    )


# --- RetryPolicy ---------------------------------------------------------------------
def test_retry_succeeds_first_try() -> None:
    policy = RetryPolicy(retries=2, backoff=BACKOFF)
    result, retries_used = policy.run(lambda: RESULT)
    assert result is RESULT
    assert retries_used == 0


def test_retry_recovers_after_transient_failures() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def attempt() -> RawProviderResult:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderCallError("transient")
        return RESULT

    policy = RetryPolicy(retries=2, backoff=BACKOFF, sleep=slept.append)
    result, retries_used = policy.run(attempt)
    assert result is RESULT
    assert retries_used == 2
    assert calls["n"] == 3
    assert slept == [0.4, 0.8]  # exponential backoff: 400ms, 800ms


def test_retry_exhausts_and_raises_last_error() -> None:
    policy = RetryPolicy(retries=1, backoff=BACKOFF)

    def attempt() -> RawProviderResult:
        raise ProviderCallError("always")

    with pytest.raises(ProviderCallError):
        policy.run(attempt)


def test_retry_does_not_retry_structured_output_error() -> None:
    calls = {"n": 0}

    def attempt() -> RawProviderResult:
        calls["n"] += 1
        raise StructuredOutputError("malformed")

    policy = RetryPolicy(retries=3, backoff=BACKOFF)
    with pytest.raises(StructuredOutputError):
        policy.run(attempt)
    assert calls["n"] == 1  # content failure: no retry


def test_retry_zero_retries_single_attempt() -> None:
    assert RetryPolicy(retries=0, backoff=BACKOFF).max_attempts == 1


def test_backoff_is_capped() -> None:
    policy = RetryPolicy(retries=10, backoff=BackoffCfg(base_ms=400, max_ms=1000))
    assert policy.backoff_ms(0) == 400
    assert policy.backoff_ms(1) == 800
    assert policy.backoff_ms(2) == 1000  # capped
    assert policy.backoff_ms(5) == 1000


def test_backoff_non_exponential_is_flat() -> None:
    policy = RetryPolicy(retries=2, backoff=BackoffCfg(type="fixed", base_ms=300, max_ms=1000))
    assert policy.backoff_ms(0) == 300
    assert policy.backoff_ms(3) == 300


# --- TimeoutPolicy -------------------------------------------------------------------
def test_timeout_passes_within_deadline() -> None:
    ticks = iter([0, 500])  # 500ms < 1000ms deadline
    policy = TimeoutPolicy(timeout_seconds=1, monotonic_ms=lambda: next(ticks))
    result, elapsed = policy.run("p", lambda: RESULT)
    assert result is RESULT
    assert elapsed == 500


def test_timeout_trips_over_deadline() -> None:
    ticks = iter([0, 2500])  # 2500ms > 2000ms deadline
    policy = TimeoutPolicy(timeout_seconds=2, monotonic_ms=lambda: next(ticks))
    with pytest.raises(ProviderTimeoutError):
        policy.run("p", lambda: RESULT)


# --- CircuitBreaker ------------------------------------------------------------------
def _breaker(now: list[float]) -> CircuitBreaker:
    cfg = CircuitBreakerCfg(failure_threshold=3, window_seconds=120, half_open_after_seconds=60)
    return CircuitBreaker(cfg, monotonic_s=lambda: now[0])


def test_breaker_starts_closed() -> None:
    now = [0.0]
    b = _breaker(now)
    assert b.state is BreakerState.CLOSED
    assert b.allows() is True


def test_breaker_opens_after_threshold() -> None:
    now = [0.0]
    b = _breaker(now)
    for _ in range(3):
        b.record_failure()
    assert b.state is BreakerState.OPEN
    assert b.allows() is False


def test_breaker_half_opens_after_cooldown_then_closes_on_success() -> None:
    now = [0.0]
    b = _breaker(now)
    for _ in range(3):
        b.record_failure()
    assert b.state is BreakerState.OPEN
    now[0] = 61.0  # past half_open_after_seconds
    assert b.state is BreakerState.HALF_OPEN
    assert b.allows() is True
    b.record_success()
    assert b.state is BreakerState.CLOSED


def test_breaker_reopens_on_failed_probe() -> None:
    now = [0.0]
    b = _breaker(now)
    for _ in range(3):
        b.record_failure()
    now[0] = 61.0
    assert b.state is BreakerState.HALF_OPEN
    b.record_failure()  # probe fails
    assert b.state is BreakerState.OPEN
    now[0] = 100.0  # not yet past new cooldown (61 + 60)
    assert b.state is BreakerState.OPEN


def test_breaker_prunes_old_failures_outside_window() -> None:
    now = [0.0]
    b = _breaker(now)
    b.record_failure()
    b.record_failure()
    now[0] = 200.0  # first two failures now outside the 120s window
    b.record_failure()  # only 1 within window → stays closed
    assert b.state is BreakerState.CLOSED


def test_breaker_success_resets_failures() -> None:
    now = [0.0]
    b = _breaker(now)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.CLOSED  # counter was reset by the success


# --- HealthMonitor -------------------------------------------------------------------
def test_health_tracks_rates_and_latency() -> None:
    hm = HealthMonitor(window=10)
    hm.record("openai", Outcome.SUCCESS.value, 100)
    hm.record("openai", Outcome.SUCCESS.value, 300)
    hm.record("openai", Outcome.TIMEOUT.value, 0)
    snap = hm.snapshot("openai")
    assert snap.samples == 3
    assert snap.successes == 2
    assert snap.timeouts == 1
    assert snap.failures == 1
    assert snap.success_rate == pytest.approx(2 / 3)
    assert snap.timeout_rate == pytest.approx(1 / 3)
    assert snap.avg_latency_ms == pytest.approx(200.0)  # only successes counted


def test_health_unknown_provider_is_neutral() -> None:
    snap = HealthMonitor().snapshot("never_seen")
    assert snap.samples == 0
    assert snap.success_rate == 1.0


def test_health_window_bounds_memory() -> None:
    hm = HealthMonitor(window=2)
    for _ in range(5):
        hm.record("p", Outcome.SUCCESS.value, 10)
    assert hm.snapshot("p").samples == 2
    assert set(hm.all_snapshots()) == {"p"}


# --- Router --------------------------------------------------------------------------
def test_router_priority_order() -> None:
    router = Router("priority")
    assert router.strategy == "priority"
    providers = [_provider("c", 3), _provider("a", 1), _provider("b", 2)]
    order = router.order(providers, seed="run1")
    assert [p.name for p in order] == ["a", "b", "c"]


def test_router_empty() -> None:
    assert Router("priority").order([], seed="x") == []


def test_router_weighted_is_deterministic_per_run() -> None:
    providers = [_provider("a", 1, weight=10), _provider("b", 2, weight=90)]
    router = Router("weighted")
    o1 = [p.name for p in router.order(providers, seed="run-42")]
    o2 = [p.name for p in router.order(providers, seed="run-42")]
    assert o1 == o2  # replay-stable
    assert set(o1) == {"a", "b"}  # all providers still present as failover fall-through


def test_router_weighted_first_pick_follows_weight_distribution() -> None:
    providers = [_provider("a", 1, weight=1), _provider("b", 2, weight=99)]
    router = Router("weighted")
    firsts = [router.order(providers, seed=f"run-{i}")[0].name for i in range(200)]
    # With 99% weight on b, it should be chosen first the vast majority of the time.
    assert firsts.count("b") > firsts.count("a")


def test_router_weighted_zero_weights_falls_back_to_priority() -> None:
    providers = [_provider("a", 1, weight=0), _provider("b", 2, weight=0)]
    order = Router("weighted").order(providers, seed="run1")
    assert [p.name for p in order] == ["a", "b"]

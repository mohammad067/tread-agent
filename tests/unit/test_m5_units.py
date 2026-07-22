"""Focused unit tests for M5 leaf modules: security, session URL resolution, metrics, envelope."""

from __future__ import annotations

import pytest

from market_state_engine.api.envelope import envelope, error_body
from market_state_engine.api.security import AuthError, check_read, check_write
from market_state_engine.observability.metrics import Metrics
from market_state_engine.persistence.session import resolve_url


# --- security ------------------------------------------------------------------------
def test_check_read_open_when_no_key_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MSE_API_READ_KEY", raising=False)
    check_read(None)  # no exception


def test_check_read_rejects_bad_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_READ_KEY", "good")
    with pytest.raises(AuthError):
        check_read("bad")
    check_read("good")


def test_check_write_requires_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MSE_API_WRITE_KEY", raising=False)
    with pytest.raises(AuthError) as exc:
        check_write("anything")
    assert exc.value.status == 503


def test_check_write_accepts_write_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "w")
    check_write("w")


def test_check_write_rejects_unknown_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_API_WRITE_KEY", "w")
    monkeypatch.delenv("MSE_API_READ_KEY", raising=False)
    with pytest.raises(AuthError) as exc:
        check_write("nope")
    assert exc.value.status == 401


# --- session URL resolution ----------------------------------------------------------
def test_resolve_url_sqlite_memory() -> None:
    assert resolve_url("sqlite") == "sqlite:///:memory:"


def test_resolve_url_sqlite_path() -> None:
    assert resolve_url("sqlite", sqlite_path="/tmp/x.db") == "sqlite:////tmp/x.db"


def test_resolve_url_postgres_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSE_DSN", "postgresql://u:p@h/db")
    assert resolve_url("postgresql", dsn_env="MSE_DSN") == "postgresql://u:p@h/db"


def test_resolve_url_postgres_requires_env_name() -> None:
    with pytest.raises(ValueError, match="dsn_env"):
        resolve_url("postgresql")


def test_resolve_url_postgres_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MSE_DSN", raising=False)
    with pytest.raises(ValueError, match="unset"):
        resolve_url("postgresql", dsn_env="MSE_DSN")


# --- metrics -------------------------------------------------------------------------
def test_metrics_counter_and_gauge() -> None:
    m = Metrics()
    m.inc("runs_total")
    m.inc("runs_total", 2)
    m.set_gauge("last_latency_ms", 42.0)
    snap = m.snapshot()
    assert snap["runs_total"] == 3
    assert snap["last_latency_ms"] == 42.0


def test_metrics_prometheus_render() -> None:
    m = Metrics()
    m.inc("c")
    m.set_gauge("g", 1.0)
    text = m.render_prometheus()
    assert "# TYPE c counter" in text
    assert "# TYPE g gauge" in text


# --- envelope ------------------------------------------------------------------------
def test_envelope_meta_fields() -> None:
    body = envelope({"x": 1}, is_degraded=False, pagination={"next_cursor": None, "limit": 5})
    assert body["data"] == {"x": 1}
    assert body["meta"]["api_version"] == "v1"
    assert body["meta"]["is_degraded"] is False
    assert body["meta"]["pagination"]["limit"] == 5


def test_error_body_with_details() -> None:
    body = error_body("invalid_request", "bad", "corr-1", details={"field": "x"})
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["details"] == {"field": "x"}

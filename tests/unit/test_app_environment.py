"""Application environment policy is explicit, safe, and independent of cwd."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from market_state_engine.app.environment import (
    EnvironmentConfigurationError,
    load_root_dotenv,
    resolve_ingest_mode,
)


@pytest.mark.parametrize("mode", ["mock", "real"])
def test_dev_accepts_explicit_ingest_modes(mode: str) -> None:
    assert resolve_ingest_mode("dev", mode) == mode


def test_dev_without_ingest_mode_retains_mock_default() -> None:
    assert resolve_ingest_mode("dev", None) == "mock"


@pytest.mark.parametrize("environment", ["staging", "prod", "production"])
def test_protected_environment_requires_explicit_ingest(
    environment: str,
) -> None:
    with pytest.raises(EnvironmentConfigurationError, match="explicitly set"):
        resolve_ingest_mode(environment, None)


@pytest.mark.parametrize("environment", ["staging", "prod", "production"])
def test_protected_environment_rejects_mock(environment: str) -> None:
    with pytest.raises(EnvironmentConfigurationError, match="forbidden"):
        resolve_ingest_mode(environment, "mock")


@pytest.mark.parametrize("environment", ["staging", "prod", "production"])
def test_protected_environment_accepts_real(environment: str) -> None:
    assert resolve_ingest_mode(environment, "real") == "real"


def test_unknown_ingest_mode_is_rejected() -> None:
    with pytest.raises(EnvironmentConfigurationError, match="unsupported MSE_INGEST"):
        resolve_ingest_mode("dev", "automatic")


def test_root_dotenv_loading_does_not_depend_on_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    elsewhere = tmp_path / "elsewhere"
    root.mkdir()
    elsewhere.mkdir()
    (root / ".env").write_text("MSE_TEST_ROOT_VALUE=loaded-from-root\n", encoding="utf-8")
    monkeypatch.delenv("MSE_TEST_ROOT_VALUE", raising=False)
    monkeypatch.chdir(elsewhere)

    load_root_dotenv(root)

    assert os.environ["MSE_TEST_ROOT_VALUE"] == "loaded-from-root"


@pytest.mark.parametrize("mode", ["mock", "real"])
def test_dev_asgi_bootstrap_accepts_explicit_modes_from_another_cwd(
    mode: str, tmp_path: Path
) -> None:
    environment = os.environ.copy()
    _remove_parent_coverage_environment(environment)
    environment.update(
        {
            "MSE_ENV": "dev",
            "MSE_INGEST": mode,
            "MSE_SQLITE_PATH": str(tmp_path / f"{mode}.db"),
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import market_state_engine.app.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("", "must be explicitly set to 'real'"),
        ("mock", "MSE_INGEST='mock' is forbidden"),
    ],
)
def test_prod_asgi_bootstrap_fails_fast_before_database_setup(
    mode: str, message: str, tmp_path: Path
) -> None:
    environment = os.environ.copy()
    _remove_parent_coverage_environment(environment)
    environment.update({"MSE_ENV": "prod", "MSE_INGEST": mode})
    environment.pop("DB_DSN", None)

    result = subprocess.run(
        [sys.executable, "-c", "import market_state_engine.app.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert "DB_DSN" not in result.stderr


def _remove_parent_coverage_environment(environment: dict[str, str]) -> None:
    """Keep ASGI bootstrap subprocesses from writing incompatible pytest-cov data files."""
    for name in list(environment):
        if name.startswith("COV_CORE_"):
            environment.pop(name)

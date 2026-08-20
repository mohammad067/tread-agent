"""Environment-only bootstrap policy for the application composition root."""

from __future__ import annotations

from pathlib import Path

_INGEST_MODES = frozenset({"mock", "real"})
_PROTECTED_ENVIRONMENTS = frozenset({"staging", "prod", "production"})


class EnvironmentConfigurationError(RuntimeError):
    """An unsafe or unsupported application environment setting was supplied."""


def load_root_dotenv(root: Path) -> None:
    """Load only the repository-root ``.env``, independent of the process working directory."""

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependency is installed in supported deployments
        return
    load_dotenv(dotenv_path=root / ".env")


def resolve_ingest_mode(environment: str, configured_value: str | None) -> str:
    """Validate ingest mode and forbid mock data in protected environments."""

    normalized_environment = environment.strip().lower()
    raw_mode = configured_value.strip().lower() if configured_value is not None else ""

    if not raw_mode:
        if normalized_environment in _PROTECTED_ENVIRONMENTS:
            raise EnvironmentConfigurationError(
                f"MSE_INGEST must be explicitly set to 'real' in {normalized_environment}"
            )
        return "mock"

    if raw_mode not in _INGEST_MODES:
        allowed = ", ".join(sorted(_INGEST_MODES))
        raise EnvironmentConfigurationError(
            f"unsupported MSE_INGEST value {raw_mode!r}; expected one of: {allowed}"
        )

    if normalized_environment in _PROTECTED_ENVIRONMENTS and raw_mode == "mock":
        raise EnvironmentConfigurationError(
            f"MSE_INGEST='mock' is forbidden in {normalized_environment}; use 'real'"
        )

    return raw_mode

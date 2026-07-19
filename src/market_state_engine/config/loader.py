"""Config loading with fail-fast validation and version capture.

Reads the versioned YAML data files under ``config/`` and returns typed, validated models. A
malformed file raises ``ConfigError`` at load time (never mid-run). The loaded bundle records the
exact versions used, for per-run pinning and replay.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from market_state_engine.core.errors import ConfigError

from .models import AssetConfig, EnvConfig, HalfLives, MhiWeights, SourceQuality

ASSET_SYMBOLS = ("btc", "eth", "gold", "wti", "usd_irr", "total_mcap")


def _read_yaml(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file {path} must contain a mapping")
    return data


def _parse(model: type, data: dict[str, object], path: Path):  # type: ignore[no-untyped-def]
    try:
        return model(**data)
    except ValidationError as exc:
        raise ConfigError(f"config validation failed for {path}: {exc}") from exc


class ConfigBundle:
    """A fully loaded, validated configuration set with the versions it comprises."""

    def __init__(
        self,
        assets: dict[str, AssetConfig],
        mhi_weights: MhiWeights,
        source_quality: SourceQuality,
        half_lives: HalfLives,
    ) -> None:
        self.assets = assets
        self.mhi_weights = mhi_weights
        self.source_quality = source_quality
        self.half_lives = half_lives

    @property
    def versions(self) -> dict[str, str]:
        return {
            "mhi_weights": self.mhi_weights.version,
            "source_quality": self.source_quality.version,
            "half_lives": self.half_lives.version,
        }


def load_config_bundle(config_dir: Path) -> ConfigBundle:
    assets: dict[str, AssetConfig] = {}
    for name in ASSET_SYMBOLS:
        path = config_dir / "assets" / f"{name}.yaml"
        cfg = _parse(AssetConfig, _read_yaml(path), path)
        assets[cfg.symbol] = cfg

    mhi_path = config_dir / "weights" / "mhi_weights.v1.yaml"
    mhi = _parse(MhiWeights, _read_yaml(mhi_path), mhi_path)

    sq_path = config_dir / "sources" / "source_quality.v1.yaml"
    sq = _parse(SourceQuality, _read_yaml(sq_path), sq_path)

    hl_path = config_dir / "decay" / "half_lives.v1.yaml"
    hl = _parse(HalfLives, _read_yaml(hl_path), hl_path)

    return ConfigBundle(assets=assets, mhi_weights=mhi, source_quality=sq, half_lives=hl)


def load_env_config(config_dir: Path, env: str) -> EnvConfig:
    path = config_dir / "environments" / f"{env}.yaml"
    cfg: EnvConfig = _parse(EnvConfig, _read_yaml(path), path)
    return cfg

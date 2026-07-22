"""``PriceTable`` — versioned model pricing → automatic ``estimated_cost`` (ADR-007 D-6).

Cost is never hand-accounted: it derives from token counts x a versioned per-model rate table
(``config/models/pricing.vN.yaml``). The table version is recorded per Run, so historical cost
stays reproducible even as vendor prices drift. A model absent from the table falls back to the
``default`` rates (0 by default). Pure — loader reads config at startup; ``estimate`` does no I/O.

``estimated_cost`` is ``None`` when token counts are unavailable (a provider that does not report
usage) — an honest absence, mirroring the required-nullable field in call_record.v1.json.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ProviderConfigError


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRate(_Cfg):
    input_per_unit: float = Field(ge=0.0)
    output_per_unit: float = Field(ge=0.0)


class PricingConfig(_Cfg):
    version: str
    currency: str = "USD"
    unit_tokens: int = Field(default=1000, ge=1)
    default: ModelRate
    models: dict[str, ModelRate]


class PriceTable:
    def __init__(self, config: PricingConfig) -> None:
        self._config = config

    @property
    def version(self) -> str:
        return self._config.version

    @classmethod
    def from_file(cls, path: Path) -> PriceTable:
        if not path.is_file():
            raise ProviderConfigError(f"pricing config not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise ProviderConfigError(f"invalid YAML in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderConfigError(f"pricing config {path} must be a mapping")
        try:
            config = PricingConfig(**data)
        except ValidationError as exc:
            raise ProviderConfigError(f"pricing config invalid ({path}): {exc}") from exc
        return cls(config)

    def rate_for(self, model_id: str) -> ModelRate:
        return self._config.models.get(model_id, self._config.default)

    def estimate(
        self, model_id: str, input_tokens: int | None, output_tokens: int | None
    ) -> float | None:
        """Return estimated cost, or ``None`` when token counts are unavailable (honest absence)."""
        if input_tokens is None and output_tokens is None:
            return None
        rate = self.rate_for(model_id)
        unit = self._config.unit_tokens
        cost = (input_tokens or 0) / unit * rate.input_per_unit
        cost += (output_tokens or 0) / unit * rate.output_per_unit
        return round(cost, 6)

"""Typed models for ``config/models/providers.yaml`` (frozen sketch — llm-provider-architecture §3).

Providers are configuration, never code (ADR-007 D-3): no vendor value is hardcoded in ``src/`` and
secrets are referenced by env-var name only (``api_key_env``), never inlined. The whole frozen file
shape is modelled here — including the routing/retry/backoff/circuit-breaker knobs — so loading a
real config validates end-to-end; the *behaviour* those knobs drive (retry, failover, circuit
breaking) is deferred to M4.2 and is not read by anything in M4.1.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ProviderConfigError


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutingCfg(_Cfg):
    strategy: str = "priority"
    # ADR-011 frozen invariant: must remain true (a run degrades, never aborts, on total failure).
    degrade_after_all_fail: bool = True

    @model_validator(mode="after")
    def _validate(self) -> RoutingCfg:
        if self.strategy not in ("priority", "weighted"):
            raise ValueError(f"routing.strategy must be priority|weighted, got {self.strategy!r}")
        if self.degrade_after_all_fail is not True:
            raise ValueError("routing.degrade_after_all_fail must remain true (ADR-011)")
        return self


class BackoffCfg(_Cfg):
    type: str = "exponential"
    base_ms: int = Field(default=400, ge=0)
    max_ms: int = Field(default=4000, ge=0)


class CircuitBreakerCfg(_Cfg):
    failure_threshold: int = Field(default=5, ge=1)
    window_seconds: int = Field(default=120, ge=1)
    half_open_after_seconds: int = Field(default=60, ge=1)


class DefaultsCfg(_Cfg):
    temperature: float = Field(default=0.0, ge=0.0)
    max_tokens: int = Field(default=1024, ge=1)
    timeout_seconds: int = Field(default=20, ge=1)
    retries: int = Field(default=2, ge=0)
    backoff: BackoffCfg = Field(default_factory=BackoffCfg)
    circuit_breaker: CircuitBreakerCfg = Field(default_factory=CircuitBreakerCfg)


class ProviderModels(_Cfg):
    sentiment: str
    synthesis: str


class ProviderCfg(_Cfg):
    name: str
    enabled: bool = True
    priority: int = Field(ge=1)
    weight: int = Field(default=0, ge=0)
    api_key_env: str
    models: ProviderModels
    temperature: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)
    retries: int | None = Field(default=None, ge=0)


class ProvidersConfig(_Cfg):
    version: str
    routing: RoutingCfg
    defaults: DefaultsCfg
    providers: list[ProviderCfg]

    @model_validator(mode="after")
    def _validate(self) -> ProvidersConfig:
        if not self.providers:
            raise ValueError("providers.yaml must declare at least one provider")
        names = [p.name for p in self.providers]
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique")
        return self

    def model_for(self, provider: ProviderCfg, job: str) -> str:
        if job == "sentiment":
            return provider.models.sentiment
        if job == "synthesis":
            return provider.models.synthesis
        raise ProviderConfigError(f"unknown llm job: {job!r}")

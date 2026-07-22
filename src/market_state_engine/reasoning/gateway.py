"""``LLMGateway`` — the production implementation of ``MarketReasoner`` (ADR-007 D-2).

M4.3 completes the ADR-011 failover chain. For each LLM job the Gateway:
  1. builds the neutral prompt (PromptBuilder),
  2. orders providers for this run (Router: priority | deterministic weighted),
  3. walks the chain — skipping breaker-open providers — attempting each with its retry+timeout
     policy, validating structured output,
  4. records a Call Record per attempt, updates the circuit breaker + health monitor,
  5. returns the first validated response, or — if every provider is exhausted — an honest
     ``DegradedMarker`` (never aborts; ADR-011 DR-1..DR-3).

Everything below the port is config-driven and **operational only** — routing/health/breaker change
*which* provider answers, never any market number (ADR-007 D-7). All time is injected (clock,
monotonic ms, monotonic seconds, sleep) so behaviour is deterministic and replay-safe; the Gateway
does no I/O of its own beyond the injected adapters and Call Record sink (persistence is M5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from market_state_engine.core.enums import LlmJob
from market_state_engine.core.hashing import content_hash

from .adapters.base import ProviderAdapter
from .errors import (
    ProviderCallError,
    ProviderTimeoutError,
    StructuredOutputError,
)
from .models import (
    CallRecord,
    DegradedMarker,
    LastAttempt,
    ReasoningRequest,
    SentimentResponse,
    SynthesisResponse,
)
from .outcome import Outcome
from .pricing import PriceTable
from .prompt_builder import PromptBuilder
from .provider_config import ProviderCfg
from .registry import ProviderRegistry
from .reliability.circuit_breaker import CircuitBreakerRegistry
from .reliability.health import HealthMonitor
from .reliability.retry import RetryPolicy, Sleep
from .reliability.router import Router
from .reliability.timeout import TimeoutPolicy
from .structured_output import StructuredOutputValidator
from .types import CallParams, RawProviderResult, RenderedPrompt

# Injected clocks: created_at wall-clock, latency reader (ms), breaker cool-down reader (seconds).
Clock = Callable[[], datetime]
MonotonicMs = Callable[[], int]
MonotonicSeconds = Callable[[], float]
CallRecorder = Callable[[CallRecord], None]


def _default_clock() -> datetime:  # pragma: no cover - trivial default, overridden in tests
    return datetime.now(timezone.utc)


def _zero_ms() -> int:  # pragma: no cover - trivial default
    return 0


def _iso_z(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class LLMGateway:
    def __init__(
        self,
        registry: ProviderRegistry,
        prompt_builder: PromptBuilder,
        validator: StructuredOutputValidator,
        adapters: Mapping[str, ProviderAdapter],
        recorder: CallRecorder | None = None,
        clock: Clock = _default_clock,
        monotonic_ms: MonotonicMs | None = None,
        monotonic_s: MonotonicSeconds | None = None,
        sleep: Sleep | None = None,
        health: HealthMonitor | None = None,
        price_table: PriceTable | None = None,
    ) -> None:
        self._registry = registry
        self._prompt_builder = prompt_builder
        self._validator = validator
        self._adapters = dict(adapters)
        self._recorder = recorder
        self._clock = clock
        self._monotonic_ms = monotonic_ms if monotonic_ms is not None else _zero_ms
        # Breaker cool-down uses a seconds reader; default derives from the ms reader.
        self._monotonic_s = (
            monotonic_s if monotonic_s is not None else (lambda: self._monotonic_ms() / 1000.0)
        )
        self._sleep = sleep
        self._price_table = price_table
        cfg = registry.config
        self._router = Router(cfg.routing.strategy)
        self._breakers = CircuitBreakerRegistry(cfg.defaults.circuit_breaker, self._monotonic_s)
        self._health = health if health is not None else HealthMonitor()

    @property
    def health(self) -> HealthMonitor:
        """Operational health view (ADR-007 D-7) — never feeds any deterministic output."""
        return self._health

    # --- MarketReasoner port -----------------------------------------------------------
    def analyze_sentiment(self, request: ReasoningRequest) -> SentimentResponse | DegradedMarker:
        outcome = self._run(request, LlmJob.SENTIMENT)
        if isinstance(outcome, DegradedMarker):
            return outcome
        return self._validator.build_sentiment(outcome)

    def synthesize(self, request: ReasoningRequest) -> SynthesisResponse | DegradedMarker:
        outcome = self._run(request, LlmJob.SYNTHESIS)
        if isinstance(outcome, DegradedMarker):
            return outcome
        return self._validator.build_synthesis(outcome)

    # --- failover chain (ADR-011 DR-1) -------------------------------------------------
    def _run(self, request: ReasoningRequest, job: LlmJob) -> dict[str, object] | DegradedMarker:
        prompt = self._prompt_builder.build(request)
        chain = self._router.order(self._registry.enabled_providers(), seed=request.run_id)
        if not chain:
            return DegradedMarker(
                job=job,
                reason="no enabled providers configured",
                last_attempt=LastAttempt(provider="none", model_id="none"),
            )

        last_provider = chain[-1]
        last_model = self._registry.call_params_for(last_provider, job.value).model_id
        last_reason = "all providers exhausted"

        for attempt_index, provider in enumerate(chain):
            params = self._registry.call_params_for(provider, job.value)
            last_provider, last_model = provider, params.model_id
            breaker = self._breakers.for_provider(provider.name)

            if not breaker.allows():
                self._emit(
                    self._record(
                        request,
                        job,
                        attempt_index,
                        provider,
                        params,
                        prompt,
                        None,
                        Outcome.CIRCUIT_OPEN,
                        0,
                        0,
                    )
                )
                self._health.record(provider.name, Outcome.CIRCUIT_OPEN.value, 0)
                last_reason = f"{provider.name}: circuit open"
                continue

            data, record, ok, reason = self._try_provider(
                request, job, attempt_index, provider, params, prompt
            )
            self._emit(record)
            self._health.record(provider.name, record.outcome, record.latency_ms)
            if ok:
                breaker.record_success()
                assert data is not None
                return data
            breaker.record_failure()
            last_reason = reason

        # Chain exhausted → Degraded Run (never abort).
        return DegradedMarker(
            job=job,
            reason=last_reason,
            last_attempt=LastAttempt(provider=last_provider.name, model_id=last_model),
        )

    def _try_provider(
        self,
        request: ReasoningRequest,
        job: LlmJob,
        attempt_index: int,
        provider: ProviderCfg,
        params: CallParams,
        prompt: RenderedPrompt,
    ) -> tuple[dict[str, object] | None, CallRecord, bool, str]:
        """Attempt one provider with retry + timeout. Returns (data, record, ok, reason)."""
        defaults = self._registry.config.defaults
        retries = provider.retries if provider.retries is not None else defaults.retries
        retry = RetryPolicy(
            retries=retries,
            backoff=defaults.backoff,
            sleep=self._sleep if self._sleep is not None else (lambda _s: None),
        )
        timeout = TimeoutPolicy(params.timeout_seconds, self._monotonic_ms)
        elapsed_holder = {"ms": 0}

        def _attempt() -> RawProviderResult:
            result, elapsed = timeout.run(
                provider.name, lambda: self._call(provider, prompt, params)
            )
            elapsed_holder["ms"] = elapsed
            return result

        try:
            result, retries_used = retry.run(_attempt)
            data = self._validator.parse_json(result.text)
            self._validator.validate(job, data)
        except ProviderTimeoutError as exc:
            record = self._record(
                request,
                job,
                attempt_index,
                provider,
                params,
                prompt,
                None,
                Outcome.TIMEOUT,
                elapsed_holder["ms"],
                0,
            )
            return None, record, False, str(exc)
        except (ProviderCallError, StructuredOutputError) as exc:
            record = self._record(
                request,
                job,
                attempt_index,
                provider,
                params,
                prompt,
                None,
                Outcome.ERROR,
                elapsed_holder["ms"],
                0,
            )
            return None, record, False, str(exc)

        record = self._record(
            request,
            job,
            attempt_index,
            provider,
            params,
            prompt,
            (result, data),
            Outcome.SUCCESS,
            elapsed_holder["ms"],
            retries_used,
        )
        return data, record, True, ""

    def _call(
        self, provider: ProviderCfg, prompt: RenderedPrompt, params: CallParams
    ) -> RawProviderResult:
        adapter = self._adapters.get(provider.name)
        if adapter is None:
            raise ProviderCallError(f"no adapter bound for provider {provider.name!r}")
        return adapter.complete(prompt, params)

    # --- Call Record construction ------------------------------------------------------
    def _record(
        self,
        request: ReasoningRequest,
        job: LlmJob,
        attempt_index: int,
        provider: ProviderCfg,
        params: CallParams,
        prompt: RenderedPrompt,
        success: tuple[RawProviderResult, dict[str, object]] | None,
        outcome: Outcome,
        latency_ms: int,
        retries: int,
    ) -> CallRecord:
        result = success[0] if success is not None else None
        data = success[1] if success is not None else None
        input_tokens = result.input_tokens if result is not None else None
        output_tokens = result.output_tokens if result is not None else None
        # Automatic, versioned cost (ADR-007 D-6): only on a completed call with a price table.
        estimated_cost = (
            self._price_table.estimate(params.model_id, input_tokens, output_tokens)
            if (self._price_table is not None and result is not None)
            else None
        )
        return CallRecord(
            run_id=request.run_id,
            llm_job=job,
            attempt_index=attempt_index,
            provider=provider.name,
            model_id=params.model_id,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_hash,
            rendered_prompt=prompt.text,
            response=data,
            response_hash=content_hash(data) if data is not None else None,
            latency_ms=max(0, latency_ms),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            retries=retries,
            finish_reason=result.finish_reason if result is not None else None,
            outcome=outcome.value,
            created_at=_iso_z(self._clock()),
        )

    def _emit(self, record: CallRecord) -> None:
        if self._recorder is not None:
            self._recorder(record)

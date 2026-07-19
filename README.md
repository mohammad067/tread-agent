# Market State Engine

A deterministic, explainable, auditable engine that produces a **Market State** — a structured snapshot of
market conditions — every 6 hours and after major macro events, across six assets plus a Global Regime.
**API-only, no front-end** ([ADR-012](docs/adr/ADR-012-api-only-no-frontend.md)). Not a price predictor,
not an advisor.

## Status

- **Milestone 0** — Product foundation ✅ (`docs/product/`)
- **Milestone 1** — Architecture foundation ✅ (`docs/architecture/`, `docs/adr/`)
- **Milestone 2** — Contracts & schemas ✅ (`docs/contracts/`)
- **Milestone 3** — Deterministic core 🔨 (in progress, implemented in reviewable batches M3.1…M3.10)

## Architecture in one line

Deterministic core owns **all numbers** (features, rules, scoring, regime, MHI, confidence, guardrails). The
External LLM Provider is reached **only** through the frozen `MarketReasoner` port and does exactly three
jobs (news sentiment, novelty, Persian summaries). Everything is replayable and versioned.

See [docs/architecture/overview.md](docs/architecture/overview.md).

## Development

Requires Python 3.10+ (frozen stack targets 3.12+; code is forward-compatible).

```bash
python -m venv .venv
# Windows (Git Bash):
source .venv/Scripts/activate
python -m pip install -e ".[dev]"

# quality gates (also available via the Makefile targets):
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy
python -m pytest --cov --cov-report=term-missing
lint-imports                  # import-linter: Clean-Architecture boundary
```

## Repository layout

Canonical structure per [master prompt §10](md/00-master-promt.md); `config/`, `rules/`, `prompts/`,
`schemas/` live **outside** `src/` because they are versioned data reviewed by non-engineers. See
[docs/architecture/deployment.md](docs/architecture/deployment.md).

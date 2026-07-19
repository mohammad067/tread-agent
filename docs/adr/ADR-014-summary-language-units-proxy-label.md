# ADR-014: Summary language (FA-only), USD/IRR units (IRT), and proxy labeling (internal-only)

- **Status:** Accepted (2026-07-19) — resolves the last three open contract items before Milestone 2.
- **Deciders:** Product Manager + reviewer (user directive), with Senior Trader (units) and Senior Blockchain
  Engineer (proxy) personas consulted.
- **Resolves:** Open Items **O1**, **D1**, **D2** (previously in
  [../product/00-decisions-and-open-items.md](../product/00-decisions-and-open-items.md) and
  [../architecture/evolution-roadmap.md §5](../architecture/evolution-roadmap.md)).
- **Related:** ADR-009 (crypto/USD-IRR aggregation), ADR-012 (API-only), release policy.

## Context
Three items were deliberately left open pending a product decision because each touches the **frozen v1.0.0
schema** and could not be guessed: the human-summary language (O1), the USD/IRR unit (D1), and whether the
USDT/IRT proxy nature is surfaced to consumers (D2). Milestone 2 freezes the schema, so these had to be
resolved first.

## Decision

### O1 — Summary language: **Persian only (FA)**
- The MVP generates **only `human_summary_fa`**. **No `human_summary_en`** in the v1.0.0 schema.
- Bilingual support is **removed from MVP scope**.
- English support may be added later as a **MINOR** schema version (additive optional field) if a need is
  demonstrated — this is now the *only* forward path, and it is backward-compatible by construction.

### D1 — USD/IRR units: **IRT (Toman)**
- The USD/IRR reference is the **USDT/IRT proxy** from the configured market-data source (kifpool
  `priceSellIRT`).
- All values are **stored and returned in IRT (Toman)**. `price.currency = "IRT"` for `USD_IRR`.
- The earlier `rial_multiplier: 10` idea is **dropped from the contract** — there is no Rial field and no
  dual-unit representation in v1.0.0; a consumer that wants Rial multiplies by 10 itself. (Keeping a
  multiplier field would imply we also serve Rial, which we do not.)

### D2 — Proxy label: **not surfaced in the standard API/UI**
- The value is presented plainly as `USD/IRR` with its number (e.g., `103000`). **No "USDT Proxy" or similar
  wording** appears next to the value in the normal API response or any consumer UI.
- The proxy fact is **recorded internally only**: in the Domain Dictionary, this ADR, the decision log, and
  engineering docs. It is **not** a payload field and **not** a required consumer-facing disclosure.
- **This reverses** the earlier Milestone 0 stance that treated the proxy nature as a must-be-discoverable
  truth-in-labeling obligation (former compliance §6 "source-transparency obligation" and a traceability
  "gap"). That obligation is **withdrawn**; see Consequences.

## Alternatives Considered
- **O1 bilingual FA+EN (prior default):** rejected by the reviewer for MVP — the primary consumer is an
  Iranian/Persian-reading audience; EN prose adds synthesis surface with no confirmed MVP consumer. Additive
  later path preserved.
- **D1 Rial, or dual Rial+Toman:** rejected — the source is Toman; a single canonical unit avoids conversion
  ambiguity; no consumer asked for Rial in the contract.
- **D2 surface the proxy (`proxy_note` field or UI label):** rejected by the reviewer — the product presents
  USD/IRR as a clean reference number; the proxy detail is an implementation fact, not consumer-facing.

## Consequences
- (+) The v1.0.0 schema is simpler: one summary field, one USD/IRR unit, no proxy field. Fewer fields to
  freeze, all mapped to a need.
- (+) A clean additive path for EN later (MINOR bump), consistent with the release policy.
- (−/accepted risk) **Not surfacing the proxy** means a consumer cannot see, from the payload, that USD/IRR is
  a USDT/IRT proxy that can diverge during USDT depegs or cash-premium episodes. The reviewer accepts this
  presentation choice. **Mitigation retained internally:** the proxy nature and its divergence risk stay
  documented (dictionary + this ADR + decision log), and cross-source/deviation monitoring for the USDT proxy
  remains an engineering concern (ADR-009) even though it is not a payload disclosure.
- Compliance's former **§6 source-transparency obligation** (discoverable USD/IRR proxy) is **withdrawn** for
  the consumer surface and restated as an internal documentation note. (Note: compliance rule **C-6** —
  degraded-run disclaimer compliance — is unrelated and unchanged.)

## Freeze
O1, D1, D2 are **Resolved and frozen**. They are removed from all Open Questions lists. Changing any of them
(e.g., adding EN, surfacing the proxy, or serving Rial) requires a schema version bump per the release policy
and a superseding note referencing this ADR.

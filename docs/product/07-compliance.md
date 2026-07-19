# Compliance & Disclaimer Framing

> **Milestone 0 deliverable.** How the product frames itself legally and ethically as **market observation,
> not investment advice**, and the binding requirements for disclaimer text and placement.
> **Working jurisdiction assumption:** generic non-advice framing, no jurisdiction-specific regulatory text
> (Open Item O4 — revise if you specify Iran/EU/US framing).
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md).
> **Version:** 0.1.0

---

## 1. Positioning statement (the legal spine)

The Market State Engine produces a **market Observation**: a structured, explainable description of market
conditions. It is **not**:

- investment advice, a recommendation, or a solicitation to buy/sell/hold any asset;
- a prediction, forecast, or price target;
- a personalized or suitability-assessed output for any individual.

This positioning is not cosmetic — it is enforced end-to-end by product design: the External LLM Provider
never advises (F-4),
scores are observations not directives (F-3), and the UX bans advice language (UX-1). Compliance is a
**product invariant**, not a footer.

## 2. Disclaimer text (canonical)

**Payload disclaimer (English, `disclaimer` field), canonical MVP text:**

> "This is a market observation, not investment advice. Confidence values are system confidence, not
> calibrated probabilities."

**API envelope disclaimer (`meta.disclaimer`), short form:**

> "Market observation only. Not investment advice."

**UI disclaimer (Persian, for P1 surfaces), canonical:**

> «این خروجی یک مشاهده‌ی بازار است، نه توصیه‌ی سرمایه‌گذاری. مقادیر «اطمینان»، اطمینان سیستم هستند و احتمال
> کالیبره‌شده محسوب نمی‌شوند.»

> These strings are **content contracts**. Changing them is a release-policy event
> ([10-release-policy.md](10-release-policy.md)), not an ad-hoc edit.

## 3. Placement requirements (binding)

| # | Requirement | Level | Verified by |
|---|-------------|-------|-------------|
| C-1 | Every `MarketStateRun` payload carries a non-empty `disclaimer` field. | MUST | Contract test (schema `required`) |
| C-2 | Every API response carries `meta.disclaimer`. | MUST | Contract test |
| C-3 | Any UI screen displaying a Market State shows the disclaimer visibly (not footer-only, not behind a dismissible-and-forgotten modal). | MUST (consumer contract) | M-C-3 (UI review) |
| C-4 | `confidence`/`regime.confidence` are labeled "system confidence," never "probability." | MUST | UX-2 + M-C-4 |
| C-5 | No surface renders advice/recommendation/price-target language. | MUST | UX-1 + guardrail content check |
| C-6 | Degraded/fallback runs remain disclaimer-compliant and are marked degraded. | MUST | UC-7 + contract test |

## 4. What compliance forbids in outputs

- **No advice verbs:** recommend, advise, suggest (to trade), buy, sell, hold, allocate.
- **No predictions:** will rise/fall, target, expected price, guaranteed.
- **No suitability language:** "right for you," "your portfolio."
- **No probability framing of confidence.**

These are enforced at three layers: (1) prompt constraints on the External LLM Provider's Call #2,
(2) deterministic guardrail content
checks before publish, (3) UX copy rules. Defense in depth — no single layer is trusted alone.

## 5. Data & privacy posture

- **No PII** is collected, processed, or stored anywhere in the system (§12 Security). The product handles
  market data only.
- Upstream API keys are **read-only, market-data scope** (including the internal kifpool source).
- The static API key on external endpoints is access control, not user identity — there are no user accounts
  (§3).

## 6. Source-transparency posture (data integrity)

- **USD/IRR is internally a USDT/IRT proxy** (kifpool `priceSellIRT`), not a true interbank USD/IRR rate.
  **Per ADR-014, the proxy nature is NOT surfaced in the standard API/UI** — `USD_IRR` is presented plainly
  with its number and `currency: "IRT"`. The proxy fact is recorded **internally only** (Domain Dictionary,
  ADR-014, engineering docs); there is **no `proxy_note` payload field** and no required consumer-facing
  disclosure. *(This withdraws the earlier "must be discoverable" truth-in-labeling obligation; the reviewer
  accepted this presentation choice — see ADR-014 Consequences for the accepted risk.)*
- The proxy's **divergence risk** (USDT depeg / cash premium) remains an **engineering** concern monitored via
  cross-source/deviation checks (ADR-009), even though it is not a payload disclosure.
- **BTC Dominance methodology** (stablecoin inclusion) is documented (ADR-009); the number's meaning is
  reproducible.

## 7. Open compliance items

| # | Item | Default | Escalate if |
|---|------|---------|-------------|
| O4 | Jurisdiction-specific regulatory framing | Generic non-advice text (above) | You operate in a regulated context (e.g., licensed advisory, EU MiFID, specific Iranian regulations) — then jurisdiction-reviewed text replaces the canonical strings via a release event. |
| — | Legal review of canonical disclaimer strings | Assumed sufficient for an internal/observational tool | Product is exposed to external retail consumers — obtain legal sign-off before GA. |

> **Bottom line:** the disclaimer is necessary but not sufficient. The product is compliant because it is
> *designed* not to advise — the disclaimer states plainly what the architecture already guarantees.

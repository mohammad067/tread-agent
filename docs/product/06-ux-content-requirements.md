# UX & Content Requirements

> **Milestone 0 deliverable.** **Binding requirements for UI builders** consuming the JSON contract. We do not
> build the UI (§3), but these constraints are part of the product contract: a UI that violates them ships a
> non-compliant product. Includes the **style guide for `human_summary_fa`**.
> Terms per [09-domain-dictionary.md](09-domain-dictionary.md); compliance in
> [07-compliance.md](07-compliance.md).
> **Version:** 0.1.0

**Requirement levels:** **MUST** (mandatory, testable), **SHOULD** (strong default), **MAY** (permitted).

---

## 1. Framing & language (the non-negotiables)

- **UX-1 (MUST):** Every surface frames output as a **market Observation**, never advice, prediction, or a
  buy/sell signal. Banned words in UI copy: *predict, forecast, buy, sell, recommend, signal (to trade),
  target price, guaranteed*. (Domain Dictionary "banned terms.")
- **UX-2 (MUST):** `confidence` is **always** labeled **"system confidence"** (Persian: «اطمینان سیستم»),
  **never** "probability," "chance," or "%likely." A raw `0.72` rendered as "72% probability" is a defect.
- **UX-3 (MUST):** The **disclaimer** (from `disclaimer` / `meta.disclaimer`) is visible on any screen that
  shows a Market State — not buried in a footer-only modal. (See [07-compliance.md](07-compliance.md).)

## 2. Honesty of numbers

- **UX-4 (MUST):** `computed` and `ordinal` driver weights are **visually distinct**. Example: `computed`
  drivers show a real percentage bar; `ordinal` drivers show a labeled chip (Dominant/Major/Moderate/Minor)
  **without** a percentage. Rendering an ordinal level as a fake percentage is a defect. (PRD X-3.)
- **UX-5 (MUST):** A `computed` weight is shown as a percentage; an `ordinal` `level` is shown as its label.
  The UI **MUST NOT** invent a percentage for an ordinal driver.
- **UX-6 (SHOULD):** MHI (0–100) uses a consistent, colorblind-safe scale (not red/green-only). Pair color
  with a number/label so meaning survives for colorblind users.

## 3. Staleness & data gaps

- **UX-7 (MUST):** When `price.is_stale = true`, the price is **dimmed/greyed** and accompanied by a **stale
  note** derived from `stale_reason` (e.g., «بازار تهران تعطیل است»). A stale price must never look identical
  to a fresh one. (PRD X-4.)
- **UX-8 (MUST):** `data_gaps[]` entries are surfaced as visible notes on the affected asset (e.g., "informal
  overnight quotes excluded"), not hidden.
- **UX-9 (SHOULD):** Show `price.as_of` and `generated_at` timestamps in the user's locale so freshness is
  self-evident.

## 4. Regime & change markers

- **UX-10 (MUST):** When `regime.changed_this_run = true`, show a **regime-change marker** on the Timeline at
  that Run, with `previous_state → state`.
- **UX-11 (SHOULD):** The four Regime states have stable, distinct visual identities: `risk_on`, `risk_off`,
  `transition`, `event_driven`. `event_driven` SHOULD reference the driving event (`trigger_detail`).
- **UX-12 (MUST):** `regime.confidence` is rendered as **system confidence** (UX-2), not as a probability of a
  regime.

## 5. Alerts & severities

- **UX-13 (MUST):** `guardrail_flags[]` are surfaced with a severity treatment. Minimum severity vocabulary:
  `info` (note), `warning` (amber — e.g., data-gap, source-deviation), `critical` (red — e.g., degraded
  fallback run, guardrail block). The exact palette is the UI's, but the three tiers are mandatory.
- **UX-14 (MUST):** A **Degraded Run** (all External LLM Providers failed → rule-engine-only) is visibly marked as degraded
  so users don't read a partial state as complete. (UC-7.)
- **UX-15 (SHOULD):** Alerts link to the affected asset/field, not just a global banner.

## 6. Causal graph (drill-down)

- **UX-16 (MUST):** The causal graph renders **only** edges present in `causal_links[]`; the UI must not
  invent or infer edges. Each edge shows `from → to`, `direction`, and the `via_rule` id (with the rule's
  `economic_rationale` available on demand — serves P4).
- **UX-17 (SHOULD):** Clicking an `activated_rule` reveals its `economic_rationale`, `strength`, `horizon`,
  and `decay_remaining`.

## 7. Summary language (resolved — ADR-014)

- **UX-18 (MVP):** The summary is **Persian only** (`human_summary_fa`) — ADR-014. Consumers present the
  Persian summary as-is. (If a future MINOR schema adds `human_summary_en`, a consumer may then offer a
  language preference; not in MVP.)
- **UX-19 (MUST):** Numeric fields, enums, and units are language-independent; only the prose field
  (`human_summary_fa`, driver `detail`) is localized (Persian).

---

## 8. Style guide — `human_summary_fa`

The Persian human summary is the product's voice to P1/P4. It **describes and explains; it never advises**.

**Language & tone**
- **Language:** Standard, professional Persian (فارسی رسمی و روان). No slang, no emoji, no exclamation.
- **Register:** Neutral-analytical, like a desk note — confident about *observation*, humble about the future.
- **Tense:** Present/past for what *is/has happened* («منتشر شد»، «فشار فروش وارد کرده است»). **No future
  predictions** («خواهد رفت» is banned when it asserts a price move).

**Length & structure**
- **Length:** 1–3 sentences per asset (target 25–60 Persian words). Long enough to explain the driver, short
  enough to read at a glance.
- **Structure (recommended):** (1) the salient move/condition, (2) the driver/why (tie to the activated Rule
  or indicator), (3) an honest qualifier (volatility/uncertainty/staleness) when relevant.

**Content rules (MUST)**
- **S-1:** Reference **only numbers present in the request** (grounding constraint mirrors F-4). No invented
  figures.
- **S-2:** **No advice, no recommendations, no price targets, no directional calls to action.** Describe the
  state; do not tell the reader what to do.
- **S-3:** Attribute causes to the activated Rule / indicator, not to speculation («به دنبال انتشار CPI
  بالاتر از انتظار…»), matching `causal_links`.
- **S-4:** Represent uncertainty honestly: if `confidence` is low or data is stale, the summary says so
  («با توجه به تعطیلی بازار، این ارزیابی با احتیاط ارائه می‌شود»).
- **S-5:** Use the **Domain Dictionary Persian glosses** for domain terms (رژیم، امتیاز ریسک، شاخص سلامت
  بازار…). Consistency across runs is mandatory.

**Banned in `human_summary_fa`**
- Future price assertions, buy/sell language, «پیشنهاد می‌شود»/«توصیه»/«بخرید»/«بفروشید», probability language
  for confidence, superlatives implying certainty («قطعاً»، «حتماً صعودی»).

**Golden example (from §11.1 — compliant):**
> «شاخص CPI آمریکا بالاتر از انتظار منتشر شد و فشار فروش کوتاه‌مدت بر بیت‌کوین وارد کرده است. حجم معاملات نزدیک
> به دو برابر میانگین ۲۰ روزه است و ریسک نوسان بالا ارزیابی می‌شود. روند میان‌مدت همچنان مثبت است.»

*Why compliant:* describes the move, attributes it to the CPI surprise (a Rule), cites only present numbers
(volume ~2× 20-day avg), flags risk honestly, and makes **no** recommendation.

**Non-compliant example (a defect):**
> «CPI بالا آمد؛ بیت‌کوین ریزش خواهد کرد، بهتر است بفروشید.» ✗ (future prediction + advice — violates S-2, UX-1)

---

## 9. Acceptance & testing hooks

| Requirement | Verified by |
|-------------|-------------|
| UX-1/2/3 framing & disclaimer present | M-UX-1 (content review) + contract test that `disclaimer` is non-empty |
| UX-4/5 computed vs ordinal distinct | M-UX-2 (UI review against golden fixtures) |
| UX-7/8 stale/data-gap rendering | M-UX-3 (review against degraded golden fixture) |
| S-1…S-5 summary style | M-UX-4 (Trader/PM review) + guardrail grounding check (T-703 family) |

> These are **contract requirements on consumers**. The engine enforces what it can server-side (grounding,
> disclaimer presence, degraded-run flags); the rest is verified by review against the golden fixtures we ship
> in Milestone 2.

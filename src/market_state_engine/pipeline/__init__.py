"""Pipeline / orchestration layer (module-catalog E). Connects existing components; owns sequencing.

Sequences the frozen 10-stage lifecycle (pipelines.md §2): trigger → ingest → features → rule match
→ sentiment → scoring → regime → synthesis → guardrails → persist/publish. The LLM appears at
exactly two stages, both via the ``MarketReasoner`` port; a provider outage degrades honestly and
never aborts (ADR-011). This layer contains **no** market math and **no** vendor knowledge — it
calls the deterministic core and the reasoning port and persists the result through repositories.
"""

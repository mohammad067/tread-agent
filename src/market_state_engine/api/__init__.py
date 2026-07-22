"""API layer — FastAPI presentation (module-catalog G1, api-design.md). Read-optimized, API-only.

Serves the JSON contract with a uniform ``data`` + ``meta`` envelope and an ``Error`` shape.
No computation on the request path (numbers are precomputed + persisted); no business logic here.
Two guarded operational writes (events, runs:trigger) sit behind the write API key. Endpoints match
the frozen catalog exactly — no redesign.
"""

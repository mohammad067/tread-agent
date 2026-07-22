"""Application composition root (dependency injection) — wires every service from config (M5).

No business logic lives here or in the API/repositories; this module only *constructs* the object
graph: config bundle, rulebook, database, the reasoning gateway (live or replay), the pipeline
orchestrator, run service, and scheduler. Everything is built from the existing configuration system
(no hardcoded values). The API layer receives a fully-wired container and calls into it.
"""

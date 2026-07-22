"""Evaluation layer — replay, ablation, metrics, evaluation, validation, reporting (Milestone 6).

Production tooling that reads the immutable Event Log (run_inputs/run_outputs/call_records/events)
and re-runs pipeline variants offline through ``ReplayProvider`` — never a live provider. Every
component here is read-and-recompute over stored data (module-catalog F); it changes no market
number, touches no schema, and reuses the M4/M5 abstractions (``verify_replay``,
``build_replay_adapters``, the ``PipelineOrchestrator``, repositories, the container). Outcomes are
recorded to the append-only ``event_log`` (its ``event_type`` is free-form, so no migration needed).
"""

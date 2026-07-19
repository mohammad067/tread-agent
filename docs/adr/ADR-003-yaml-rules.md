# ADR-003: YAML rules instead of DB/vector store (with migration threshold)

- **Status:** Accepted (2026-07-19)
- **Deciders:** Principal Architect, Senior Trader
- **Related:** ADR-001, ADR-008 (sign-off gate)

## Context
The rulebook is **dozens** of rules, not thousands. Rules are reviewed by a non-engineer (the Senior Trader
persona) and must be versioned, diff-able, and shipped with an `economic_rationale`. Options: YAML files, a SQL
table, or a vector store.

## Decision
Rules live in **versioned YAML** under `rules/` (`global/`, `assets/`), with a `VERSION` file. **Migrate to SQL
only past ~50 rules**; use a **vector store only if** free-text knowledge retrieval is ever needed (not in
MVP). Every rule change bumps the rulebook version and snapshots to `rules_versions`.

## Alternatives Considered
- **SQL-backed rules now**: rejected — adds a migration/admin surface with no MVP benefit at dozens of rules;
  loses effortless git review by the Trader. (Reserved for Phase 2 dynamic rules / hot-reload.)
- **Vector store**: rejected — there is no free-text retrieval need; rules are structured triggers/effects, not
  documents. (Explicit non-goal, §3.)

## Consequences
- (+) Git-reviewable by non-engineers; trivial versioning; hard sign-off gate enforceable at load (ADR-008).
- (−) No runtime hot-reload (a change needs a deploy) — acceptable at MVP cadence; Phase 2 addresses it.
- **Migration threshold (~50 rules)** is the documented trigger to revisit; recorded so the decision is not
  silently overrun.

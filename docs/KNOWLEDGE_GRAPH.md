# Evidence-backed knowledge graph

DP-GRAPH-002 extends the existing entity and relation tables instead of introducing a separate graph database.

## Canonical boundary

Relations have one of three states: `proposed`, `canonical`, or `rejected`. Existing callers remain backward compatible and create canonical relations unless they explicitly choose another state.

Automated/model enrichment is suggestion-only. `POST /v1/graph/suggestions` receives a bounded entity set and retrieves bounded evidence from one authorized collection. The reasoning provider may suggest aliases and relations, but returned entity IDs and chunk IDs are validated against that supplied context. Suggestions do not mutate graph state.

A proposed relation must include chunk evidence. It is excluded from normal relation reads and graph traversal until `POST /v1/entity-relations/{id}/review` explicitly promotes it to canonical. Rejection is retained for audit history.

## Evidence and time

Relation evidence continues to use the existing validated collection/resource/document/chunk chain. Optional `valid_from` and `valid_to` describe when the asserted relationship applies; invalid intervals are rejected.

## Traversal

`GET /v1/entities/{entity_id}/graph` performs bounded breadth-first traversal over canonical relations only. Depth is capped at 5 and result count is bounded. Existing API authentication/consumer policy remains in force.

This layer is intentionally PostgreSQL-backed. A dedicated graph database should only be introduced if measured traversal scale or query complexity makes it necessary.

# Technical Tradeoffs & Constraints: Carbon Accounting Ledger

This document details the trade-offs and compromises accepted in the design of the carbon ledger platform.

## 1. Relational Database Scaffolding (SQLite vs. PostgreSQL)
* **Tradeoff**: SQLite was chosen for development and unit testing, while the models are structured to support a production-ready PostgreSQL instance in a live environment.
* **Pros**: SQLite enables instant local execution, requiring no external docker-compose or database setup for evaluations.
* **Cons**: SQLite lacks native support for Postgres' `JSONB` fields (Django falls back to a text representation). It also lacks native high-concurrency locking, which is critical for multi-tenant SaaS scaling.
* **Mitigation**: Database configs support dynamic environment switches. In production (e.g. Render/Railway), django will automatically bind to PostgreSQL via the `DATABASE_URL` setting.

## 2. Ingestion Performance vs. Strict Audit Integrity
* **Tradeoff**: Ingested rows are stored in full raw JSON format before running the normalizer, and manual corrections must update the raw JSON fields rather than the normalized output fields directly.
* **Pros**: The raw input payload acts as an immutable "source of truth". Analysts cannot change the normalized CO2 figures directly; they can only fix errors in the input data (such as plant codes or consumption figures) and trigger a re-run. This keeps the calculation logic deterministic and audible.
* **Cons**: Manual correction requires editing JSON strings or form structures, which has a slightly higher UI interaction cost than directly typing into columns.
* **Mitigation**: The React frontend provides an override pane with error checking. If an analyst enters invalid JSON, the frontend blocks submission.

## 3. Haversine Distance Fallback for Flight Bookings
* **Tradeoff**: When flight booking payloads lack explicit distances (miles/km), the backend automatically falls back to calculating the great-circle distance between airport coordinates.
* **Pros**: Prevents the row from failing entirely when external API partners omit distance metadata. Calculates realistic coordinates for major global airports using a built-in coordinates registry.
* **Cons**: Great-circle distance calculations do not account for flight detours, holding patterns, or layovers. It represents the theoretical minimum path.
* **Mitigation**: When the Haversine fallback is activated, the parser records a warning warning in the validation log: `"Distance missing. Calculated JFK-LHR distance of 5570.26 km via coordinates."` The status is set to `SUSPICIOUS` so an analyst can review it.

## 4. Logical Multi-Tenancy vs. Physical DB Isolation
* **Tradeoff**: We chose a shared-database, shared-schema (logical) multi-tenancy model over separate database schemas.
* **Pros**: Simple to deploy, cost-efficient, and easy to run migrations.
* **Cons**: Risks "noisy neighbor" queries affecting performance and carries a higher risk of data leakage if developer scoping queries are written incorrectly.
* **Mitigation**: All API views filter querysets strictly by `tenant_id` at the entrypoint. Database constraints and lookup maps are also logically isolated.

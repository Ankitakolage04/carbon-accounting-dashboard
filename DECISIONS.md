# Architectural Design Decisions: Carbon Accounting Ledger

This document details the primary technical design decisions made when building the Carbon Emissions Ingestion and Audit platform.

## 1. Multi-Tenant Strategy
* **Decision**: Single-database logical partitioning using foreign keys.
* **Rationale**: Carbon accounting dashboards are typically SaaS tools. We chose to enforce tenant scoping on every model (`Tenant` foreign key) to support clean logical separation. This balances operational simplicity with robust scoping. 
* **API Protection**: Tenant IDs are included in query params and payload fields, allowing future API Gateway filters to automatically validate requests against tenant keys.

## 2. Ingestion Lifecycles & State Machine
* **Decision**: All raw rows follow a four-state state machine: `PENDING` ➔ `APPROVED` or `SUSPICIOUS` or `FAILED`.
* **Rationale**: Real-world data is noisy. 
  - `FAILED`: Rows with syntactically unparseable dates or negative metric amounts. These rows are excluded from calculation engines.
  - `SUSPICIOUS`: Rows with syntactically valid formats but anomalous parameters (e.g. unknown plant codes, unit rate outliers, billing period overlaps). These rows compute *draft* carbon figures so analysts can see the potential impact, but cannot be approved without manual inspection.
  - `APPROVED`: Once approved, the record is locked. Subsequent edits or overrides are blocked to maintain chronological ledger stability for audit preparation.

## 3. Data Normalization & Unit Conversions
* **Decision**: All quantities are converted to standardized SI units at rest.
  - Fuel ➔ `L` (Liters)
  - Power ➔ `kWh` (Kilowatt-hours)
  - Transport ➔ `km` (Kilometers)
* **Rationale**: SAP exports and Webhooks use varying units (e.g. US plants outputting US Gallons, UK flight trackers outputting Miles). Normalizing to standard metric units allows simple, unified aggregation in downstream reporting and chart generation.

## 4. Anomaly and Suspicious Data Thresholds
To capture operational outliers before they corrupt official reporting, the ingestion parser enforces the following rules:

### A. SAP MM Fuel Purchasing
* **Fuel Unit Price Validation**: Checks if the unit price (`Cost / Volume`) lies within historical normal bounds:
  - Diesel: `€0.40 - €4.50` per Liter.
  - Petrol: `€0.40 - €4.50` per Liter.
  - If the price is higher (e.g., indicating an inflation typo like writing $10/L instead of $1.00), it flags the row as `SUSPICIOUS`.
* **Plant Verification**: Checks if the plant code (`WERKS`) exists in `PlantLookup`. If the plant is unknown, it flags the row as `SUSPICIOUS`.

### B. Utility Statements
* **Billing Period Bounds**: Utility bills must span between `20` and `40` days. If a bill spans less than 20 days or more than 40, it flags the row as `SUSPICIOUS` (indicates a missing statement or overlapping utility cycle).
* **Billing Period Overlap**: Checks if a new bill overlaps in date ranges with an existing billing cycle for the *same meter*. If an overlap is detected, it flags the row as `SUSPICIOUS` to prevent double-counting.
* **Rate Outliers**: Utility electricity rates must reside between `$0.02` and `$0.60` per kWh. Outliers are marked `SUSPICIOUS`.

### C. Corporate Travel
* **Cost & Distance Thresholds**: 
  - Flight costs must not exceed `$25,000`.
  - Flight distances must not exceed `20,000 km`.
  - Hotel durations must not exceed `30 days`.
  - Hotel night costs must not exceed `$2,000`.
  - Ground rental mileage must not exceed `5,000 km`.
  - Exceeding any of these triggers `SUSPICIOUS` status.

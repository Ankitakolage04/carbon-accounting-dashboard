# Industry Data Sources & Mapping Reference: Carbon Ingestion

This document details the real-world research and assumptions used to design the ingestion parsers for SAP, Utility, and Corporate Travel integrations.

---

## 1. SAP ERP: Material Management (MM) Procurement & Fuels
In industrial operations, fuel consumption (Scope 1) and raw material procurement (Scope 3) are typically exported from SAP Material Management (MM) reports or Financial Accounting (FI) logs.

### Realistic Export Formats
* **Export Mechanism**: SAP systems typically export transactional data via flat CSV files, fixed-width text files, or OData services. In this application, we implemented a flat CSV export format reflecting a typical `SAP List Viewer` download.
* **German Technical Headers**: Standard SAP tables retain historic German abbreviations for field names. Our parser maps these headers to their semantic equivalents:
  - `BUDAT` (Buchungsdatum): Posting Date.
  - `MENGE` (Menge): Quantity purchased.
  - `MEINS` (Mengeneinheit): Unit of Measure (e.g. `L` for liters, `GAL` for gallons, `PC` for pieces).
  - `WERKS` (Werk): Plant/Facility location code.
  - `WRBTR` (Wert in Hauswährung): Invoice amount in local currency.
  - `WAERS` (Währungsschlüssel): Currency key (e.g. `EUR`, `USD`).
  - `MATNR` (Materialnummer): Material ID.
  - `MAKTX` (Materialkurztext): Description of the purchased material.

### Emission Mappings
* **Fuel (Scope 1)**: If the material description indicates fuel (e.g. contains "diesel", "gasoline", "fuel"), it is mapped to Scope 1. Liter conversions are done automatically for US Gallons using standard conversion factors (`1 US Gallon = 3.78541 Liters`). We use DEFRA / EPA emission factors (Diesel: `2.68 kg CO2e/L`, Petrol: `2.31 kg CO2e/L`).
* **Procurement (Scope 3 Category 1)**: If the material is not fuel, it is categorized as purchased goods & services. We apply a spend-based emission factor to calculate estimated carbon output (`0.12 kg CO2e` per unit of currency).

---

## 2. Utility Statements (Scope 2 Electricity)
Corporate Scope 2 emissions track purchased electricity. These are extracted from monthly utility bills (e.g. PG&E, National Grid, Vattenfall).

### Dataset Fields
A typical utility CSV export includes:
* **Account/Meter Mapping**: `Account Number` and `Meter Number` associate the bill with a specific physical building in the real-world registry (`FacilityLookup`).
* **Billing Period**: `Start Date` and `End Date`. 
* **Consumption**: Metric consumption in Kilowatt-hours (`Usage_kWh` or `Consumption`).
* **Total Cost**: Financial expenditure (`Total_Amount` or `Cost`).
* **Tariff Code**: The electricity rate plan.

### Emissions Calculations & Anomaly Flags
* **Location-Based Method**: The billing address resolves to a grid subregion. If the facility is registered under `FacilityLookup`, we query its specific regional grid emission factor (e.g., US eGRID factors or European national factors). If unknown, the system falls back to a global default factor of `0.40 kg CO2e/kWh`.
* **Date Overlap Checks**: Since utility statement windows can vary, the parser scans historical entries. If a bill overlaps with another bill registered on the *same meter*, it indicates duplicate entries or human data entry errors. The system flags this as `SUSPICIOUS`.
* **Cycle Duration Checks**: Commercial bills represent a monthly cycle. The parser calculates the duration `(End Date - Start Date)`. If it is less than 20 days or more than 40, it flags the row.

---

## 3. Corporate Travel APIs (Scope 3 Category 6)
Corporate travel systems (e.g. Concur, Navan, TripActions) deliver travel booking data via webhooks or API requests.

### API JSON Layouts
Our travel parser ingests standard JSON objects representing three travel sub-types:
1. **Flights**:
   - `departure_airport` and `arrival_airport`: IATA 3-letter codes.
   - `cabin_class`: Economy, Business, or First Class (controls emissions multipliers).
   - `distance_km` or `distance_miles`: If omitted, coordinates are queried from a local database of major hubs (JFK, LHR, CDG, FRA, DXB, SIN, SYD, HND, BOM, SFO), and distance is computed via the Haversine equation.
2. **Hotels**:
   - `check_in_date` and `check_out_date`: Used to calculate nights.
   - `city` and `country`: Dictates country-specific accommodation multipliers (e.g., standard UK hotel night: `15.0 kg CO2e/night`, US hotel night: `20.0 kg CO2e/night`, generic default: `18.0 kg CO2e/night`).
3. **Ground Transport**:
   - `transport_type`: `rental_car`, `train`, or `taxi`.
   - `fuel_type` (for rental cars): `Petrol`, `Diesel`, or `Electric` (electric vehicle factor: `0.05 kg CO2e/km`, petrol: `0.18 kg CO2e/km`, train: `0.04 kg CO2e/km`).

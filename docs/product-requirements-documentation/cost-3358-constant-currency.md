# PRD: Constant Currency Exchange Rates

**Ticket**: COST-3358
**Status**: Draft
**Author**: Engineering
**Last updated**: 2026-02-13

---

## Table of Contents

- [1. Problem Statement](#1-problem-statement)
- [2. Background and Current Behavior](#2-background-and-current-behavior)
- [3. Goals and Non-Goals](#3-goals-and-non-goals)
- [4. User Stories](#4-user-stories)
- [5. Feature Design](#5-feature-design)
  - [5.1. Rate Hierarchy](#51-rate-hierarchy)
  - [5.2. Currency Pair Model](#52-currency-pair-model)
  - [5.3. Timezone Handling](#53-timezone-handling)
  - [5.4. Audit Trail](#54-audit-trail)
- [6. Data Model](#6-data-model)
- [7. API Design](#7-api-design)
  - [7.1. Endpoints](#71-endpoints)
  - [7.2. Request and Response Examples](#72-request-and-response-examples)
  - [7.3. Validation Rules](#73-validation-rules)
- [8. Query-Time Behavior](#8-query-time-behavior)
- [9. Permissions](#9-permissions)
- [10. Supported Currencies](#10-supported-currencies)
- [11. Edge Cases and Constraints](#11-edge-cases-and-constraints)
- [12. Open Decision: Timezone Approach](#12-open-decision-timezone-approach)
- [13. Out of Scope](#13-out-of-scope)
- [14. Dependencies and Risks](#14-dependencies-and-risks)
- [15. Success Criteria](#15-success-criteria)
- [16. Appendix: Current Architecture Reference](#16-appendix-current-architecture-reference)

---

## 1. Problem Statement

Today, Koku converts cost data between currencies using a dynamic exchange rate fetched daily from an external API. This rate reflects the market rate at the time of the fetch — not at the time the cost was incurred or at any rate agreed upon by the customer.

This means the same historical cost data displays different amounts depending on *when* you query it. If a customer views their January costs today, they see today's exchange rate applied. If they view the same data next week, they see next week's rate. This behavior is incorrect for customers who operate under **constant currency agreements** — contractual exchange rates negotiated with their banks for defined periods (e.g., "USD to EUR at 0.90 for Q1 2026, regardless of market fluctuations").

Without constant currency support, customers cannot rely on Koku for accurate multi-currency cost reporting that aligns with their financial planning.

## 2. Background and Current Behavior

### How currency conversion works today

1. A Celery task (`get_daily_currency_rates`) runs daily at 01:00 UTC.
2. It fetches the latest rates from an external API (`open.er-api.com/v6/latest/USD`).
3. Rates are stored in two database tables:
   - `ExchangeRates` — one row per currency with a single rate value.
   - `ExchangeRateDictionary` — a JSON matrix enabling conversion between any two supported currencies.
4. Each fetch **overwrites** the previous rates. No history is retained.
5. At **query time**, the report query handler reads the current `ExchangeRateDictionary` and annotates each cost row with an exchange rate based on the row's source currency and the user's display currency.
6. Provider maps multiply cost fields by `Coalesce(exchange_rate, 1)` in aggregate expressions.

### Key limitations

| Limitation | Impact |
|-----------|--------|
| Rates are fetched daily and overwritten | No rate history; same data shows different amounts on different days |
| No per-date rate lookup | A single rate is applied to all rows regardless of their `usage_start` date |
| No user-configurable rates | Customers cannot set contractual or budgeted exchange rates |
| No timezone awareness | All date boundaries are UTC; no per-tenant timezone setting exists |

### Relevant code references

| Component | Location |
|-----------|----------|
| Exchange rate models | `koku/api/currency/models.py` |
| Daily fetch task | `koku/masu/celery/tasks.py` (`get_daily_currency_rates`) |
| Query-time annotation | `koku/api/report/queries.py` (lines 888–903) |
| Provider map cost expressions | `koku/api/report/aws/provider_map.py`, `azure/provider_map.py`, `gcp/provider_map.py`, `ocp/provider_map.py` |
| User display currency setting | `koku/api/settings/utils.py` (`set_currency`), `koku/api/utils.py` (`get_currency`) |
| Supported currencies list | `koku/api/currency/currencies.py` |

## 3. Goals and Non-Goals

### Goals

1. Allow customers to define **fixed exchange rates** for specific currency pairs and date ranges.
2. Allow customers to define a **default constant rate** per currency pair that applies when no date-ranged rate is defined.
3. Maintain **backward compatibility** — customers who do not configure constant rates see no change in behavior.
4. Provide a clear **rate hierarchy** (date-ranged rate > default constant rate > dynamic API rate).
5. Support **daily granularity** for rate validity periods.
6. Provide an **audit trail** for all rate changes.
7. Restrict management to the **Cost Price List Administrator** role.

### Non-Goals

1. Retroactive application — constant rates apply only to queries made after configuration, not to historical query results.
2. Sovereign cloud provider-level rates — this feature operates at the organization (tenant) level only.
3. Replacing the dynamic rate system — the daily API fetch continues as the system-wide fallback.
4. Price list lifecycle / validity periods (COST-575) — that feature is independent.
5. Re-bucketing daily summary data by tenant timezone — summary data remains in UTC dates.

## 4. User Stories

### US-1: Define a date-ranged constant rate

> As a **Cost Price List Administrator**, I want to define a fixed exchange rate for a currency pair over a specific date range, so that cost reports during that period reflect my organization's contractual rate rather than the fluctuating market rate.

**Acceptance criteria:**
- I can specify a source currency, target currency, rate, start date, and end date.
- The rate applies to all cost data with `usage_start` within the defined range.
- The rate takes effect for queries made after I save it (forward-only).

### US-2: Define a default constant rate

> As a **Cost Price List Administrator**, I want to define a default fixed exchange rate for a currency pair with no date range, so that it serves as my organization's standing rate whenever no date-specific rate is configured.

**Acceptance criteria:**
- I can specify a source currency, target currency, and rate — without start/end dates.
- This rate applies to any date not covered by a date-ranged constant rate.
- It remains in effect until I modify or delete it.

### US-3: Fallback to dynamic rate

> As a **cost analyst**, I expect that when no constant rate is defined for a currency pair, the system uses the current dynamic rate from the external API, so that I always see converted costs even without explicit configuration.

**Acceptance criteria:**
- If no default constant rate and no date-ranged rate exist for a pair, the existing dynamic rate behavior applies.
- No configuration is required for fallback behavior.

### US-4: View and manage constant rates

> As a **Cost Price List Administrator**, I want to view, create, update, and delete constant exchange rates, so that I can manage my organization's currency configuration over time.

**Acceptance criteria:**
- I can list all constant rates (date-ranged and defaults) for my organization.
- I can filter by currency pair, date range, or rate type (default vs date-ranged).
- I can update or delete any existing rate.
- All changes are recorded in an audit trail.

### US-5: Audit rate changes

> As a **Cost Administrator**, I want to see a history of who changed constant exchange rates and when, so that I can track financial configuration changes for compliance.

**Acceptance criteria:**
- Every create, update, and delete operation is recorded with timestamp, user, and before/after values.
- Audit records are queryable via API.

## 5. Feature Design

### 5.1. Rate Hierarchy

When converting a cost row from source currency to the customer's display currency, the system evaluates rates in the following order:

```
1. Date-ranged constant rate
   ├── Does a constant rate exist for this (source, target) pair
   │   where usage_start falls within [effective_start, effective_end]?
   │   └── YES → use this rate
   │   └── NO  → continue to step 2
   │
2. Default constant rate
   ├── Does a default constant rate exist for this (source, target) pair
   │   (no date range defined)?
   │   └── YES → use this rate
   │   └── NO  → continue to step 3
   │
3. Dynamic rate (system fallback)
   └── Use the rate from ExchangeRateDictionary (daily API fetch)
```

### 5.2. Currency Pair Model

- Pairs are **directional**: USD→EUR is distinct from EUR→USD.
- Direction is always **source billing currency → customer display currency**.
  - Source: the `currency_code` / `currency` / `raw_currency` column in cost summary data.
  - Target: the customer's configured display currency (from account settings).
- A customer may define up to **2 active currency pairs**.
- Any combination of the 22 supported currencies is valid.

### 5.3. Timezone Handling

Rate validity periods are defined with **daily granularity**. Because Koku's cost summary data is stored using UTC calendar dates (`usage_start` is a `DateField`), the interpretation of "which day" a rate applies to depends on timezone handling. Two approaches are under consideration (see [Section 12](#12-open-decision-timezone-approach)).

Regardless of the approach chosen, the timezone setting is a **new capability** that does not exist in Koku today. All current date handling is UTC-based.

### 5.4. Audit Trail

Every mutation (create, update, delete) to a constant exchange rate record produces an audit entry containing:

| Field | Description |
|-------|-------------|
| `timestamp` | When the change occurred |
| `user` | The user who made the change (username or user UUID) |
| `operation` | `create`, `update`, or `delete` |
| `rate_id` | The ID of the affected constant rate record |
| `previous_values` | Snapshot of the record before the change (null for `create`) |
| `new_values` | Snapshot of the record after the change (null for `delete`) |

Audit records are immutable and retained indefinitely (subject to data retention policy).

## 6. Data Model

### ConstantExchangeRate (new table)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | Primary key |
| `source_currency` | CharField(10) | No | Source currency code (e.g., `USD`) |
| `target_currency` | CharField(10) | No | Target currency code (e.g., `EUR`) |
| `exchange_rate` | DecimalField(24,10) | No | The fixed exchange rate |
| `effective_start` | DateField | Yes | Start of validity period (null = default rate) |
| `effective_end` | DateField | Yes | End of validity period (null = default rate) |
| `created_timestamp` | DateTimeField | No | Record creation time |
| `updated_timestamp` | DateTimeField | No | Last modification time |

**Table name**: `constant_exchange_rate` (tenant schema)

**Constraints:**
- Both `effective_start` and `effective_end` must be null (default rate) or both must be non-null (date-ranged rate).
- `effective_start <= effective_end`.
- For a given `(source_currency, target_currency)` pair, at most one default rate (both dates null).
- For a given `(source_currency, target_currency)` pair, date ranges must not overlap.
- `source_currency != target_currency`.
- Both currencies must be in the supported currencies list.
- `exchange_rate > 0`.
- Maximum of 2 distinct `(source_currency, target_currency)` pairs per tenant.

### ConstantExchangeRateAudit (new table)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | No | Primary key |
| `rate_id` | UUID | No | FK to `ConstantExchangeRate.id` (or the ID of the deleted record) |
| `operation` | CharField(10) | No | `create`, `update`, or `delete` |
| `previous_values` | JSONField | Yes | Snapshot before change (null for `create`) |
| `new_values` | JSONField | Yes | Snapshot after change (null for `delete`) |
| `user` | TextField | No | Username or user identifier |
| `timestamp` | DateTimeField | No | When the change occurred |

**Table name**: `constant_exchange_rate_audit` (tenant schema)

## 7. API Design

### 7.1. Endpoints

All endpoints are under `/api/cost-management/v1/constant-rates/`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/constant-rates/` | List all constant exchange rates for the tenant |
| `POST` | `/constant-rates/` | Create a new constant exchange rate |
| `GET` | `/constant-rates/{id}/` | Retrieve a specific constant exchange rate |
| `PUT` | `/constant-rates/{id}/` | Update a constant exchange rate |
| `DELETE` | `/constant-rates/{id}/` | Delete a constant exchange rate |
| `GET` | `/constant-rates/audit/` | List audit records |

### 7.2. Request and Response Examples

#### Create a date-ranged constant rate

**Request**: `POST /api/cost-management/v1/constant-rates/`

```json
{
  "source_currency": "USD",
  "target_currency": "EUR",
  "exchange_rate": "0.90",
  "effective_start": "2026-01-01",
  "effective_end": "2026-03-31"
}
```

**Response**: `201 Created`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "source_currency": "USD",
  "target_currency": "EUR",
  "exchange_rate": "0.90",
  "effective_start": "2026-01-01",
  "effective_end": "2026-03-31",
  "created_timestamp": "2026-02-13T14:30:00Z",
  "updated_timestamp": "2026-02-13T14:30:00Z"
}
```

#### Create a default constant rate

**Request**: `POST /api/cost-management/v1/constant-rates/`

```json
{
  "source_currency": "USD",
  "target_currency": "GBP",
  "exchange_rate": "0.79"
}
```

**Response**: `201 Created`

```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "source_currency": "USD",
  "target_currency": "GBP",
  "exchange_rate": "0.79",
  "effective_start": null,
  "effective_end": null,
  "created_timestamp": "2026-02-13T14:35:00Z",
  "updated_timestamp": "2026-02-13T14:35:00Z"
}
```

#### List constant rates

**Request**: `GET /api/cost-management/v1/constant-rates/?source_currency=USD`

**Response**: `200 OK`

```json
{
  "meta": {
    "count": 2
  },
  "data": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "source_currency": "USD",
      "target_currency": "EUR",
      "exchange_rate": "0.90",
      "effective_start": "2026-01-01",
      "effective_end": "2026-03-31",
      "created_timestamp": "2026-02-13T14:30:00Z",
      "updated_timestamp": "2026-02-13T14:30:00Z"
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "source_currency": "USD",
      "target_currency": "GBP",
      "exchange_rate": "0.79",
      "effective_start": null,
      "effective_end": null,
      "created_timestamp": "2026-02-13T14:35:00Z",
      "updated_timestamp": "2026-02-13T14:35:00Z"
    }
  ]
}
```

#### List audit records

**Request**: `GET /api/cost-management/v1/constant-rates/audit/?rate_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890`

**Response**: `200 OK`

```json
{
  "meta": {
    "count": 1
  },
  "data": [
    {
      "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "rate_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "operation": "create",
      "previous_values": null,
      "new_values": {
        "source_currency": "USD",
        "target_currency": "EUR",
        "exchange_rate": "0.90",
        "effective_start": "2026-01-01",
        "effective_end": "2026-03-31"
      },
      "user": "cost-admin@example.com",
      "timestamp": "2026-02-13T14:30:00Z"
    }
  ]
}
```

### 7.3. Validation Rules

| Rule | Error Code | Message |
|------|-----------|---------|
| `source_currency` must be in supported currencies | 400 | `"Unsupported source currency: {value}"` |
| `target_currency` must be in supported currencies | 400 | `"Unsupported target currency: {value}"` |
| `source_currency != target_currency` | 400 | `"Source and target currencies must be different"` |
| `exchange_rate > 0` | 400 | `"Exchange rate must be a positive number"` |
| Both dates null or both non-null | 400 | `"Both effective_start and effective_end must be provided, or neither"` |
| `effective_start <= effective_end` | 400 | `"effective_start must be on or before effective_end"` |
| No overlapping date ranges for the same pair | 400 | `"Date range overlaps with existing rate {id} ({start} to {end})"` |
| At most one default rate per pair | 400 | `"A default rate already exists for {source}→{target}"` |
| Maximum 2 distinct currency pairs | 400 | `"Maximum of 2 currency pairs allowed. Current pairs: {pair1}, {pair2}"` |

## 8. Query-Time Behavior

The exchange rate annotation logic in the query handler must be extended to implement the rate hierarchy. Today, the annotation is built from `ExchangeRateDictionary`:

```python
# Current behavior (simplified)
whens = [
    When(currency_code=source, then=Value(rate_to_target))
    for source, rates in exchange_dict.items()
]
annotation = {"exchange_rate": Case(*whens, default=1)}
```

With constant currency, the logic becomes **date-aware**:

```
For each cost row:
  1. Look up (row.currency_code, user.display_currency) in ConstantExchangeRate
     where row.usage_start BETWEEN effective_start AND effective_end
     → If found, use that rate

  2. Look up (row.currency_code, user.display_currency) in ConstantExchangeRate
     where effective_start IS NULL AND effective_end IS NULL
     → If found, use that rate

  3. Fall back to ExchangeRateDictionary[row.currency_code][user.display_currency]
```

This can be implemented as a layered `Case/When` annotation or as a subquery annotation. The implementation approach should be determined during technical design.

### Cache invalidation

Creating, updating, or deleting a constant exchange rate must **invalidate all cached report views** for the tenant, consistent with how currency setting changes are handled today.

## 9. Permissions

| Action | Required Role |
|--------|--------------|
| View constant rates | Cost Price List Administrator, Cost Price List Viewer, Cost Administrator |
| Create / Update / Delete constant rates | Cost Price List Administrator, Cost Administrator |
| View audit trail | Cost Price List Administrator, Cost Administrator |

This aligns with the existing RBAC model where `cost_model` read/write permissions govern cost model management. Constant exchange rates should use the same `cost_model` resource type for permissions, since they are conceptually part of the pricing configuration managed by the same persona.

## 10. Supported Currencies

Any pair drawn from the 22 currently supported currencies is valid:

> AED, AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, INR, JPY, NGN, NOK, NZD, SAR, SEK, SGD, TWD, USD, ZAR

Both the source and target must be in this list. If the supported currencies list is expanded in the future, constant rates will automatically support the new currencies.

## 11. Edge Cases and Constraints

### Overlapping date ranges

Date ranges for the same `(source_currency, target_currency)` pair must not overlap. The API rejects any create or update that would cause an overlap. If a customer needs to change a rate mid-period, they must first shorten or delete the existing range, then create a new one.

### Gap between date ranges

Gaps between date ranges are permitted. Days that fall in a gap use the default constant rate (if defined) or the dynamic rate.

### Forward-only application

Constant rates affect the **exchange rate annotation at query time**. They do not trigger re-summarization of historical data. A customer configuring a rate for a past period will see the new rate reflected in future queries for that period.

### Rate precision

Exchange rates are stored with up to 10 decimal places (`DecimalField(24, 10)`) to accommodate currencies with large numeric differences (e.g., JPY/USD).

### Deletion behavior

Deleting a constant rate immediately removes it from the rate hierarchy. Subsequent queries for the affected date range will fall through to the default constant rate or the dynamic rate. The deletion is recorded in the audit trail.

### Maximum pairs

The limit of 2 currency pairs is enforced at the tenant level, counting distinct `(source_currency, target_currency)` combinations across all rates (both date-ranged and default). For example, if a customer has rates for USD→EUR and USD→GBP, they cannot add a rate for EUR→GBP without first removing all rates for one of the existing pairs.

## 12. Open Decision: Timezone Approach

Rate validity periods use daily granularity. Because cost summary data is bucketed by UTC calendar dates, the system must define how "which day" a rate applies to. Two approaches are under consideration.

### Current state

- Koku has **no per-tenant timezone setting**. All date handling is UTC.
- Summary tables use `DateField` for `usage_start` — a calendar date with no time component.
- Cloud providers (AWS, Azure, GCP, OCP) all provide data in UTC.
- The daily rate fetch runs at 01:00 UTC.
- `KOKU_DEFAULT_TIMEZONE` exists as an env var but is unused anywhere in the codebase.

### Option A: Timezone-aware rate boundaries

**Description**: Introduce a per-tenant timezone setting. When evaluating whether a constant rate's date range covers a given `usage_start`, convert the rate's boundary dates from the tenant's timezone to UTC dates.

**How it works**:
1. Customer sets their timezone (e.g., `America/New_York`, UTC-5) as a new account setting.
2. Customer defines a rate valid from `2026-01-15` to `2026-03-31`.
3. At query time, the system interprets these boundaries in the customer's timezone:
   - `2026-01-15` in `America/New_York` starts at `2026-01-15 05:00 UTC`.
   - Summary rows with `usage_start = 2026-01-14` (UTC) would partially overlap but are excluded (date comparison, not datetime).
   - In practice, the boundary mismatch is at most **1 day** for any timezone.

**Pros**:
- Better customer experience — dates mean what the customer expects.
- Foundation for future timezone-aware features.

**Cons**:
- Adds complexity to the query layer.
- Requires a new timezone setting, validation, and cache invalidation.
- A 1-day boundary mismatch at period edges is inherent because summary data is stored as UTC dates.

**Effort estimate**: ~2-3 weeks for the timezone setting + query integration.

### Option B: UTC-only rate boundaries

**Description**: Rate date ranges are interpreted as UTC dates. No timezone setting is introduced for this feature.

**How it works**:
1. Customer defines a rate valid from `2026-01-15` to `2026-03-31`.
2. At query time, these dates are compared directly against `usage_start` (a UTC date).
3. `usage_start = 2026-01-15` uses the constant rate. `usage_start = 2026-01-14` does not.

**Pros**:
- Simpler implementation — no new timezone infrastructure.
- No boundary ambiguity — dates map 1:1 to stored UTC dates.
- Consistent with how all other date-based features work today.

**Cons**:
- Customers in non-UTC timezones may find that their Q1 rate doesn't perfectly align with their local Q1 start.
- Customers must mentally map their local dates to UTC (or accept a potential 1-day offset).

**Effort estimate**: No additional effort beyond the core feature.

### Recommendation

This decision should be made collaboratively with the team. Key considerations:

- If timezone support is planned for other features, Option A establishes the infrastructure.
- If constant currency is the only timezone-sensitive feature in the near term, Option B avoids premature complexity.
- The practical impact is a **1-day difference at period boundaries**, which may or may not matter depending on customer expectations.

## 13. Out of Scope

| Item | Rationale |
|------|-----------|
| Sovereign cloud provider-level rates | Not related to this feature; rates are per-tenant only |
| Price list lifecycle / validity periods (COST-575) | Independent feature; not a prerequisite |
| Retroactive re-summarization | Rates apply forward-only at query time |
| Replacing the dynamic rate system | Dynamic rates remain as the system fallback |
| Bulk CSV upload of rates | A single rate per date range eliminates the need for bulk entry |
| More than 2 currency pairs | Can be expanded in a future iteration if needed |
| Re-bucketing daily summaries by timezone | High effort, high risk; not required for this feature |

## 14. Dependencies and Risks

### Dependencies

| Dependency | Description |
|-----------|-------------|
| Existing exchange rate infrastructure | The dynamic rate system must continue working as the fallback layer |
| RBAC service | Permission checks for Cost Price List Administrator must be functional |
| Cache invalidation | The existing cache invalidation mechanism (used for currency changes) must be extended |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Query performance degradation from date-aware rate lookups | Medium | Medium | Benchmark the new annotation logic; consider caching constant rates in memory |
| Confusion about forward-only behavior | Medium | Low | Clear API documentation and UI messaging |
| Overlap detection edge cases with concurrent requests | Low | Medium | Use database-level constraints and transactions |
| Timezone boundary mismatches frustrating customers | Medium (Option A) / Low (Option B) | Low | Document the behavior clearly; provide examples |

## 15. Success Criteria

| Criterion | Measurement |
|-----------|------------|
| Customers can define constant rates and see them applied in reports | End-to-end functional test |
| Rate hierarchy is respected (date-ranged > default > dynamic) | Unit and integration tests covering all three tiers |
| No performance regression for customers without constant rates | Benchmark query time with/without constant rates configured |
| Audit trail captures all mutations | Integration test verifying create/update/delete audit records |
| Existing behavior is unchanged for non-configured tenants | Regression test suite passes without constant rates configured |
| Permission enforcement works correctly | RBAC integration tests for all endpoints |

## 16. Appendix: Current Architecture Reference

### Exchange rate flow (today)

```
Celery Beat (01:00 UTC)
  └── get_daily_currency_rates()
      ├── GET https://open.er-api.com/v6/latest/USD
      ├── Update ExchangeRates table (per currency)
      └── Rebuild ExchangeRateDictionary (cross-currency matrix)

Report query
  └── QueryHandler reads ExchangeRateDictionary
  └── Builds Case/When annotation: currency_code → rate_to_display_currency
  └── Annotates queryset with exchange_rate
  └── Provider map: cost * Coalesce(exchange_rate, 1)
```

### Provider currency columns

| Provider | Currency column | Source |
|----------|----------------|--------|
| AWS | `currency_code` | `lineItem/CurrencyCode` in CUR |
| Azure | `currency` | Cost export |
| GCP | `currency` | BigQuery export |
| OCP | `raw_currency` | From infrastructure provider; cost model currency via `source_to_currency_map` |

### Key files

| Component | Path |
|-----------|------|
| Exchange rate models | [`koku/api/currency/models.py`](../../koku/api/currency/models.py) |
| Exchange rate utilities | [`koku/api/currency/utils.py`](../../koku/api/currency/utils.py) |
| Daily fetch task | [`koku/masu/celery/tasks.py`](../../koku/masu/celery/tasks.py) |
| Query-time annotation | [`koku/api/report/queries.py`](../../koku/api/report/queries.py) |
| Cost model models | [`koku/cost_models/models.py`](../../koku/cost_models/models.py) |
| User settings model | [`koku/reporting/user_settings/models.py`](../../koku/reporting/user_settings/models.py) |
| Account settings API | [`koku/api/settings/views.py`](../../koku/api/settings/views.py) |
| RBAC permissions | [`koku/api/common/permissions/`](../../koku/api/common/permissions/) |
| Supported currencies | [`koku/api/currency/currencies.py`](../../koku/api/currency/currencies.py) |

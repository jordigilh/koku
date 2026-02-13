# Test Plan: Cost Breakdown by Rate Description (COST-2105)

**Date**: 2026-02-13
**Version**: 2.0
**Related DD**: [cost-breakdown-sankey.md](./cost-breakdown-sankey.md) v1.5
**Approach**: Test-Driven Development (TDD)
**Target Coverage**: >70% of new/modified code

---

## Table of Contents

- [Overview](#overview)
- [TDD Implementation Phases](#tdd-implementation-phases)
- [Test Data Strategy](#test-data-strategy)
- [Test Suite 1: Cost Model Serializer](#test-suite-1-cost-model-serializer)
- [Test Suite 2: Cost Model DB Accessor](#test-suite-2-cost-model-db-accessor)
- [Test Suite 3: OCP Cost Model Cost Updater](#test-suite-3-ocp-cost-model-cost-updater)
- [Test Suite 4: OCP Report DB Accessor](#test-suite-4-ocp-report-db-accessor)
- [Test Suite 5: API Query Handler](#test-suite-5-api-query-handler)
- [Test Suite 6: API View Integration](#test-suite-6-api-view-integration)
- [Requirements Traceability Matrix](#requirements-traceability-matrix)

---

## Overview

This test plan validates the business outcomes of the COST-2105 feature: breaking down costs into user-meaningful line items from cost model price lists. Each test scenario validates a specific business behavior with deterministic data and concrete expected values.

### Scope Notes

- **VM hourly usage costs** (`vm_cost_per_hour`, `vm_core_cost_per_hour`) are **in scope** using a Postgres proxy approach. `OCP_VM_HOUR` uses 24h/day assumption; `OCP_VM_CORE_HOUR` uses `pod_request_cpu_core_hours` as proxy. See TS3-09, TS4-13, TS4-14. VM **monthly** costs are also in scope.
- **Default tag rates** (`populate_tag_usage_default_costs`) are **in scope**. They write to the same table and must carry `cost_breakdown_source` for Sankey completeness (TS2-08, TS3-08, TS4-12).

### Principles

1. **Business outcome validation** — every test asserts a customer-visible behavior or a data integrity invariant
2. **Deterministic data** — all test rates, descriptions, and expected cost values are explicit; no randomness
3. **No anti-patterns** — no tests for empty/nil/missing unless it validates a specific fallback behavior the user experiences
4. **Follows existing patterns** — `MasuTestCase` for pipeline tests, `IamTestCase` for API tests, `assertAlmostEqual` for cost values, `@patch` for isolation

### Test Type Legend

| Badge | Meaning | Isolation | DB? |
|-------|---------|-----------|-----|
| **Unit (serializer)** | Serializer validation only | Self-contained | No |
| **Unit (mocked)** | Production code under test; all collaborators mocked | `@patch` on accessor/DB methods | No |
| **Integration (DB)** | Real SQL against test Postgres schema | `MasuTestCase` fixtures + real `OCPReportDBAccessor` | Yes |
| **Integration (accessor+DB)** | Real accessor reading from test DB | `MasuTestCase` fixtures + real `CostModelDBAccessor` | Yes |
| **Integration (API)** | Query handler with real DB backend | `IamTestCase` fixtures + real query pipeline | Yes |
| **Integration (HTTP)** | Full Django request/response cycle | `APIClient` + `IamTestCase` | Yes |

---

## TDD Implementation Phases

Tests are implemented bottom-up so that each phase's production code is validated before the next layer depends on it. Within each phase, follow the Red → Green → Refactor cycle.

### Phase A: Foundation (Schema + Serializer)

**Unlocks**: `cost_breakdown_source` column, mandatory description validation

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | Migration | `ALTER TABLE reporting_ocpusagelineitem_daily_summary ADD COLUMN cost_breakdown_source TEXT` |
| 2 | TS1-01 | `RateSerializer.description` → `required=True, allow_blank=False` |
| 3 | TS1-02 | (same — validates rejection path) |
| 4 | TS1-03 | (same — validates blank rejection) |
| 5 | TS1-04 | `CostModelSerializer` propagation of description through full save |

### Phase B: Data Access Layer (Cost Model DB Accessor)

**Unlocks**: `itemized_rates` property, tag description propagation
**Depends on**: Phase A (cost model must store descriptions)

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | TS2-01 | `CostModelDBAccessor.itemized_rates` property |
| 2 | TS2-02 | (validates duplicate metric preservation — same property) |
| 3 | TS2-03 | Metric-name fallback in `itemized_rates` |
| 4 | TS2-04 | (backward compat — no production code, just verification) |
| 5 | TS2-05 | `tag_based_price_list` propagates `description` field |
| 6 | TS2-06 | 3-tier fallback chain in `tag_based_price_list` |
| 7 | TS2-07 | `tag_infrastructure_rates` returns `{value, description}` dict |
| 8 | TS2-08 | `tag_default_infrastructure_rates` includes `description` |

### Phase C: SQL Execution Layer (OCP Report DB Accessor — Core)

**Unlocks**: SQL templates with `cost_breakdown_source`, `delete_usage_costs` method
**Depends on**: Phase A (migration applied)

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | TS4-03 | `OCPReportDBAccessor.delete_usage_costs()` method |
| 2 | TS4-01 | `usage_costs.sql` + `populate_usage_costs` accept `cost_breakdown_source` |
| 3 | TS4-02 | (validates distinct rows per description — same SQL) |
| 4 | TS4-07 | (backward compat — no new code, just verification) |
| 5 | TS4-15 | (edge case: rate=0 — same SQL, validates boundary) |
| 6 | TS4-04 | `monthly_cost_*.sql` + `populate_monthly_cost_sql` accept `cost_breakdown_source` |
| 7 | TS4-05 | `infrastructure_tag_rates.sql` + `populate_tag_usage_costs` accept `cost_breakdown_source` |
| 8 | TS4-06 | (markup preservation — no new code, just verification) |

### Phase D: Orchestration Layer (Cost Updater)

**Unlocks**: Per-rate execution loop, description resolution and passing
**Depends on**: Phase B (`itemized_rates`), Phase C (DB methods accept `cost_breakdown_source`)

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | TS3-02 | `_update_usage_costs` calls `delete_usage_costs` before loop |
| 2 | TS3-01 | `_update_usage_costs` per-rate loop with `cost_breakdown_source` |
| 3 | TS3-06 | (single-rate edge — same loop) |
| 4 | TS3-03 | Filter `itemized_rates` against `COST_MODEL_USAGE_RATES` |
| 5 | TS3-10 | (empty rates edge — same loop, validates zero-iteration) |
| 6 | TS3-04 | `_update_monthly_cost` resolves description from `itemized_rates` |
| 7 | TS3-07 | (dual cost_type resolution — same method) |
| 8 | TS3-05 | `_update_tag_usage_costs` extracts description from enriched dict |
| 9 | TS3-08 | `_update_tag_usage_default_costs` extracts rate-level description |
| 10 | TS3-09 | VM rate routing to `populate_vm_usage_costs_postgres` |

### Phase E: Advanced DB Operations

**Unlocks**: Distributed cost qualifiers, default tag rates, VM proxy SQL
**Depends on**: Phase C (core DB accessor works)

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | TS4-08 | `distribute_platform_cost.sql` carries + qualifies `cost_breakdown_source` |
| 2 | TS4-09 | (multiple sources — same SQL, validates GROUP BY) |
| 3 | TS4-10 | `distribute_unattributed_storage_cost.sql` hardcoded label |
| 4 | TS4-11 | `distribute_unattributed_network_cost.sql` hardcoded label |
| 5 | TS4-12 | `default_infrastructure_tag_rates.sql` + `populate_tag_usage_default_costs` |
| 6 | TS4-13 | `usage_costs_virtual_machine.sql` + `populate_vm_usage_costs_postgres` (OCP_VM_HOUR) |
| 7 | TS4-14 | `usage_costs_vm_core.sql` (OCP_VM_CORE_HOUR) |

### Phase F: API Layer

**Unlocks**: `cost_breakdown` in API response, synthetic Markup
**Depends on**: All prior phases

| Order | Scenario | Production Code to Write |
|-------|----------|--------------------------|
| 1 | TS5-01 | `cost_breakdown` annotation in `provider_map.py` |
| 2 | TS5-02 | (structure validation — same annotation) |
| 3 | TS5-03 | (source matching — end-to-end verification) |
| 4 | TS5-04 | Synthetic "Markup" entry in query handler |
| 5 | TS5-05 | (sum consistency — same annotation) |
| 6 | TS5-06 | (backward compat — no new code) |
| 7 | TS5-12 | (duplicate metric separation — same annotation) |
| 8 | TS5-07 | Total-section aggregation across projects |
| 9 | TS5-08 | (distributed [platform] entries — end-to-end) |
| 10 | TS5-09 | (distributed [worker] entries — end-to-end) |
| 11 | TS5-10 | `cost_breakdown` annotation for `costs` report type |
| 12 | TS5-11 | `cost_breakdown` annotation for `costs_by_node` report type |
| 13 | TS5-13 | (no cost model edge — validates empty list) |
| 14 | TS6-01 | (HTTP integration — no new code beyond TS5) |
| 15 | TS6-02 | (per-project HTTP — same) |
| 16 | TS6-03 | (per-node HTTP — same) |
| 17 | TS6-04 | (backward compat HTTP — same) |
| 18 | TS6-05 | (Markup consistency HTTP — same) |
| 19 | TS6-06 | (platform sum consistency HTTP — same) |

---

## Test Data Strategy

All test suites share a common **multi-rate cost model** that exercises the full feature surface. This cost model is constructed in test setup, not loaded from fixtures, to keep test scenarios self-contained and traceable.

### Reference Cost Model: "Multi-Rate OCP"

```python
MULTI_RATE_COST_MODEL_RATES = [
    {
        "metric": {"name": "cpu_core_usage_per_hour"},
        "cost_type": "Infrastructure",
        "description": "JBoss subscription",
        "tiered_rates": [{"value": 5.0, "unit": "USD"}],
    },
    {
        "metric": {"name": "memory_gb_usage_per_hour"},
        "cost_type": "Infrastructure",
        "description": "Guest OS subscription (RHEL)",
        "tiered_rates": [{"value": 3.0, "unit": "USD"}],
    },
    {
        "metric": {"name": "cpu_core_usage_per_hour"},
        "cost_type": "Supplementary",
        "description": "Quota charge",
        "tiered_rates": [{"value": 2.0, "unit": "USD"}],
    },
    {
        "metric": {"name": "node_cost_per_month"},
        "cost_type": "Infrastructure",
        "description": "Node monthly license",
        "tiered_rates": [{"value": 100.0, "unit": "USD"}],
    },
    {
        "metric": {"name": "cluster_cost_per_month"},
        "cost_type": "Supplementary",
        "description": "Cluster support fee",
        "tiered_rates": [{"value": 250.0, "unit": "USD"}],
    },
]
```

### Reference Tag Rate

```python
MULTI_RATE_TAG_RATE = {
    "metric": {"name": "cpu_core_usage_per_hour"},
    "cost_type": "Infrastructure",
    "description": "Environment tag rate",
    "tag_rates": {
        "tag_key": "environment",
        "tag_values": [
            {
                "tag_value": "production",
                "value": 10.0,
                "unit": "USD",
                "default": False,
                "description": "Production environment",
            },
            {
                "tag_value": "staging",
                "value": 4.0,
                "unit": "USD",
                "default": False,
                "description": "",  # blank — falls back to rate-level description
            },
        ],
    },
}
```

### Standard Test Fixture Values

All scenarios reference these deterministic fixture values. Using fixed values ensures every expected output is pre-computable.

```python
# OCP usage fixture (created via baker.make or MasuTestCase fixtures)
FIXTURE_CPU_CORE_HOURS = Decimal("2.0")
FIXTURE_MEMORY_GB_HOURS = Decimal("4.0")
FIXTURE_POD_REQUEST_CPU_CORE_HOURS = Decimal("48.0")  # VM tests
FIXTURE_DAYS_IN_MONTH = 31
FIXTURE_MARKUP_PERCENT = Decimal("0.10")  # 10%
FIXTURE_START_DATE = "2026-01-01"
FIXTURE_END_DATE = "2026-01-31"
FIXTURE_NAMESPACE = "test-project"
FIXTURE_PLATFORM_NAMESPACE = "openshift-kube-apiserver"
FIXTURE_VM_POD_LABELS = {"vm_kubevirt_io_name": "test-vm-1"}
FIXTURE_TAG_POD_LABELS = {"environment": "production"}
```

### Derived Expected Values

| Calculation | Formula | Expected |
|-------------|---------|----------|
| CPU Infra cost | `2.0 × $5.0` | `Decimal("10.00")` |
| Memory Infra cost | `4.0 × $3.0` | `Decimal("12.00")` |
| CPU Supp cost | `2.0 × $2.0` | `Decimal("4.00")` |
| Node monthly daily | `$100.0 / 31` | `Decimal("3.225806")` |
| Cluster monthly daily | `$250.0 / 31` | `Decimal("8.064516")` |
| Markup on CPU Infra | `10.00 × 0.10` | `Decimal("1.00")` |
| Tag prod CPU cost | `2.0 × $10.0` | `Decimal("20.00")` |
| Tag staging CPU cost | `2.0 × $4.0` | `Decimal("8.00")` |
| VM hourly daily | `24 × $0.50` | `Decimal("12.00")` |
| VM core hourly | `48.0 × $0.10` | `Decimal("4.80")` |
| Default tag cost | `2.0 × $5.0` | `Decimal("10.00")` |

### Reference Tag Rate (No Descriptions)

```python
LEGACY_TAG_RATE = {
    "metric": {"name": "memory_gb_usage_per_hour"},
    "cost_type": "Supplementary",
    "tag_rates": {
        "tag_key": "tier",
        "tag_values": [
            {
                "tag_value": "gold",
                "value": 8.0,
                "unit": "USD",
                "default": False,
                "description": "",
            },
        ],
    },
    # No top-level "description" — falls back to metric name
}
```

---

## Test Suite 1: Cost Model Serializer

**File**: [`koku/cost_models/test/test_serializers.py`](../../koku/cost_models/test/test_serializers.py)
**Base class**: `IamTestCase`
**Requirement coverage**: R1, AD-5

### TS1-01: Rate with description passes validation

**Type**: Unit (serializer) | **TDD Phase**: A | **Depends on**: None

**Business outcome**: A user creating a new cost model rate with a description succeeds.

**Steps**:
1. **Arrange**: Build rate data dict: `{"metric": {"name": "cpu_core_usage_per_hour"}, "cost_type": "Infrastructure", "description": "JBoss subscription", "tiered_rates": [{"value": 5.0, "unit": "USD"}]}`
2. **Act**: `serializer = RateSerializer(data=rate_data)` → call `serializer.is_valid()`
3. **Assert**: `assertTrue(serializer.is_valid())`
4. **Assert**: `assertEqual(serializer.validated_data["description"], "JBoss subscription")`

**Exit criteria**:
- Serializer validation passes
- The `description` field value is preserved exactly as submitted in `validated_data`

### TS1-02: Rate without description fails validation

**Type**: Unit (serializer) | **TDD Phase**: A | **Depends on**: None

**Business outcome**: A user creating a new cost model rate without a description is rejected with a clear error.

**Steps**:
1. **Arrange**: Build rate data dict identical to TS1-01 but omit the `description` key entirely
2. **Act**: `serializer = RateSerializer(data=rate_data)` → call `serializer.is_valid()`
3. **Assert**: `assertFalse(serializer.is_valid())`
4. **Assert**: `assertIn("description", serializer.errors)`

**Exit criteria**:
- Serializer validation fails
- Error response explicitly references the `description` field

### TS1-03: Rate with blank description fails validation

**Type**: Unit (serializer) | **TDD Phase**: A | **Depends on**: None

**Business outcome**: A user submitting an empty string description is rejected (description must be meaningful).

**Steps**:
1. **Arrange**: Build rate data dict identical to TS1-01 but set `"description": ""`
2. **Act**: `serializer = RateSerializer(data=rate_data)` → call `serializer.is_valid()`
3. **Assert**: `assertFalse(serializer.is_valid())`
4. **Assert**: `assertIn("description", serializer.errors)`

**Exit criteria**:
- Serializer validation fails with `allow_blank=False` enforcement
- Error response explicitly references the `description` field

### TS1-04: Full cost model with multiple described rates saves successfully

**Type**: Unit (serializer) | **TDD Phase**: A | **Depends on**: TS1-01

**Business outcome**: A cost model with multiple rates, each having a unique description, is created and persisted.

**Steps**:
1. **Arrange**: Build full cost model payload using `MULTI_RATE_COST_MODEL_RATES` (5 rates) with a valid OCP provider UUID and `"source_type": "OCP"`
2. **Act**: `serializer = CostModelSerializer(data=payload, context=self.request_context)` → call `serializer.is_valid()` → `instance = serializer.save()`
3. **Assert**: `assertIsNotNone(instance.uuid)`
4. **Assert**: `assertEqual(len(instance.rates), 5)`
5. **Assert**: For each rate `i` in `instance.rates`: `assertEqual(instance.rates[i]["description"], MULTI_RATE_COST_MODEL_RATES[i]["description"])`

**Exit criteria**:
- `CostModel` instance is persisted in the database with a valid UUID
- `instance.rates` JSON contains exactly 5 rate entries
- Every rate entry's `description` matches the corresponding input value verbatim

---

## Test Suite 2: Cost Model DB Accessor

**File**: [`koku/masu/test/database/test_cost_model_db_accessor.py`](../../koku/masu/test/database/test_cost_model_db_accessor.py)
**Base class**: `MasuTestCase`
**Requirement coverage**: R2, R4, R6, R10, AD-1

### TS2-01: `itemized_rates` returns individual rates with descriptions

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: Phase A migration

**Business outcome**: The pipeline receives each rate as a separate entry with its description preserved, enabling per-rate cost tracking.

**Steps**:
1. **Arrange**: Create `CostModel` with `MULTI_RATE_COST_MODEL_RATES` (5 rates) in the test schema via `baker.make` or `CostModelDBAccessor`
2. **Arrange**: Instantiate `CostModelDBAccessor(self.schema, self.provider_uuid)`
3. **Act**: `result = accessor.itemized_rates`
4. **Assert**: `assertEqual(len(result), 5)`
5. **Assert**: `assertEqual(result[0], {"metric": "cpu_core_usage_per_hour", "cost_type": "Infrastructure", "value": 5.0, "description": "JBoss subscription"})`
6. **Assert**: `assertEqual(result[2], {"metric": "cpu_core_usage_per_hour", "cost_type": "Supplementary", "value": 2.0, "description": "Quota charge"})`

**Exit criteria**:
- Exactly 5 rate dicts returned, each with keys: `metric`, `cost_type`, `value`, `description`
- All values and descriptions match `MULTI_RATE_COST_MODEL_RATES` in order

### TS2-02: `itemized_rates` preserves duplicate metrics as separate entries

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: TS2-01

**Business outcome**: When a customer defines two CPU rates (Infrastructure + Supplementary) with different descriptions, both appear individually — they are not summed (R10).

**Steps**:
1. **Arrange**: Same cost model as TS2-01 (has two `cpu_core_usage_per_hour` entries)
2. **Act**: `result = accessor.itemized_rates`
3. **Act**: `cpu_rates = [r for r in result if r["metric"] == "cpu_core_usage_per_hour"]`
4. **Assert**: `assertEqual(len(cpu_rates), 2)`
5. **Assert**: Entry with `cost_type="Infrastructure"` has `value=5.0`, `description="JBoss subscription"`
6. **Assert**: Entry with `cost_type="Supplementary"` has `value=2.0`, `description="Quota charge"`

**Exit criteria**:
- Both CPU rates are returned as distinct list entries (not merged/summed to 7.0)
- Each entry has the correct `cost_type` and `description`

### TS2-03: `itemized_rates` falls back to metric name when description is missing

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: TS2-01

**Business outcome**: A legacy cost model without descriptions still works; the metric name serves as the identifier the customer sees in the Sankey.

**Steps**:
1. **Arrange**: Create `CostModel` with one rate: `{"metric": {"name": "cpu_core_usage_per_hour"}, "cost_type": "Infrastructure", "tiered_rates": [{"value": 5.0}]}` — no `description` key
2. **Arrange**: Instantiate `CostModelDBAccessor`
3. **Act**: `result = accessor.itemized_rates`
4. **Assert**: `assertEqual(len(result), 1)`
5. **Assert**: `assertEqual(result[0]["description"], "cpu_core_usage_per_hour")`

**Exit criteria**:
- The `description` field is populated with the metric name as fallback
- No exception is raised due to the missing key

### TS2-04: `price_list` remains unchanged (backward compatibility)

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: Phase A migration

**Business outcome**: Existing code paths that use `price_list` continue to work. The `price_list` still sums duplicate metrics.

**Steps**:
1. **Arrange**: Create `CostModel` with `MULTI_RATE_COST_MODEL_RATES`
2. **Act**: `pl = accessor.price_list`; `infra = accessor.infrastructure_rates`; `supp = accessor.supplementary_rates`
3. **Assert**: `assertIsInstance(pl, dict)` — keyed by metric name
4. **Assert**: `assertEqual(infra["cpu_core_usage_per_hour"], 5.0)` — single value, not split
5. **Assert**: `assertNotIn("description", pl.get("cpu_core_usage_per_hour", {}))` — no new keys

**Exit criteria**:
- `price_list` dict structure identical to pre-feature behavior
- No new keys appear in the returned dicts

### TS2-05: `tag_based_price_list` propagates tag-value description

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: Phase A migration

**Business outcome**: Tag rates carry the most granular description available so the Sankey shows meaningful tag-rate labels.

**Steps**:
1. **Arrange**: Create `CostModel` with `MULTI_RATE_TAG_RATE` (production: "Production environment", staging: blank)
2. **Act**: `tag_pl = accessor.tag_based_price_list`
3. **Act**: Navigate to `tag_pl["Infrastructure"]["cpu_core_usage_per_hour"]["environment"]`
4. **Assert**: `assertEqual(tag_pl[...]["production"]["description"], "Production environment")` — tier 1: tag-value description
5. **Assert**: `assertEqual(tag_pl[...]["staging"]["description"], "Environment tag rate")` — tier 2: rate-level fallback

**Exit criteria**:
- "production" uses its own description (tier 1), "staging" falls back to rate-level (tier 2)
- Numeric `value` fields unchanged (10.0 and 4.0)

### TS2-06: `tag_based_price_list` falls back to metric name when both descriptions are missing

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: TS2-05

**Business outcome**: Legacy tag rates without any descriptions still produce a usable identifier.

**Steps**:
1. **Arrange**: Create `CostModel` with `LEGACY_TAG_RATE` (no top-level description, blank tag-value descriptions)
2. **Act**: `tag_pl = accessor.tag_based_price_list`
3. **Act**: Navigate to the "gold" tag value entry
4. **Assert**: `assertEqual(entry["description"], "memory_gb_usage_per_hour")` — tier 3: metric name fallback

**Exit criteria**:
- Description resolves to metric name as last-resort fallback
- No exception raised; numeric `value` (8.0) preserved

### TS2-07: `tag_infrastructure_rates` carries description alongside value

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: TS2-05

**Business outcome**: The tag rate dict structure now provides both the numeric value and description for downstream use.

**Steps**:
1. **Arrange**: Create `CostModel` with `MULTI_RATE_TAG_RATE`
2. **Act**: `tag_rates = accessor.tag_infrastructure_rates`
3. **Act**: Navigate to `tag_rates["environment"]["production"]`
4. **Assert**: `assertEqual(entry["value"], 10.0)`
5. **Assert**: `assertEqual(entry["description"], "Production environment")`

**Exit criteria**:
- Each tag value entry contains both `value` (numeric) and `description` (string)
- Downstream callers can access both fields from the same dict

### TS2-08: `tag_default_infrastructure_rates` carries description for default tag rates

**Type**: Integration (accessor+DB) | **TDD Phase**: B | **Depends on**: TS2-05

**Business outcome**: Default tag rates carry the rate-level description so the Sankey shows meaningful labels for the "catch-all" rate.

**Steps**:
1. **Arrange**: Create `CostModel` with `MULTI_RATE_TAG_RATE` (rate-level description: "Environment tag rate")
2. **Act**: `defaults = accessor.tag_default_infrastructure_rates`
3. **Act**: Navigate to `defaults["environment"]`
4. **Assert**: `assertEqual(entry["description"], "Environment tag rate")`

**Exit criteria**:
- Returned dict includes `description` alongside `default_value` and `defined_keys`
- Description is the rate-level description (defaults don't match a specific tag value)
- If no rate-level description exists, falls back to metric name

---

## Test Suite 3: OCP Cost Model Cost Updater

**File**: [`koku/masu/test/processor/ocp/test_ocp_cost_model_cost_updater.py`](../../koku/masu/test/processor/ocp/test_ocp_cost_model_cost_updater.py)
**Base class**: `MasuTestCase`
**Requirement coverage**: R2, R4, R5, R6, R7, R10, AD-1

### TS3-01: `_update_usage_costs` calls `populate_usage_costs` once per individual rate

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS2-01, TS4-01

**Business outcome**: Each rate in the cost model produces a separate SQL execution, allowing per-rate cost tracking in the database.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")` — mock `itemized_rates` property
- `@patch.object(OCPReportDBAccessor, "populate_usage_costs")` — capture calls
- `@patch.object(OCPReportDBAccessor, "delete_usage_costs")` — no-op

**Steps**:
1. **Arrange**: Configure mock `CostModelDBAccessor.itemized_rates` to return 3 usage rates: CPU Infra ($5, "JBoss subscription"), Memory Infra ($3, "Guest OS subscription (RHEL)"), CPU Supp ($2, "Quota charge")
2. **Arrange**: Instantiate `OCPCostModelCostUpdater(self.schema, self.provider)` (uses mocked accessor)
3. **Act**: Call `updater._update_usage_costs(start_date, end_date, cluster_id, ...)`
4. **Assert**: `assertEqual(mock_populate.call_count, 3)`
5. **Assert**: Call 1 kwargs: `cost_type="Infrastructure"`, rates dict has only `cpu_core_usage_per_hour=5.0`, `cost_breakdown_source="JBoss subscription"`
6. **Assert**: Call 2 kwargs: `cost_type="Infrastructure"`, rates dict has only `memory_gb_usage_per_hour=3.0`, `cost_breakdown_source="Guest OS subscription (RHEL)"`
7. **Assert**: Call 3 kwargs: `cost_type="Supplementary"`, rates dict has only `cpu_core_usage_per_hour=2.0`, `cost_breakdown_source="Quota charge"`

**Exit criteria**:
- 3 calls (1:1 with usage rates); each passes a single-metric rates dict with correct `cost_breakdown_source`

### TS3-02: `_update_usage_costs` bulk-deletes before per-rate inserts

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS4-03

**Business outcome**: Stale cost rows from previous rate configurations are cleaned up before new rates are inserted, preventing data corruption.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")`
- `@patch.object(OCPReportDBAccessor, "populate_usage_costs")`
- `@patch.object(OCPReportDBAccessor, "delete_usage_costs")`

**Steps**:
1. **Arrange**: Configure mock with 2 Infrastructure usage rates
2. **Act**: Call `updater._update_usage_costs(...)`
3. **Assert**: Use `mock.call_args_list` to reconstruct the full call sequence across both mocks
4. **Assert**: `delete_usage_costs("Infrastructure")` appears before any `populate_usage_costs` call
5. **Assert**: `delete_usage_costs("Supplementary")` appears before any `populate_usage_costs` call
6. **Assert**: `assertEqual(mock_delete.call_count, 2)` — one per cost_type

**Exit criteria**:
- Sequence: delete(Infra) → delete(Supp) → populate(rate1) → populate(rate2)
- Both cost types deleted even if only one has rates (cleans stale data from removed rates)

### TS3-03: `_update_usage_costs` filters to usage-rate metrics only

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS3-01

**Business outcome**: Monthly cost metrics are not processed by the usage cost path, preventing double-counting.

**Mocks**: Same as TS3-01

**Steps**:
1. **Arrange**: Configure mock `itemized_rates` with all 5 rates from `MULTI_RATE_COST_MODEL_RATES` (3 usage + 2 monthly)
2. **Act**: Call `updater._update_usage_costs(...)`
3. **Assert**: `assertEqual(mock_populate.call_count, 3)` — only usage metrics
4. **Assert**: No call's rates dict contains `node_cost_per_month` or `cluster_cost_per_month`

**Exit criteria**:
- Only metrics in `COST_MODEL_USAGE_RATES` are processed; monthly metrics silently excluded

### TS3-04: `_update_monthly_cost` passes description to `populate_monthly_cost_sql`

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS2-01, TS4-04

**Business outcome**: Monthly fixed costs carry the rate description through to the database for Sankey display.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")` — mock `infrastructure_rates` and `itemized_rates`
- `@patch.object(OCPReportDBAccessor, "populate_monthly_cost_sql")` — capture calls

**Steps**:
1. **Arrange**: Mock `infrastructure_rates = {"node_cost_per_month": 100.0}`
2. **Arrange**: Mock `itemized_rates` includes `{"metric": "node_cost_per_month", "cost_type": "Infrastructure", "value": 100.0, "description": "Node monthly license"}`
3. **Act**: Call `updater._update_monthly_cost(...)`
4. **Assert**: `mock_populate_monthly.assert_called_with(...)` includes `cost_breakdown_source="Node monthly license"`

**Exit criteria**:
- Description resolved by matching both `metric` and `cost_type` from `itemized_rates`

### TS3-05: `_update_tag_usage_costs` passes tag-value description to `populate_tag_usage_costs`

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS2-07, TS4-05

**Business outcome**: Tag-based costs carry the tag-value description into the database so the Sankey shows "Production environment" rather than abstract tag keys.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")` — mock `tag_infrastructure_rates`
- `@patch.object(OCPReportDBAccessor, "populate_tag_usage_costs")`

**Steps**:
1. **Arrange**: Mock `tag_infrastructure_rates = {"environment": {"production": {"value": 10.0, "description": "Production environment"}}}`
2. **Act**: Call `updater._update_tag_usage_costs(...)`
3. **Assert**: `populate_tag_usage_costs` called with `cost_breakdown_source="Production environment"`

**Exit criteria**:
- Receives tag-value description (not rate-level), with all other existing parameters unchanged

### TS3-06: `_update_usage_costs` with single rate produces exactly one `populate_usage_costs` call

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS3-01

**Business outcome**: A simple cost model with a single rate works correctly without extra SQL executions.

**Mocks**: Same as TS3-01

**Steps**:
1. **Arrange**: Mock `itemized_rates` with 1 rate: CPU Infrastructure "JBoss subscription" $5
2. **Act**: Call `updater._update_usage_costs(...)`
3. **Assert**: `assertEqual(mock_populate.call_count, 1)`
4. **Assert**: `cost_breakdown_source="JBoss subscription"`
5. **Assert**: `assertEqual(mock_delete.call_count, 2)` — delete still called for both cost types

**Exit criteria**:
- Exactly 1 populate call (no off-by-one); delete still called for cleanup

### TS3-07: `_update_monthly_cost` resolves description from `itemized_rates` matching metric and cost_type

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS3-04

**Business outcome**: The correct description is paired with the correct monthly rate, even when multiple rates share a metric name.

**Mocks**: Same as TS3-04

**Steps**:
1. **Arrange**: Mock `itemized_rates` with two `node_cost_per_month` entries: Infrastructure "Node monthly license" ($100), Supplementary "Node supplementary charge" ($50)
2. **Arrange**: Mock `infrastructure_rates = {"node_cost_per_month": 100.0}`, `supplementary_rates = {"node_cost_per_month": 50.0}`
3. **Act**: Call `updater._update_monthly_cost(...)`
4. **Assert**: Infrastructure call has `cost_breakdown_source="Node monthly license"`
5. **Assert**: Supplementary call has `cost_breakdown_source="Node supplementary charge"`

**Exit criteria**:
- Each call receives the description matching its cost_type; no cross-contamination

### TS3-08: `_update_tag_usage_default_costs` passes rate-level description to `populate_tag_usage_default_costs`

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS2-08, TS4-12

**Business outcome**: Default tag-based costs carry the rate-level description for catch-all tag rates.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")` — mock `tag_default_infrastructure_rates`
- `@patch.object(OCPReportDBAccessor, "populate_tag_usage_default_costs")`

**Steps**:
1. **Arrange**: Mock `tag_default_infrastructure_rates = {"environment": {"default_value": 5.0, "defined_keys": ["production", "staging"], "description": "Environment tag rate"}}`
2. **Act**: Call `updater._update_tag_usage_default_costs(...)`
3. **Assert**: `populate_tag_usage_default_costs` called with `cost_breakdown_source="Environment tag rate"`

**Exit criteria**:
- Receives rate-level description (not tag-value); all other parameters unchanged

### TS3-09: `_update_usage_costs` calls Postgres VM hourly proxy for VM rates with description

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS4-13, TS4-14

**Business outcome**: VM hourly costs are applied via the Postgres proxy, not Trino, with rate descriptions.

**Mocks**:
- `@patch("masu.processor.ocp.ocp_cost_model_cost_updater.CostModelDBAccessor")`
- `@patch.object(OCPReportDBAccessor, "populate_vm_usage_costs_postgres")`
- `@patch.object(OCPReportDBAccessor, "populate_usage_costs")`

**Steps**:
1. **Arrange**: Mock `itemized_rates` with 2 VM rates: `OCP_VM_HOUR` Infra $0.50 "VM hourly subscription", `OCP_VM_CORE_HOUR` Infra $0.10 "VM core hourly cost"
2. **Act**: Call `updater._update_usage_costs(...)`
3. **Assert**: `mock_vm_postgres.call_count == 2`
4. **Assert**: Call 1: `metric="OCP_VM_HOUR"`, `rate=0.50`, `cost_breakdown_source="VM hourly subscription"`
5. **Assert**: Call 2: `metric="OCP_VM_CORE_HOUR"`, `rate=0.10`, `cost_breakdown_source="VM core hourly cost"`
6. **Assert**: `mock_populate_usage.call_count == 0` — VM rates not sent to standard populate

**Exit criteria**:
- VM metrics routed to `populate_vm_usage_costs_postgres`, not Trino or standard populate

### TS3-10: `_update_usage_costs` with empty `itemized_rates` deletes but does not populate (edge case)

**Type**: Unit (mocked) | **TDD Phase**: D | **Depends on**: TS3-02

**Business outcome**: When all rates are removed from a cost model, stale cost rows are cleaned up without inserting any new rows.

**Mocks**: Same as TS3-01

**Steps**:
1. **Arrange**: Mock `itemized_rates` returning `[]` (empty list)
2. **Act**: Call `updater._update_usage_costs(...)`
3. **Assert**: `assertEqual(mock_delete.call_count, 2)` — both cost types still deleted
4. **Assert**: `assertEqual(mock_populate.call_count, 0)` — no inserts

**Exit criteria**:
- Delete is called (cleans up previous data); populate is never called
- No errors raised on empty list iteration

---

## Test Suite 4: OCP Report DB Accessor

**File**: [`koku/masu/test/database/test_ocp_report_db_accessor.py`](../../koku/masu/test/database/test_ocp_report_db_accessor.py)
**Base class**: `MasuTestCase`
**Requirement coverage**: R2, R4, R5, R6, R7, R8, R9

### TS4-01: `populate_usage_costs` writes `cost_breakdown_source` to daily summary rows

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: Phase A migration

**Business outcome**: After applying a usage rate, every inserted cost row carries the rate description, making it queryable for the Sankey breakdown.

**Steps**:
1. **Arrange**: Verify `MasuTestCase` fixtures provide OCP usage data with `pod_usage_cpu_core_hours = 2.0`
2. **Arrange**: Build rates dict `{"cpu_core_usage_per_hour": 5.0, "memory_gb_usage_per_hour": 0, "storage_gb_usage_per_month": 0, "node_cost_per_month": 0, "cluster_cost_per_month": 0}`
3. **Act**: Call `self.accessor.populate_usage_costs(cost_type="Infrastructure", infrastructure_rates=rates, cost_breakdown_source="JBoss subscription", start_date=start, end_date=end, cluster_id=cluster, report_period_id=rp_id)`
4. **Assert**: `qs = OCPUsageLineItemDailySummary.objects.filter(cost_model_rate_type="Infrastructure", cost_breakdown_source="JBoss subscription")`
5. **Assert**: `assertTrue(qs.exists())`
6. **Assert**: `assertAlmostEqual(qs.first().cost_model_cpu_cost, Decimal("10.00"), places=2)` — (2.0 hours × $5.0)

| Expected | Value |
|----------|-------|
| `cost_breakdown_source` | `"JBoss subscription"` |
| `cost_model_cpu_cost` | `Decimal("10.00")` |
| `cost_model_rate_type` | `"Infrastructure"` |

**Exit criteria**:
- At least 1 row with `cost_breakdown_source="JBoss subscription"` and correct cost value

### TS4-02: Two separate `populate_usage_costs` calls produce distinct rows per description

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: TS4-01

**Business outcome**: When a customer has two CPU rates with different descriptions, both appear as separate rows in the database (not merged).

**Steps**:
1. **Arrange**: Same fixture data as TS4-01
2. **Act**: Call `populate_usage_costs(cost_type="Infrastructure", rates={cpu: 5.0, others: 0}, cost_breakdown_source="JBoss subscription", ...)`
3. **Act**: Call `populate_usage_costs(cost_type="Infrastructure", rates={cpu: 3.0, others: 0}, cost_breakdown_source="RHEL license", ...)`
4. **Assert**: `qs_jboss = ...filter(cost_breakdown_source="JBoss subscription")` — exists, `cost_model_cpu_cost ≈ Decimal("10.00")`
5. **Assert**: `qs_rhel = ...filter(cost_breakdown_source="RHEL license")` — exists, `cost_model_cpu_cost ≈ Decimal("6.00")` (2.0 × $3.0)
6. **Assert**: Both sets of rows are distinct (not summed into one)

**Exit criteria**:
- Row count for Infrastructure = 2× the pre-feature count (one set per rate)
- Second INSERT did not overwrite the first

### TS4-03: `delete_usage_costs` removes all rows for a cost_type in date range

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: Phase A migration

**Business outcome**: Before re-applying rates, stale cost rows are cleanly removed regardless of their `cost_breakdown_source` value.

**Steps**:
1. **Arrange**: Call `populate_usage_costs` twice to create rows with two different `cost_breakdown_source` values ("JBoss", "RHEL"), both `cost_type="Infrastructure"`
2. **Arrange**: Also create Supplementary rows as a control group
3. **Act**: Call `self.accessor.delete_usage_costs(cost_type="Infrastructure", report_period_id=rp_id, start_date=start, end_date=end)`
4. **Assert**: `assertEqual(OCPUsageLineItemDailySummary.objects.filter(cost_model_rate_type="Infrastructure", cost_breakdown_source__isnull=False, usage_start__range=(start, end)).count(), 0)`
5. **Assert**: Supplementary rows count unchanged

**Exit criteria**:
- All Infrastructure rows within date range deleted (regardless of `cost_breakdown_source`)
- Supplementary rows and rows outside date range untouched

### TS4-04: `populate_monthly_cost_sql` writes `cost_breakdown_source` for node monthly cost

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: Phase A migration

**Business outcome**: Monthly fixed costs are tagged with their description in the database.

**Steps**:
1. **Arrange**: Ensure OCP report period with at least 1 node in test schema
2. **Act**: Call `self.accessor.populate_monthly_cost_sql(cost_type="Node", rate_type="Infrastructure", rate=Decimal("100.0"), cost_breakdown_source="Node monthly license", start_date=start, end_date=end, ...)`
3. **Assert**: `qs = ...filter(monthly_cost_type="Node", cost_breakdown_source="Node monthly license")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: `assertAlmostEqual(qs.first().cost_model_cpu_cost, Decimal("3.225806"), places=4)` — $100 / 31 days

| Expected | Value |
|----------|-------|
| `cost_breakdown_source` | `"Node monthly license"` |
| `monthly_cost_type` | `"Node"` |
| Daily amortized cost | `Decimal("3.225806")` |

**Exit criteria**:
- Monthly cost rows tagged with correct `cost_breakdown_source` and amortized value

### TS4-05: `populate_tag_usage_costs` writes `cost_breakdown_source` with tag-value description

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: Phase A migration

**Business outcome**: Tag-based costs carry the description from the tag value definition.

**Steps**:
1. **Arrange**: Create OCP usage data with `pod_labels = {"environment": "production"}` and `pod_usage_cpu_core_hours = 2.0`
2. **Act**: Call `self.accessor.populate_tag_usage_costs(cost_type="Infrastructure", tag_key="environment", tag_value="production", rate=Decimal("10.0"), cost_breakdown_source="Production environment", ...)`
3. **Assert**: `qs = ...filter(cost_breakdown_source="Production environment")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: Cost values ≈ `Decimal("20.00")` (2.0 × $10.0)

**Exit criteria**:
- Matching pods have `cost_breakdown_source="Production environment"` with correct cost
- Non-matching pods have no tag-rate rows inserted

### TS4-06: `populate_markup_cost` does NOT overwrite `cost_breakdown_source`

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: TS4-01

**Business outcome**: Applying markup preserves the original rate description; markup tracked via `infrastructure_markup_cost` column.

**Steps**:
1. **Arrange**: Call `populate_usage_costs` to create rows with `cost_breakdown_source="JBoss subscription"` and known `infrastructure_raw_cost = Decimal("10.00")`
2. **Arrange**: Record `source_before = list(qs.values_list("cost_breakdown_source", flat=True))`
3. **Act**: Call `self.accessor.populate_markup_cost(markup=Decimal("0.10"), ...)`
4. **Assert**: `source_after = list(qs.values_list("cost_breakdown_source", flat=True))`
5. **Assert**: `assertEqual(source_before, source_after)` — no change
6. **Assert**: `assertAlmostEqual(row.infrastructure_markup_cost, Decimal("1.00"), places=2)` — 10.00 × 0.10

**Exit criteria**:
- `cost_breakdown_source` identical before and after markup; no new rows inserted (UPDATE-only)

### TS4-07: `populate_usage_costs` preserves existing `cost.*` fields (backward compatibility)

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: TS4-01

**Business outcome**: The new column is populated without breaking existing cost column values.

**Steps**:
1. **Arrange**: Use same rates as TS4-01
2. **Act**: Call `populate_usage_costs` with `cost_breakdown_source="JBoss subscription"`
3. **Assert**: `assertIsNotNone(row.cost_model_cpu_cost)` and value matches `Decimal("10.00")`
4. **Assert**: `assertEqual(row.cost_model_rate_type, "Infrastructure")`
5. **Assert**: `assertEqual(row.cost_breakdown_source, "JBoss subscription")` — new field also set

**Exit criteria**:
- Existing columns have same values as pre-feature; `cost_breakdown_source` is additive only

### TS4-08: `populate_distributed_cost_sql` qualifies `cost_breakdown_source` with distribution type

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: TS4-01

**Business outcome**: Distributed platform costs show both the original rate and distribution type for Sankey drill-down.

**Steps**:
1. **Arrange**: Insert platform namespace rows with `cost_breakdown_source="JBoss subscription"`, cost = $30
2. **Arrange**: Ensure at least 1 user project namespace exists
3. **Act**: Call `self.accessor.populate_distributed_cost_sql(...)` for platform distribution
4. **Assert**: `qs = ...filter(namespace="test-project", cost_breakdown_source="JBoss subscription [platform]")`
5. **Assert**: `assertTrue(qs.exists())`
6. **Assert**: `distributed_cost` is proportional to source cost and project's usage share

**Exit criteria**:
- All distributed rows have format `"<description> [platform]"`; costs are proportional

### TS4-09: Distributed costs with multiple source descriptions produce multiple distributed rows per project

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: TS4-08

**Business outcome**: A project receives separate distributed rows per source rate (not one merged row).

**Steps**:
1. **Arrange**: Insert platform rows: `"JBoss subscription"` cost=$30, `"RHEL license"` cost=$20
2. **Arrange**: Configure project to receive 50% of platform costs
3. **Act**: Call `populate_distributed_cost_sql` for platform distribution
4. **Assert**: Project has `"JBoss subscription [platform]"` with `distributed_cost ≈ Decimal("15.00")`
5. **Assert**: Project has `"RHEL license [platform]"` with `distributed_cost ≈ Decimal("10.00")`
6. **Assert**: Sum = $25 = 50% of $50 total platform cost

**Exit criteria**:
- 2 distributed rows per project (one per source); proportional split per description

### TS4-10: Unattributed storage distribution uses fixed description

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: Phase A migration

**Business outcome**: Unattributed storage costs use standardized label for the Sankey.

**Steps**:
1. **Arrange**: Ensure unattributed storage costs exist; storage distribution enabled
2. **Act**: Call `populate_distributed_cost_sql` for unattributed storage
3. **Assert**: `qs = ...filter(cost_breakdown_source="Storage unattributed")`
4. **Assert**: `assertTrue(qs.exists())`

**Exit criteria**:
- All rows have exact string `"Storage unattributed"` — hardcoded, not derived from rates

### TS4-11: Unattributed network distribution uses fixed description

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: Phase A migration

**Business outcome**: Same as TS4-10 but for network.

**Steps**:
1. **Arrange**: Ensure unattributed network costs exist; network distribution enabled
2. **Act**: Call `populate_distributed_cost_sql` for unattributed network
3. **Assert**: `qs = ...filter(cost_breakdown_source="Network unattributed")`
4. **Assert**: `assertTrue(qs.exists())`

**Exit criteria**:
- All rows have exact string `"Network unattributed"` — hardcoded

### TS4-12: `populate_tag_usage_default_costs` writes `cost_breakdown_source` for default tag rates

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: Phase A migration

**Business outcome**: Default tag-based costs carry the rate-level description for Sankey.

**Steps**:
1. **Arrange**: Create OCP usage data with `pod_labels = {"environment": "unknown_value"}` and `pod_usage_cpu_core_hours = 2.0`
2. **Act**: Call `self.accessor.populate_tag_usage_default_costs(cost_type="Infrastructure", tag_key="environment", default_rate=Decimal("5.0"), cost_breakdown_source="Environment tag rate", ...)`
3. **Assert**: `qs = ...filter(cost_breakdown_source="Environment tag rate")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: Cost ≈ `Decimal("10.00")` (2.0 × $5.0)

**Exit criteria**:
- Default-matched pods have `cost_breakdown_source="Environment tag rate"`
- Pods matching specific tag values (e.g., "production") do NOT have this description

### TS4-13: `populate_vm_usage_costs_postgres` writes `cost_breakdown_source` for `OCP_VM_HOUR`

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: Phase A migration

**Business outcome**: VM hourly costs via the Postgres proxy carry the rate description as distinct Sankey nodes.

**Steps**:
1. **Arrange**: Create OCP usage data with VM pod: `pod_labels = {"vm_kubevirt_io_name": "test-vm-1"}`
2. **Act**: Call `self.accessor.populate_vm_usage_costs_postgres(metric="OCP_VM_HOUR", rate=Decimal("0.50"), cost_type="Infrastructure", cost_breakdown_source="VM hourly subscription", ...)`
3. **Assert**: `qs = ...filter(cost_breakdown_source="VM hourly subscription")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: `assertAlmostEqual(row.infrastructure_raw_cost, Decimal("12.00"), places=2)` — 24 × $0.50
6. **Assert**: Non-VM pods have no rows with this description

| Expected | Value |
|----------|-------|
| `cost_breakdown_source` | `"VM hourly subscription"` |
| Cost per VM per day | `Decimal("12.00")` (24h × $0.50) |

**Exit criteria**:
- VM pods tagged; 24h/day assumption applied; non-VM pods excluded

### TS4-14: `populate_vm_usage_costs_postgres` writes `cost_breakdown_source` for `OCP_VM_CORE_HOUR`

**Type**: Integration (DB) | **TDD Phase**: E | **Depends on**: TS4-13

**Business outcome**: VM core hourly costs use `pod_request_cpu_core_hours` as the usage proxy.

**Steps**:
1. **Arrange**: Create OCP usage data with VM pod: `pod_labels = {"vm_kubevirt_io_name": "test-vm-1"}`, `pod_request_cpu_core_hours = 48.0`
2. **Act**: Call `self.accessor.populate_vm_usage_costs_postgres(metric="OCP_VM_CORE_HOUR", rate=Decimal("0.10"), cost_type="Infrastructure", cost_breakdown_source="VM core hourly cost", ...)`
3. **Assert**: `qs = ...filter(cost_breakdown_source="VM core hourly cost")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: `assertAlmostEqual(row_cost, Decimal("4.80"), places=2)` — 48.0 × $0.10
6. **Assert**: Non-VM pods excluded

| Expected | Value |
|----------|-------|
| `cost_breakdown_source` | `"VM core hourly cost"` |
| Cost | `Decimal("4.80")` (48.0 core-hours × $0.10) |

**Exit criteria**:
- VM pods tagged; `pod_request_cpu_core_hours × rate` proxy applied; non-VM pods excluded

### TS4-15: `populate_usage_costs` with rate = 0 still writes `cost_breakdown_source` (edge case)

**Type**: Integration (DB) | **TDD Phase**: C | **Depends on**: TS4-01

**Business outcome**: A rate of $0 still produces a tracked row so the Sankey shows the rate exists (at zero cost), rather than silently omitting it.

**Steps**:
1. **Arrange**: Same fixture as TS4-01
2. **Act**: Call `populate_usage_costs(cost_type="Infrastructure", rates={cpu: 0.0, others: 0}, cost_breakdown_source="Free tier CPU", ...)`
3. **Assert**: `qs = ...filter(cost_breakdown_source="Free tier CPU")`
4. **Assert**: `assertTrue(qs.exists())`
5. **Assert**: `assertEqual(row.cost_model_cpu_cost, Decimal("0.00"))`

**Exit criteria**:
- Row exists with `cost_breakdown_source="Free tier CPU"` and zero cost (not omitted)

---

## Test Suite 5: API Query Handler

**File**: [`koku/api/report/test/ocp/test_ocp_query_handler.py`](../../koku/api/report/test/ocp/test_ocp_query_handler.py)
**Base class**: `IamTestCase`
**Requirement coverage**: R3, R8, R9, R10, AD-4

### TS5-01: `cost_breakdown` field present in costs_by_project response

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS4-01, TS3-01 (full pipeline)

**Business outcome**: The API response includes the new `cost_breakdown` list alongside the existing `cost` object.

**Steps**:
1. **Arrange**: Use `IamTestCase` fixtures with OCP data and cost model applied (summary tables populated with `cost_breakdown_source`)
2. **Act**: Call the costs_by_project query handler to get response `data`
3. **Assert**: For each `values` entry in `data`: `assertIn("cost_breakdown", values)`
4. **Assert**: `assertIsInstance(values["cost_breakdown"], list)`

**Exit criteria**:
- Every `values` entry contains `cost_breakdown` as a list (not dict, string, or null)

### TS5-02: `cost_breakdown` entries have correct structure

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: Each entry in `cost_breakdown` contains the `source`, `value`, and `units` keys the frontend needs.

**Steps**:
1. **Arrange**: Same as TS5-01
2. **Act**: Query costs_by_project; extract `cost_breakdown` list from first values entry
3. **Assert**: For each entry: `assertIn("source", entry)`, `assertIn("value", entry)`, `assertIn("units", entry)`
4. **Assert**: `assertEqual(entry["units"], "USD")`
5. **Assert**: `assertIsInstance(entry["value"], (Decimal, float))`
6. **Assert**: `assertTrue(len(entry["source"]) > 0)` — non-empty string

**Exit criteria**:
- Every entry has exactly 3 keys: `source` (non-empty string), `value` (numeric), `units` ("USD")

### TS5-03: `cost_breakdown` contains distinct sources matching rate descriptions

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-02

**Business outcome**: The Sankey diagram receives actual rate descriptions from the customer's cost model.

**Steps**:
1. **Arrange**: Apply cost model with `MULTI_RATE_COST_MODEL_RATES` to OCP data; refresh summary tables
2. **Act**: Query costs_by_project; collect all `source` values from `cost_breakdown`
3. **Assert**: `assertIn("JBoss subscription", sources)`
4. **Assert**: `assertIn("Guest OS subscription (RHEL)", sources)`
5. **Assert**: `assertIn("Quota charge", sources)`
6. **Assert**: No duplicate source strings: `assertEqual(len(sources), len(set(sources)))`

**Exit criteria**:
- Sources are customer-meaningful descriptions, not metric names; no duplicates

### TS5-04: `cost_breakdown` includes synthetic "Markup" entry

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01, TS4-06

**Business outcome**: The Sankey shows a "Markup" line item computed from infrastructure markup costs.

**Steps**:
1. **Arrange**: Apply cost model with `markup = Decimal("0.10")`; populate usage costs and markup
2. **Act**: Query costs_by_project; find entry where `source == "Markup"`
3. **Assert**: Exactly 1 "Markup" entry exists
4. **Assert**: `assertAlmostEqual(markup_entry["value"], cost["markup"]["value"], places=6)`

**Exit criteria**:
- Exactly 1 "Markup" entry (not per-rate); value matches `cost.markup.value`

### TS5-05: `cost_breakdown` values sum equals `cost.total`

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-03, TS5-04

**Business outcome**: Mathematical consistency — the Sankey diagram balances.

**Steps**:
1. **Arrange**: Apply full cost model with usage rates, monthly rates, and markup
2. **Act**: Query costs_by_project; compute `breakdown_sum = sum(e["value"] for e in cost_breakdown)`
3. **Assert**: `assertAlmostEqual(breakdown_sum, cost["total"]["value"], places=2)`

**Exit criteria**:
- Sum of `cost_breakdown` values equals `cost.total` within $0.01 — no dollars lost or created

### TS5-06: Existing `cost` object fields are unchanged (backward compatibility)

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: Existing frontend consumers relying on `cost.*` continue to work identically.

**Steps**:
1. **Arrange**: Same data as TS5-05
2. **Act**: Query costs_by_project; extract `cost` object
3. **Assert**: `assertIn("raw", cost)`, `assertIn("usage", cost)`, `assertIn("markup", cost)`, `assertIn("total", cost)`
4. **Assert**: `assertAlmostEqual(cost["total"]["value"], expected_db_aggregate, places=6)`

**Exit criteria**:
- All pre-existing `cost.*` fields present with correct values; no fields renamed or removed

### TS5-07: `cost_breakdown` in `total` section sums across all projects

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-03

**Business outcome**: Account-level Sankey aggregates breakdown across all projects.

**Steps**:
1. **Arrange**: OCP data spanning 2+ projects with cost model applied
2. **Act**: Query costs_by_project; extract `total` section and per-project sections
3. **Assert**: `assertIn("cost_breakdown", total)`
4. **Assert**: For each unique source: `total_value == sum(project_values)` across all projects

**Exit criteria**:
- `total.cost_breakdown` contains all sources from individual projects; sums match

### TS5-08: `cost_breakdown` includes distributed cost entries with qualifiers

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS4-08

**Business outcome**: Distributed platform costs appear in the Sankey with `[platform]` qualifier for Level 2 drill-down.

**Steps**:
1. **Arrange**: Enable platform distribution; apply multi-rate cost model; refresh summary tables
2. **Act**: Query costs_by_project; filter `cost_breakdown` for entries ending with `" [platform]"`
3. **Assert**: At least 1 `[platform]` entry exists
4. **Assert**: `platform_sum = sum(...)` ≈ `cost["platform_distributed"]["value"]` within $0.01

**Exit criteria**:
- `[platform]` entries exist; their sum matches `cost.platform_distributed.value`

### TS5-09: `cost_breakdown` includes distributed cost entries with worker qualifier

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS4-08

**Business outcome**: Worker-distributed overhead shows `[worker]` qualifier.

**Steps**:
1. **Arrange**: Enable worker distribution; apply cost model; refresh summary tables
2. **Act**: Query costs_by_project; filter for entries ending with `" [worker]"`
3. **Assert**: At least 1 `[worker]` entry exists
4. **Assert**: `worker_sum = sum(...)` ≈ `cost["worker_unallocated_distributed"]["value"]` within $0.01

**Exit criteria**:
- `[worker]` entries exist; their sum matches `cost.worker_unallocated_distributed.value`

### TS5-10: `cost_breakdown` appears in costs report (not just costs_by_project)

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: The Sankey is available in the overall costs report view.

**Steps**:
1. **Arrange**: Standard OCP test data with cost model
2. **Act**: Query the `costs` endpoint (not `costs_by_project`)
3. **Assert**: `assertIn("cost_breakdown", values)` for total values
4. **Assert**: Structure matches TS5-02 (same keys: `source`, `value`, `units`)

**Exit criteria**:
- `costs` report type includes `cost_breakdown` with matching structure

### TS5-11: `cost_breakdown` appears in costs_by_node report

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: The breakdown is available when grouping by node.

**Steps**:
1. **Arrange**: Standard OCP test data with cost model
2. **Act**: Query `costs_by_node` endpoint
3. **Assert**: Each node entry has `cost_breakdown` list with valid structure

**Exit criteria**:
- Each node entry includes `cost_breakdown`; structure matches other report types

### TS5-12: Two rates for the same metric appear as separate `cost_breakdown` entries

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-03, TS4-02

**Business outcome**: Duplicate CPU rates appear individually in the Sankey, not merged.

**Steps**:
1. **Arrange**: Apply cost model with 2 CPU rates: "JBoss subscription" (Infra $5) and "Quota charge" (Supp $2)
2. **Act**: Query costs_by_project; extract `cost_breakdown` sources
3. **Assert**: `assertIn("JBoss subscription", sources)` and `assertIn("Quota charge", sources)`
4. **Assert**: Their values differ (reflect $5 vs $2 rates)

**Exit criteria**:
- Both descriptions appear as distinct entries; API aggregation did not merge by metric name

### TS5-13: `cost_breakdown` is empty list when no cost model applied (edge case)

**Type**: Integration (API) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: When no cost model is applied, `cost_breakdown` is an empty list (not null or missing), ensuring the frontend can always iterate safely.

**Steps**:
1. **Arrange**: OCP data with NO cost model applied (no usage costs, no monthly costs)
2. **Act**: Query costs_by_project
3. **Assert**: `assertIn("cost_breakdown", values)`
4. **Assert**: `assertEqual(values["cost_breakdown"], [])`

**Exit criteria**:
- `cost_breakdown` is present as empty list `[]`, not `null` or absent

---

## Test Suite 6: API View Integration

**File**: [`koku/api/report/test/ocp/view/test_views.py`](../../koku/api/report/test/ocp/view/test_views.py)
**Base class**: `IamTestCase`
**Requirement coverage**: R3, R8, R9, AD-4

### TS6-01: Costs endpoint returns `cost_breakdown` in HTTP 200 response

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS5-01

**Business outcome**: The full API endpoint returns the `cost_breakdown` field when queried.

**Steps**:
1. **Arrange**: Standard OCP data with cost model applied (`IamTestCase` fixtures)
2. **Act**: `response = APIClient().get(reverse("reports-openshift-costs"), **self.headers)`
3. **Assert**: `assertEqual(response.status_code, 200)`
4. **Assert**: Parse `response.json()`; navigate to `data[0]["values"][0]`
5. **Assert**: `assertIn("cost_breakdown", values)`

**Exit criteria**:
- HTTP 200 with valid JSON containing `cost_breakdown` in the expected data structure

### TS6-02: Costs by project endpoint returns `cost_breakdown` with per-project data

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS6-01

**Business outcome**: Each project has its own breakdown reflecting rates applied to that project's usage.

**Steps**:
1. **Arrange**: OCP data with 2+ projects and `MULTI_RATE_COST_MODEL_RATES` cost model
2. **Act**: `response = APIClient().get(reverse("reports-openshift-costs") + "?group_by[project]=*", **self.headers)`
3. **Assert**: `assertEqual(response.status_code, 200)`
4. **Assert**: Each project entry has `cost_breakdown` list with `len >= 1`
5. **Assert**: Sources match rate descriptions from cost model (not metric names)

**Exit criteria**:
- HTTP 200; each project's `cost_breakdown` independently populated; at least 2 projects have entries

### TS6-03: Costs by node endpoint returns `cost_breakdown`

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS6-01

**Business outcome**: Node-grouped reports include the breakdown.

**Steps**:
1. **Arrange**: OCP data with cost model
2. **Act**: `response = APIClient().get(reverse("reports-openshift-costs") + "?group_by[node]=*", **self.headers)`
3. **Assert**: `assertEqual(response.status_code, 200)`
4. **Assert**: Each node entry has `cost_breakdown` with entries having `source`, `value`, `units`

**Exit criteria**:
- HTTP 200; each node entry contains valid `cost_breakdown` list

### TS6-04: Existing cost fields in response unchanged after feature

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS6-01

**Business outcome**: No regression — existing `cost` object is identical to pre-feature values.

**Steps**:
1. **Arrange**: OCP data with cost model; pre-compute expected `cost.total` from DB aggregate
2. **Act**: `response = APIClient().get(reverse("reports-openshift-costs"), **self.headers)`
3. **Assert**: `cost = response.json()["data"][0]["values"][0]["cost"]`
4. **Assert**: `assertIn("raw", cost)`, `assertIn("markup", cost)`, `assertIn("total", cost)`
5. **Assert**: `assertAlmostEqual(cost["total"]["value"], expected_total, places=6)`

**Exit criteria**:
- All pre-existing `cost` keys present with correct values; no fields renamed or removed

### TS6-05: `cost_breakdown` "Markup" value matches `cost.markup` value

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS6-02, TS5-04

**Business outcome**: The synthetic Markup entry is mathematically consistent with the existing markup field.

**Steps**:
1. **Arrange**: OCP data with cost model and `markup = Decimal("0.10")`
2. **Act**: Query costs_by_project endpoint
3. **Act**: `markup_entry = next(e for e in cost_breakdown if e["source"] == "Markup")`
4. **Assert**: `assertAlmostEqual(markup_entry["value"], cost["markup"]["value"], places=6)`

**Exit criteria**:
- "Markup" entry exists; value matches `cost.markup.value` within 6 decimal places

### TS6-06: `cost_breakdown` platform entries sum matches `cost.platform_distributed`

**Type**: Integration (HTTP) | **TDD Phase**: F | **Depends on**: TS6-02, TS5-08

**Business outcome**: Level 2 drill-down is mathematically consistent with Level 1 for platform costs.

**Steps**:
1. **Arrange**: OCP data with platform distribution and cost model
2. **Act**: Query costs_by_project endpoint
3. **Act**: `platform_entries = [e for e in cost_breakdown if e["source"].endswith(" [platform]")]`
4. **Act**: `platform_sum = sum(e["value"] for e in platform_entries)`
5. **Assert**: `assertAlmostEqual(platform_sum, cost["platform_distributed"]["value"], places=2)`

**Exit criteria**:
- Sum of `[platform]` entries equals `cost.platform_distributed.value` within $0.01

---

## Requirements Traceability Matrix

| Requirement | Test Scenarios | Description |
|-------------|---------------|-------------|
| R1 — Rate description mandatory | TS1-01, TS1-02, TS1-03, TS1-04 | Serializer validates description is required and non-blank |
| R2 — Per-rate cost tracking | TS2-01, TS2-02, TS3-01, TS4-01, TS4-02 | Each rate produces separate DB entry with description |
| R3 — API cost breakdown field | TS5-01, TS5-02, TS5-13, TS6-01, TS6-02, TS6-03 | `cost_breakdown` list present in API response (including empty-list edge case) |
| R4 — Usage rates broken out | TS2-01, TS3-01, TS3-03, TS3-09, TS3-10, TS4-01, TS4-02, TS4-13, TS4-14, TS4-15 | Usage rates (including VM hourly proxy, zero-rate, and empty-rates edges) individually tracked |
| R5 — Monthly costs broken out | TS3-04, TS3-07, TS4-04 | Monthly costs carry description |
| R6 — Tag rates broken out | TS2-05, TS2-06, TS2-07, TS2-08, TS3-05, TS3-08, TS4-05, TS4-12 | Tag rates (including defaults) carry 3-tier description fallback |
| R7 — Distributed costs broken out | TS4-08, TS4-09, TS4-10, TS4-11, TS5-08, TS5-09 | Distributed costs qualified with type |
| R8 — Markup as API-level aggregate | TS4-06, TS5-04, TS6-05 | Markup computed at API layer, not DB column |
| R9 — Backward compatibility | TS2-04, TS4-07, TS5-06, TS6-04 | Existing fields/values unchanged |
| R10 — Individual rate breakout | TS2-02, TS3-01, TS5-12 | Duplicate metrics stay separate |

### Coverage Summary

| Test Suite | File | Scenarios | Type | New/Modified Methods Covered |
|------------|------|-----------|------|------------------------------|
| TS1 | `test_serializers.py` | 4 | Unit (serializer) | `RateSerializer.validate` (description required) |
| TS2 | `test_cost_model_db_accessor.py` | 8 | Integration (accessor+DB) | `itemized_rates`, `tag_based_price_list` (description), `tag_infrastructure_rates` (description), `tag_default_infrastructure_rates` (description), `price_list` (backward compat) |
| TS3 | `test_ocp_cost_model_cost_updater.py` | **10** | Unit (mocked) | `_update_usage_costs` (per-rate + VM routing + empty-rates edge), `_update_monthly_cost` (description), `_update_tag_usage_costs` (description), `_update_tag_usage_default_costs` (description), `delete_usage_costs` call ordering |
| TS4 | `test_ocp_report_db_accessor.py` | **15** | Integration (DB) | `populate_usage_costs` (+source + zero-rate edge), `delete_usage_costs`, `populate_monthly_cost_sql` (+source), `populate_tag_usage_costs` (+source), `populate_tag_usage_default_costs` (+source), `populate_vm_usage_costs_postgres` (+source), `populate_markup_cost` (no overwrite), `populate_distributed_cost_sql` (qualifier) |
| TS5 | `test_ocp_query_handler.py` | **13** | Integration (API) | `cost_breakdown` annotation, synthetic Markup, total aggregation, report type coverage, empty-list edge |
| TS6 | `test_views.py` | 6 | Integration (HTTP) | HTTP endpoint integration, response structure, mathematical consistency |
| **Total** | | **56** | | |

### Estimated Coverage

| Layer | Methods/Code Paths | Covered by Tests | Est. Coverage |
|-------|--------------------|-----------------|---------------|
| Serializer | `RateSerializer` validation | TS1-01..04 | ~90% |
| Accessor (`itemized_rates`) | new property + fallback | TS2-01..04 | ~85% |
| Accessor (tag description) | `tag_based_price_list` + derivatives | TS2-05..08 | ~80% |
| Updater (usage) | `_update_usage_costs` rewrite + VM routing + empty edge | TS3-01..03, TS3-06, TS3-09, TS3-10 | ~90% |
| Updater (monthly) | `_update_monthly_cost` + description | TS3-04, TS3-07 | ~80% |
| Updater (tags) | `_update_tag_usage_costs` + `_update_tag_usage_default_costs` + description | TS3-05, TS3-08 | ~75% |
| DB Accessor (usage) | `populate_usage_costs` + `delete_usage_costs` + zero-rate edge | TS4-01..03, TS4-07, TS4-15 | ~90% |
| DB Accessor (monthly) | `populate_monthly_cost_sql` + source | TS4-04 | ~75% |
| DB Accessor (tags) | `populate_tag_usage_costs` + `populate_tag_usage_default_costs` + source | TS4-05, TS4-12 | ~75% |
| DB Accessor (markup) | `populate_markup_cost` no overwrite | TS4-06 | ~80% |
| DB Accessor (VM proxy) | `populate_vm_usage_costs_postgres` (OCP_VM_HOUR, OCP_VM_CORE_HOUR) | TS4-13, TS4-14 | ~80% |
| DB Accessor (distribute) | `populate_distributed_cost_sql` + qualifier | TS4-08..11 | ~80% |
| API (query handler) | annotations + synthetic Markup + empty-list edge | TS5-01..13 | ~85% |
| API (views) | endpoint integration | TS6-01..06 | ~75% |
| **Weighted Average** | | | **~82%** |

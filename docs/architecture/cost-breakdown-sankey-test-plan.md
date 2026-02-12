# Test Plan: Cost Breakdown by Rate Description (COST-2105)

**Date**: 2026-02-06
**Version**: 1.1
**Related DD**: [cost-breakdown-sankey.md](./cost-breakdown-sankey.md) v1.4
**Approach**: Test-Driven Development (TDD)
**Target Coverage**: >70% of new/modified code

---

## Table of Contents

- [Overview](#overview)
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

### Principles

1. **Business outcome validation** — every test asserts a customer-visible behavior or a data integrity invariant
2. **Deterministic data** — all test rates, descriptions, and expected cost values are explicit; no randomness
3. **No anti-patterns** — no tests for empty/nil/missing unless it validates a specific fallback behavior the user experiences
4. **Follows existing patterns** — `MasuTestCase` for pipeline tests, `IamTestCase` for API tests, `assertAlmostEqual` for cost values, `@patch` for isolation

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

**Business outcome**: A user creating a new cost model rate with a description succeeds.

**Prerequisites**:
- `RateSerializer` has been updated to make `description` required (`required=True`, `allow_blank=False`)
- A valid OCP provider exists in the test tenant

**Setup**:

| Input | Expected |
|-------|----------|
| `RateSerializer(data={"metric": {"name": "cpu_core_usage_per_hour"}, "cost_type": "Infrastructure", "description": "JBoss subscription", "tiered_rates": [{"value": 5.0, "unit": "USD"}]})` | `serializer.is_valid()` returns `True` |

**Assertions**:
- `assertTrue(serializer.is_valid())`
- `assertEqual(serializer.validated_data["description"], "JBoss subscription")`

**Exit criteria**:
- Serializer validation passes
- The `description` field value is preserved exactly as submitted in `validated_data`

### TS1-02: Rate without description fails validation

**Business outcome**: A user creating a new cost model rate without a description is rejected with a clear error.

**Prerequisites**:
- `RateSerializer` has been updated to make `description` required
- Rate data is otherwise valid (valid metric, cost_type, tiered_rates)

**Setup**:

| Input | Expected |
|-------|----------|
| Same as TS1-01 but `description` key omitted | `serializer.is_valid()` returns `False`; `"description"` in `serializer.errors` |

**Assertions**:
- `assertFalse(serializer.is_valid())`
- `assertIn("description", serializer.errors)`

**Exit criteria**:
- Serializer validation fails
- Error response explicitly references the `description` field
- No cost model instance is created

### TS1-03: Rate with blank description fails validation

**Business outcome**: A user submitting an empty string description is rejected (description must be meaningful).

**Prerequisites**:
- `RateSerializer` has been updated with `allow_blank=False` on `description`
- Rate data is otherwise valid

**Setup**:

| Input | Expected |
|-------|----------|
| Same as TS1-01 with `"description": ""` | `serializer.is_valid()` returns `False` |

**Assertions**:
- `assertFalse(serializer.is_valid())`
- `assertIn("description", serializer.errors)`

**Exit criteria**:
- Serializer validation fails
- Error response explicitly references the `description` field
- No cost model instance is created

### TS1-04: Full cost model with multiple described rates saves successfully

**Business outcome**: A cost model with multiple rates, each having a unique description, is created and persisted.

**Prerequisites**:
- `RateSerializer` and `CostModelSerializer` support required `description`
- A valid OCP provider exists in the test tenant
- `MULTI_RATE_COST_MODEL_RATES` test data is available (5 rates with distinct descriptions)

**Setup**:

| Input | Expected |
|-------|----------|
| `CostModelSerializer` with `MULTI_RATE_COST_MODEL_RATES` | Instance created; `instance.rates` contains 5 rates each with their description preserved |

**Assertions**:
- `assertIsNotNone(instance.uuid)`
- For each rate in `instance.rates`: `assertIn("description", rate)` and description matches input

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

**Business outcome**: The pipeline receives each rate as a separate entry with its description preserved, enabling per-rate cost tracking.

**Prerequisites**:
- `CostModelDBAccessor.itemized_rates` property is implemented
- A `CostModel` instance exists with `MULTI_RATE_COST_MODEL_RATES` (5 rates) persisted in the test schema

**Setup**: Create cost model with `MULTI_RATE_COST_MODEL_RATES` (5 rates).

**Assertions**:
- `assertEqual(len(accessor.itemized_rates), 5)`
- Rate 0: `assertEqual(rate["metric"], "cpu_core_usage_per_hour")`, `assertEqual(rate["cost_type"], "Infrastructure")`, `assertEqual(rate["value"], 5.0)`, `assertEqual(rate["description"], "JBoss subscription")`
- Rate 2: `assertEqual(rate["metric"], "cpu_core_usage_per_hour")`, `assertEqual(rate["cost_type"], "Supplementary")`, `assertEqual(rate["value"], 2.0)`, `assertEqual(rate["description"], "Quota charge")`

**Exit criteria**:
- Exactly 5 rate dicts returned
- Each dict contains keys: `metric`, `cost_type`, `value`, `description`
- All values and descriptions match the input `MULTI_RATE_COST_MODEL_RATES` in order

### TS2-02: `itemized_rates` preserves duplicate metrics as separate entries

**Business outcome**: When a customer defines two CPU rates (Infrastructure + Supplementary) with different descriptions, both appear individually — they are not summed (R10).

**Prerequisites**:
- `CostModelDBAccessor.itemized_rates` property is implemented
- A `CostModel` instance exists with at least 2 rates sharing the same `metric.name` but differing in `cost_type`

**Setup**: Cost model with two `cpu_core_usage_per_hour` rates: Infrastructure "JBoss subscription" ($5) and Supplementary "Quota charge" ($2).

**Assertions**:
- CPU rates in result: exactly 2 entries with `metric == "cpu_core_usage_per_hour"`
- Entry 1: `description == "JBoss subscription"`, `value == 5.0`, `cost_type == "Infrastructure"`
- Entry 2: `description == "Quota charge"`, `value == 2.0`, `cost_type == "Supplementary"`

**Exit criteria**:
- Both CPU rates are returned as distinct list entries (not merged/summed)
- The `value` fields are 5.0 and 2.0 respectively (not 7.0)
- Each entry has the correct `cost_type` and `description`

### TS2-03: `itemized_rates` falls back to metric name when description is missing

**Business outcome**: A legacy cost model without descriptions still works; the metric name serves as the identifier the customer sees in the Sankey.

**Prerequisites**:
- `CostModelDBAccessor.itemized_rates` property implements the metric-name fallback
- A `CostModel` instance exists with a rate that has no `description` key

**Setup**: Cost model with one rate: `{"metric": {"name": "cpu_core_usage_per_hour"}, "cost_type": "Infrastructure", "tiered_rates": [{"value": 5.0}]}` (no `description` key).

**Assertions**:
- `assertEqual(len(accessor.itemized_rates), 1)`
- `assertEqual(accessor.itemized_rates[0]["description"], "cpu_core_usage_per_hour")`

**Exit criteria**:
- The `description` field is populated with the metric name `"cpu_core_usage_per_hour"`
- No exception is raised due to the missing `description` key

### TS2-04: `price_list` remains unchanged (backward compatibility)

**Business outcome**: Existing code paths that use `price_list` continue to work. The `price_list` still sums duplicate metrics.

**Prerequisites**:
- `CostModelDBAccessor.price_list`, `infrastructure_rates`, `supplementary_rates` have NOT been modified
- A `CostModel` instance exists with `MULTI_RATE_COST_MODEL_RATES`

**Setup**: Cost model with `MULTI_RATE_COST_MODEL_RATES`.

**Assertions**:
- `price_list` returns a dict keyed by metric name (existing behavior)
- `infrastructure_rates` and `supplementary_rates` return summed values per metric (existing behavior)
- No `description` key in `price_list` entries (structure unchanged)

**Exit criteria**:
- `price_list` dict structure is identical to pre-feature behavior
- `infrastructure_rates["cpu_core_usage_per_hour"]` equals the summed value (5.0, not split)
- No new keys appear in the returned dicts

### TS2-05: `tag_based_price_list` propagates tag-value description

**Business outcome**: Tag rates carry the most granular description available so the Sankey shows meaningful tag-rate labels.

**Prerequisites**:
- `CostModelDBAccessor.tag_based_price_list` has been modified to propagate the `description` field
- A `CostModel` instance exists with `MULTI_RATE_TAG_RATE` containing tag values with mixed description states

**Setup**: Cost model with `MULTI_RATE_TAG_RATE` (production has description "Production environment", staging has blank description).

**Assertions**:
- For tag_value "production": `description == "Production environment"` (tag-value description used)
- For tag_value "staging": `description == "Environment tag rate"` (falls back to rate-level description)

**Exit criteria**:
- "production" tag value uses its own tag-value description (tier 1 of fallback)
- "staging" tag value falls back to the rate-level description (tier 2 of fallback)
- Both tag values retain their numeric `value` field unchanged (10.0 and 4.0)

### TS2-06: `tag_based_price_list` falls back to metric name when both descriptions are missing

**Business outcome**: Legacy tag rates without any descriptions still produce a usable identifier.

**Prerequisites**:
- `CostModelDBAccessor.tag_based_price_list` implements the full 3-tier fallback chain
- A `CostModel` instance exists with `LEGACY_TAG_RATE` (no top-level description, blank tag-value descriptions)

**Setup**: Cost model with `LEGACY_TAG_RATE` (no top-level description, blank tag-value descriptions).

**Assertions**:
- For tag_value "gold": `description == "memory_gb_usage_per_hour"` (metric name fallback)

**Exit criteria**:
- The description resolves to the metric name as last-resort fallback (tier 3)
- No exception is raised
- The numeric `value` (8.0) is preserved

### TS2-07: `tag_infrastructure_rates` carries description alongside value

**Business outcome**: The tag rate dict structure now provides both the numeric value and description for downstream use.

**Prerequisites**:
- `CostModelDBAccessor.tag_infrastructure_rates` has been modified to include `description` in its return structure
- A `CostModel` instance exists with `MULTI_RATE_TAG_RATE`

**Setup**: Cost model with `MULTI_RATE_TAG_RATE`.

**Assertions**:
- `tag_infrastructure_rates` for tag_key "environment" contains tag_value "production" with `value == 10.0` and `description == "Production environment"`

**Exit criteria**:
- The returned dict for each tag value contains both `value` (numeric) and `description` (string)
- Downstream callers can access both fields from the same dict entry

---

## Test Suite 3: OCP Cost Model Cost Updater

**File**: [`koku/masu/test/processor/ocp/test_ocp_cost_model_cost_updater.py`](../../koku/masu/test/processor/ocp/test_ocp_cost_model_cost_updater.py)
**Base class**: `MasuTestCase`
**Requirement coverage**: R2, R4, R5, R6, R7, R10, AD-1

### TS3-01: `_update_usage_costs` calls `populate_usage_costs` once per individual rate

**Business outcome**: Each rate in the cost model produces a separate SQL execution, allowing per-rate cost tracking in the database.

**Prerequisites**:
- `OCPCostModelCostUpdater._update_usage_costs` has been rewritten for per-rate execution
- `OCPCostModelCostUpdater.__init__` loads `_itemized_rates` from the accessor
- A valid OCP provider and report period exist in the test schema
- `MasuTestCase` fixtures provide OCP usage data for the provider

**Setup**: Mock `CostModelDBAccessor` to return `itemized_rates` with 3 usage rates (CPU Infra, Memory Infra, CPU Supplementary).

**Assertions** (via mocked `populate_usage_costs`):
- `populate_usage_costs` called exactly 3 times
- Call 1: `cost_type="Infrastructure"`, rates dict contains only `cpu_core_usage_per_hour`, `cost_breakdown_source="JBoss subscription"`
- Call 2: `cost_type="Infrastructure"`, rates dict contains only `memory_gb_usage_per_hour`, `cost_breakdown_source="Guest OS subscription (RHEL)"`
- Call 3: `cost_type="Supplementary"`, rates dict contains only `cpu_core_usage_per_hour`, `cost_breakdown_source="Quota charge"`

**Exit criteria**:
- `populate_usage_costs` receives exactly 3 calls (1:1 with usage rates)
- Each call passes a single-metric rates dict (not the full rates map)
- Each call includes the correct `cost_breakdown_source` matching the rate's description

### TS3-02: `_update_usage_costs` bulk-deletes before per-rate inserts

**Business outcome**: Stale cost rows from previous rate configurations are cleaned up before new rates are inserted, preventing data corruption.

**Prerequisites**:
- `OCPReportDBAccessor.delete_usage_costs` method exists
- `OCPCostModelCostUpdater._update_usage_costs` calls `delete_usage_costs` before the per-rate loop
- A valid OCP provider and report period exist

**Setup**: Mock `CostModelDBAccessor` with 2 Infrastructure usage rates. Mock `delete_usage_costs` and `populate_usage_costs`.

**Assertions** (via call order on mock):
- `delete_usage_costs` called with `cost_type="Infrastructure"` **before** any `populate_usage_costs` call
- `delete_usage_costs` called with `cost_type="Supplementary"` **before** any `populate_usage_costs` call
- `delete_usage_costs` called exactly 2 times (once per cost_type)

**Exit criteria**:
- Call sequence is: delete(Infra) → delete(Supp) → insert(rate1) → insert(rate2) → ...
- No `populate_usage_costs` call precedes any `delete_usage_costs` call
- Both cost types are deleted even if only one has rates (to clean stale data from removed rates)

### TS3-03: `_update_usage_costs` filters to usage-rate metrics only

**Business outcome**: Monthly cost metrics (node_cost_per_month, cluster_cost_per_month) are not processed by the usage cost path, preventing double-counting.

**Prerequisites**:
- `_update_usage_costs` filters `_itemized_rates` against `metric_constants.COST_MODEL_USAGE_RATES`
- `MULTI_RATE_COST_MODEL_RATES` contains both usage and monthly rate metrics

**Setup**: Mock `itemized_rates` with 5 rates from `MULTI_RATE_COST_MODEL_RATES` (3 usage + 2 monthly).

**Assertions**:
- `populate_usage_costs` called exactly 3 times (only usage-rate metrics)
- No call contains `node_cost_per_month` or `cluster_cost_per_month` in the rates dict

**Exit criteria**:
- Only metrics present in `COST_MODEL_USAGE_RATES` are processed
- Monthly metrics are excluded without error
- The total number of `populate_usage_costs` calls equals the count of usage-rate entries in `_itemized_rates`

### TS3-04: `_update_monthly_cost` passes description to `populate_monthly_cost_sql`

**Business outcome**: Monthly fixed costs (Node license, Cluster fee) carry the rate description through to the database for Sankey display.

**Prerequisites**:
- `_update_monthly_cost` resolves description from `_itemized_rates` and passes it as `cost_breakdown_source`
- `populate_monthly_cost_sql` accepts a `cost_breakdown_source` parameter
- A valid OCP provider and report period exist

**Setup**: Mock `CostModelDBAccessor` with `infrastructure_rates` containing `node_cost_per_month` and `itemized_rates` containing the corresponding entry with `description="Node monthly license"`.

**Assertions** (via mocked `populate_monthly_cost_sql`):
- Called with `cost_breakdown_source="Node monthly license"` for the node cost type

**Exit criteria**:
- `populate_monthly_cost_sql` is called with the exact description string from `itemized_rates`
- The description is resolved by matching both `metric` and `cost_type` (not just metric)

### TS3-05: `_update_tag_usage_costs` passes tag-value description to `populate_tag_usage_costs`

**Business outcome**: Tag-based costs carry the tag-value description into the database so the Sankey shows labels like "Production environment" rather than abstract tag keys.

**Prerequisites**:
- `CostModelDBAccessor.tag_infrastructure_rates` returns descriptions alongside values
- `_update_tag_usage_costs` extracts description from the enriched tag rate structure
- `populate_tag_usage_costs` accepts a `cost_breakdown_source` parameter

**Setup**: Mock `CostModelDBAccessor` with `tag_infrastructure_rates` that include descriptions (as modified by the feature).

**Assertions** (via mocked `populate_tag_usage_costs`):
- Called with `cost_breakdown_source` parameter matching the tag-value description

**Exit criteria**:
- `populate_tag_usage_costs` receives the tag-value description (not the rate-level description or metric name, when tag-value description is available)
- The call includes all other existing parameters unchanged

### TS3-06: `_update_usage_costs` with single rate produces exactly one `populate_usage_costs` call

**Business outcome**: A simple cost model with a single rate works correctly without extra SQL executions.

**Prerequisites**:
- `_update_usage_costs` per-rate loop handles single-element lists correctly
- A valid OCP provider and report period exist

**Setup**: Mock `itemized_rates` with 1 usage rate: CPU Infrastructure "JBoss subscription".

**Assertions**:
- `populate_usage_costs` called exactly 1 time
- `cost_breakdown_source="JBoss subscription"`

**Exit criteria**:
- Exactly 1 SQL execution occurs (no off-by-one errors)
- The single rate's description is passed correctly
- `delete_usage_costs` is still called for both cost types (Infrastructure and Supplementary) before the single insert

### TS3-07: `_update_monthly_cost` resolves description from `itemized_rates` matching metric and cost_type

**Business outcome**: The correct description is paired with the correct monthly rate, even when multiple rates share a metric name but differ in cost_type.

**Prerequisites**:
- `_update_monthly_cost` matches `itemized_rates` by both `metric` AND `cost_type`
- `itemized_rates` contains two entries with the same metric but different cost_types and descriptions

**Setup**: Mock `itemized_rates` with:
- `node_cost_per_month`, Infrastructure, "Node monthly license"
- `node_cost_per_month`, Supplementary, "Node supplementary charge"

Mock `infrastructure_rates` with `node_cost_per_month = 100.0`.
Mock `supplementary_rates` with `node_cost_per_month = 50.0`.

**Assertions**:
- Infrastructure call: `cost_breakdown_source="Node monthly license"`
- Supplementary call: `cost_breakdown_source="Node supplementary charge"`

**Exit criteria**:
- Each `populate_monthly_cost_sql` call receives the description that matches its cost_type
- No cross-contamination between Infrastructure and Supplementary descriptions
- Both calls succeed with their respective rate values (100.0 and 50.0)

---

## Test Suite 4: OCP Report DB Accessor

**File**: [`koku/masu/test/database/test_ocp_report_db_accessor.py`](../../koku/masu/test/database/test_ocp_report_db_accessor.py)
**Base class**: `MasuTestCase`
**Requirement coverage**: R2, R4, R5, R6, R7, R8, R9

### TS4-01: `populate_usage_costs` writes `cost_breakdown_source` to daily summary rows

**Business outcome**: After applying a usage rate, every inserted cost row carries the rate description, making it queryable for the Sankey breakdown.

**Prerequisites**:
- `cost_breakdown_source` column exists on `OCPUsageLineItemDailySummary` (migration applied)
- `usage_costs.sql` has been modified to include `cost_breakdown_source` in INSERT/SELECT
- `populate_usage_costs` accepts a `cost_breakdown_source` parameter
- `MasuTestCase` fixtures provide OCP usage data with at least 1 pod/node in the test schema

**Setup**: Create test OCP usage data. Call `populate_usage_costs` with `cost_type="Infrastructure"`, CPU rate = 5.0, `cost_breakdown_source="JBoss subscription"`.

**Assertions**:
- `OCPUsageLineItemDailySummary.objects.filter(cost_model_rate_type="Infrastructure", cost_breakdown_source="JBoss subscription").exists()` is `True`
- The `cost_model_cpu_cost` on those rows is non-zero and matches expected value based on usage * rate

**Exit criteria**:
- At least 1 row exists with `cost_breakdown_source="JBoss subscription"`
- All inserted rows for this call have the same `cost_breakdown_source` value
- `cost_model_cpu_cost` is calculated as `usage * 5.0` (deterministic based on fixture data)

### TS4-02: Two separate `populate_usage_costs` calls produce distinct rows per description

**Business outcome**: When a customer has two CPU rates with different descriptions, both appear as separate rows in the database (not merged).

**Prerequisites**:
- Same as TS4-01
- `usage_costs.sql` DELETE has been extracted to a separate call (INSERT-only mode)

**Setup**: Create test OCP usage data. Call `populate_usage_costs` twice:
1. CPU Infra rate 5.0, `cost_breakdown_source="JBoss subscription"`
2. CPU Infra rate 3.0, `cost_breakdown_source="RHEL license"`

**Assertions**:
- Rows with `cost_breakdown_source="JBoss subscription"` exist with `cost_model_cpu_cost` based on rate 5.0
- Rows with `cost_breakdown_source="RHEL license"` exist with `cost_model_cpu_cost` based on rate 3.0
- These are distinct rows (not summed into one)

**Exit criteria**:
- The total row count for `cost_model_rate_type="Infrastructure"` is 2x the number of (namespace, node, date) groups (one set per rate)
- Each `cost_breakdown_source` value has its own row set with its own cost value
- The second call's INSERT did not overwrite the first call's rows

### TS4-03: `delete_usage_costs` removes all rows for a cost_type in date range

**Business outcome**: Before re-applying rates, stale cost rows are cleanly removed regardless of their `cost_breakdown_source` value.

**Prerequisites**:
- `OCPReportDBAccessor.delete_usage_costs` method is implemented
- Pre-existing usage cost rows with `cost_model_rate_type="Infrastructure"` and various `cost_breakdown_source` values are present in the test schema

**Setup**: Insert usage cost rows with `cost_model_rate_type="Infrastructure"` and two different `cost_breakdown_source` values. Call `delete_usage_costs(cost_type="Infrastructure", ...)`.

**Assertions**:
- `OCPUsageLineItemDailySummary.objects.filter(cost_model_rate_type="Infrastructure", cost_breakdown_source__isnull=False, usage_start__gte=start_date, usage_start__lte=end_date).count()` is 0
- Supplementary rows are untouched

**Exit criteria**:
- All Infrastructure usage cost rows within the date range are deleted (regardless of `cost_breakdown_source` value)
- Supplementary rows with `cost_breakdown_source` remain intact (count unchanged)
- Rows outside the date range are not affected

### TS4-04: `populate_monthly_cost_sql` writes `cost_breakdown_source` for node monthly cost

**Business outcome**: Monthly fixed costs (e.g., node license fees) are tagged with their description in the database.

**Prerequisites**:
- `cost_breakdown_source` column exists on `OCPUsageLineItemDailySummary`
- `monthly_cost_cluster_and_node.sql` includes `cost_breakdown_source` in INSERT/SELECT
- `populate_monthly_cost_sql` accepts a `cost_breakdown_source` parameter
- An OCP report period with at least 1 node exists in the test schema

**Setup**: Create test OCP report period with nodes. Call `populate_monthly_cost_sql` with `cost_type="Node"`, `rate_type="Infrastructure"`, rate = 100.0, `cost_breakdown_source="Node monthly license"`.

**Assertions**:
- Rows with `monthly_cost_type="Node"` and `cost_breakdown_source="Node monthly license"` exist
- The `cost_model_cpu_cost` (or appropriate cost column) matches the amortized daily value of $100/month

**Exit criteria**:
- Monthly cost rows are tagged with `cost_breakdown_source="Node monthly license"`
- The amortized daily value is mathematically correct ($100 / days_in_month)
- `cost_model_rate_type` is set to "Infrastructure"

### TS4-05: `populate_tag_usage_costs` writes `cost_breakdown_source` with tag-value description

**Business outcome**: Tag-based costs carry the description from the tag value definition.

**Prerequisites**:
- `cost_breakdown_source` column exists on `OCPUsageLineItemDailySummary`
- `infrastructure_tag_rates.sql` includes `cost_breakdown_source` in INSERT/SELECT
- `populate_tag_usage_costs` accepts a `cost_breakdown_source` parameter
- OCP usage data exists with pod labels containing `{"environment": "production"}`

**Setup**: Create test OCP usage data with pod labels `{"environment": "production"}`. Call `populate_tag_usage_costs` with infrastructure rates for tag_key "environment", tag_value "production" at rate 10.0, `cost_breakdown_source="Production environment"`.

**Assertions**:
- Rows matching the tag filter have `cost_breakdown_source="Production environment"`
- Cost values are non-zero and consistent with usage * 10.0

**Exit criteria**:
- All tag-rate cost rows for matching pods have `cost_breakdown_source="Production environment"`
- Cost calculation is correct (usage * 10.0)
- Non-matching pods (without the "environment: production" label) have no tag-rate rows inserted

### TS4-06: `populate_markup_cost` does NOT overwrite `cost_breakdown_source`

**Business outcome**: Applying markup preserves the original rate description on each row; markup is tracked separately via the `infrastructure_markup_cost` column.

**Prerequisites**:
- Usage cost rows exist with `cost_breakdown_source="JBoss subscription"` and known `infrastructure_raw_cost` values
- `populate_markup_cost` has NOT been modified to touch `cost_breakdown_source`

**Setup**: Insert usage cost rows with `cost_breakdown_source="JBoss subscription"` and known `infrastructure_raw_cost`. Call `populate_markup_cost(markup=Decimal("0.10"), ...)`.

**Assertions**:
- Rows still have `cost_breakdown_source="JBoss subscription"` (not overwritten)
- `infrastructure_markup_cost` is set to `infrastructure_raw_cost * 0.10`

**Exit criteria**:
- `cost_breakdown_source` is identical before and after the `populate_markup_cost` call
- `infrastructure_markup_cost` is correctly computed as 10% of `infrastructure_raw_cost`
- No new rows were inserted (markup is UPDATE-only)

### TS4-07: `populate_usage_costs` preserves existing `cost.*` fields (backward compatibility)

**Business outcome**: The new `cost_breakdown_source` column is populated without breaking the existing cost column values that the current API depends on.

**Prerequisites**:
- `usage_costs.sql` has been modified to include `cost_breakdown_source` without altering existing column calculations
- OCP usage data exists in the test schema

**Setup**: Call `populate_usage_costs` with known rates. Query the resulting rows.

**Assertions**:
- `cost_model_cpu_cost`, `cost_model_memory_cost`, `cost_model_volume_cost` are populated correctly (same calculation as before the feature)
- `cost_model_rate_type` is set correctly ("Infrastructure" or "Supplementary")
- `cost_breakdown_source` is additionally set

**Exit criteria**:
- Existing cost columns produce the same values as the pre-feature implementation would
- `cost_model_rate_type` categorical value is unchanged
- `cost_breakdown_source` is a new non-null field on these rows
- No existing columns are missing or zeroed out

### TS4-08: `populate_distributed_cost_sql` qualifies `cost_breakdown_source` with distribution type

**Business outcome**: When platform costs are distributed to projects, each distributed row shows both the original rate and the distribution type (e.g., "JBoss subscription [platform]").

**Prerequisites**:
- `distribute_platform_cost.sql` has been modified to carry `cost_breakdown_source` with CONCAT qualifier
- Source (platform) namespace rows exist with `cost_breakdown_source="JBoss subscription"` and non-zero costs
- At least 1 user project namespace exists to receive distributed costs
- Distribution configuration has platform distribution enabled

**Setup**: Insert source namespace rows with `cost_breakdown_source="JBoss subscription"` in the platform namespace. Call `populate_distributed_cost_sql` for platform distribution.

**Assertions**:
- Distributed rows in user project namespaces have `cost_breakdown_source="JBoss subscription [platform]"`
- The `distributed_cost` value is proportional to the source rate's cost

**Exit criteria**:
- All distributed rows have the format `"<original description> [platform]"`
- The `[platform]` qualifier is appended (not replacing the original description)
- `distributed_cost` is proportional to the source cost and the project's usage share

### TS4-09: Distributed costs with multiple source descriptions produce multiple distributed rows per project

**Business outcome**: A project receiving distributed overhead from a platform namespace that has costs from 2 different rates gets 2 separate distributed rows (not one merged row).

**Prerequisites**:
- `distribute_platform_cost.sql` includes `cost_breakdown_source` in GROUP BY
- Platform namespace has rows with 2 distinct `cost_breakdown_source` values
- At least 1 user project namespace exists

**Setup**: Insert platform namespace rows with:
- `cost_breakdown_source="JBoss subscription"`, cost = $30
- `cost_breakdown_source="RHEL license"`, cost = $20

Call `populate_distributed_cost_sql` for platform distribution to a project that gets 50%.

**Assertions**:
- Project has distributed row: `cost_breakdown_source="JBoss subscription [platform]"`, `distributed_cost ≈ 15.0`
- Project has distributed row: `cost_breakdown_source="RHEL license [platform]"`, `distributed_cost ≈ 10.0`

**Exit criteria**:
- The project receives exactly 2 distributed rows (one per source description)
- Costs are split proportionally per source description (not aggregated then split)
- Sum of distributed rows ($15 + $10 = $25) equals 50% of total platform cost ($50)

### TS4-10: Unattributed storage distribution uses fixed description

**Business outcome**: Unattributed storage costs (which have no user-defined rate origin) use the standardized label "Storage unattributed" for the Sankey.

**Prerequisites**:
- `distribute_unattributed_storage_cost.sql` sets `cost_breakdown_source` to `"Storage unattributed"`
- Unattributed storage costs exist in the test schema
- Distribution configuration has storage unattributed distribution enabled

**Setup**: Call `populate_distributed_cost_sql` for unattributed storage distribution.

**Assertions**:
- Distributed rows have `cost_breakdown_source="Storage unattributed"`

**Exit criteria**:
- All storage-unattributed distributed rows have the exact string `"Storage unattributed"` (not qualified with `[storage]`)
- The label is hardcoded, not derived from any rate description

### TS4-11: Unattributed network distribution uses fixed description

**Business outcome**: Same as TS4-10 but for network.

**Prerequisites**:
- `distribute_unattributed_network_cost.sql` sets `cost_breakdown_source` to `"Network unattributed"`
- Unattributed network costs exist in the test schema
- Distribution configuration has network unattributed distribution enabled

**Setup**: Call `populate_distributed_cost_sql` for unattributed network distribution.

**Assertions**:
- Distributed rows have `cost_breakdown_source="Network unattributed"`

**Exit criteria**:
- All network-unattributed distributed rows have the exact string `"Network unattributed"`
- The label is hardcoded, not derived from any rate description

---

## Test Suite 5: API Query Handler

**File**: [`koku/api/report/test/ocp/test_ocp_query_handler.py`](../../koku/api/report/test/ocp/test_ocp_query_handler.py)
**Base class**: `IamTestCase`
**Requirement coverage**: R3, R8, R9, R10, AD-4

### TS5-01: `cost_breakdown` field present in costs_by_project response

**Business outcome**: The API response includes the new `cost_breakdown` list alongside the existing `cost` object.

**Prerequisites**:
- `cost_breakdown` annotation is added to `provider_map.py` for the `costs_by_project` report type
- Query handler passes `cost_breakdown` through to the response
- `IamTestCase` fixtures provide OCP data with a cost model applied
- UI summary tables have been populated with `cost_breakdown_source`

**Setup**: Standard OCP test data with cost model applied. Query the costs_by_project endpoint.

**Assertions**:
- `assertIn("cost_breakdown", values)` for each values entry in the response data
- `assertIsInstance(values["cost_breakdown"], list)`

**Exit criteria**:
- Every `values` entry in the response contains a `cost_breakdown` key
- `cost_breakdown` is a list (not a dict, string, or null)

### TS5-02: `cost_breakdown` entries have correct structure

**Business outcome**: Each entry in `cost_breakdown` contains the `source`, `value`, and `units` keys the frontend needs.

**Prerequisites**:
- Same as TS5-01
- At least 1 cost model rate has been applied, producing at least 1 `cost_breakdown` entry

**Setup**: Same as TS5-01.

**Assertions**:
- For each entry in `cost_breakdown`:
  - `assertIn("source", entry)`
  - `assertIn("value", entry)`
  - `assertIn("units", entry)`
  - `assertEqual(entry["units"], "USD")`

**Exit criteria**:
- Every entry in the list has exactly the 3 required keys: `source`, `value`, `units`
- `source` is a non-empty string
- `value` is a numeric type (Decimal or float)
- `units` is `"USD"` (matching the cost model's currency)

### TS5-03: `cost_breakdown` contains distinct sources matching rate descriptions

**Business outcome**: The Sankey diagram receives the actual rate descriptions from the customer's cost model.

**Prerequisites**:
- Cost model with `MULTI_RATE_COST_MODEL_RATES` has been applied to the OCP data
- Usage costs, monthly costs have been computed and stored with `cost_breakdown_source`
- UI summary tables have been refreshed

**Setup**: Apply cost model with `MULTI_RATE_COST_MODEL_RATES` to OCP data. Query costs_by_project.

**Assertions**:
- Sources in `cost_breakdown` include `"JBoss subscription"`, `"Guest OS subscription (RHEL)"`, `"Quota charge"`
- Each source appears exactly once (values are summed per source)

**Exit criteria**:
- The `cost_breakdown` sources are customer-meaningful descriptions (not metric names or internal identifiers)
- No duplicate source strings (aggregation groups by source correctly)
- At least the 3 usage-rate descriptions appear

### TS5-04: `cost_breakdown` includes synthetic "Markup" entry

**Business outcome**: The Sankey shows a "Markup" line item computed from the markup percentage applied to infrastructure costs.

**Prerequisites**:
- Cost model has markup configured (e.g., 10%)
- `populate_markup_cost` has been called, setting `infrastructure_markup_cost` on existing rows
- The query handler or provider_map computes the synthetic "Markup" entry from `infrastructure_markup_cost`

**Setup**: Apply cost model with markup = 10%. Insert infrastructure costs. Query costs_by_project.

**Assertions**:
- One entry with `source == "Markup"` exists in `cost_breakdown`
- Its `value` equals the sum of `infrastructure_markup_cost` across all matching rows
- `assertAlmostEqual(markup_entry["value"], expected_markup_total, places=6)`

**Exit criteria**:
- Exactly 1 "Markup" entry exists (not one per rate or per row)
- The Markup value is the sum of all `infrastructure_markup_cost` values (not a re-computation)
- The value matches `cost["markup"]["value"]` from the existing `cost` object

### TS5-05: `cost_breakdown` values sum equals `cost.total`

**Business outcome**: Mathematical consistency — the sum of all `cost_breakdown` values equals the total cost, ensuring the Sankey diagram balances.

**Prerequisites**:
- All cost types are applied: usage rates, monthly rates, markup, distributed costs
- `cost_breakdown` includes entries from all cost types plus the synthetic Markup entry

**Setup**: Apply full cost model with usage rates, monthly rates, and markup. Query costs_by_project.

**Assertions**:
- `sum(entry["value"] for entry in cost_breakdown)` ≈ `cost["total"]["value"]` (within rounding tolerance)
- Use `assertAlmostEqual` with `places=2`

**Exit criteria**:
- The sum of `cost_breakdown` values equals `cost.total` within $0.01 tolerance
- No cost dollars are "lost" or "created" by the breakdown — the Sankey balances

### TS5-06: Existing `cost` object fields are unchanged (backward compatibility)

**Business outcome**: Existing frontend consumers that rely on `cost.raw`, `cost.usage`, `cost.markup`, `cost.total` continue to work identically.

**Prerequisites**:
- The `cost` annotation in `provider_map.py` has NOT been modified
- All existing cost columns and aggregation logic are preserved

**Setup**: Same data as TS5-05.

**Assertions**:
- `assertIn("raw", cost)`
- `assertIn("usage", cost)`
- `assertIn("markup", cost)`
- `assertIn("total", cost)`
- Cost values match the same DB aggregation as before the feature (compare against `OCPUsageLineItemDailySummary` aggregate)

**Exit criteria**:
- All pre-existing `cost.*` fields are present with correct values
- `cost.total.value` matches the DB aggregate of all cost columns
- No existing fields are renamed, removed, or have changed values

### TS5-07: `cost_breakdown` in `total` section sums across all projects

**Business outcome**: The "total" row in the API response aggregates `cost_breakdown` values across all projects, so the Sankey at the account level shows the full picture.

**Prerequisites**:
- OCP data exists for at least 2 projects with cost model applied
- The query handler aggregates `cost_breakdown` across all projects in the `total` section

**Setup**: OCP data spanning 2+ projects with cost model applied. Query costs_by_project.

**Assertions**:
- `total` section contains `cost_breakdown`
- For each unique source, the total value equals the sum of that source's values across all project-level entries

**Exit criteria**:
- `total.cost_breakdown` contains all unique sources that appear in any project's breakdown
- For each source: `total_value == sum(project_values)` across all projects
- No source is missing from the total that appears in individual projects

### TS5-08: `cost_breakdown` includes distributed cost entries with qualifiers

**Business outcome**: Distributed overhead costs appear in the Sankey with their distribution type qualifier, enabling Level 2 drill-down.

**Prerequisites**:
- Platform distribution is enabled in the distribution configuration
- Platform namespace has costs with `cost_breakdown_source` set
- `distribute_platform_cost.sql` qualifies sources with `" [platform]"`
- UI summary tables have been refreshed after distribution

**Setup**: OCP data with platform distribution enabled. Apply multi-rate cost model. Query costs_by_project.

**Assertions**:
- `cost_breakdown` contains entries ending with `" [platform]"` (e.g., `"JBoss subscription [platform]"`)
- Sum of all `[platform]` entries ≈ `cost["platform_distributed"]["value"]`

**Exit criteria**:
- At least 1 entry with `" [platform]"` suffix exists in `cost_breakdown`
- The sum of all `[platform]` entries matches `cost.platform_distributed.value` within $0.01
- Level 2 (per-rate distributed) is mathematically consistent with Level 1 (aggregated overhead)

### TS5-09: `cost_breakdown` includes distributed cost entries with worker qualifier

**Business outcome**: Worker-distributed overhead shows the correct qualifier.

**Prerequisites**:
- Worker unallocated distribution is enabled in the distribution configuration
- Worker namespace has costs with `cost_breakdown_source` set
- `distribute_worker_cost.sql` qualifies sources with `" [worker]"`
- UI summary tables have been refreshed after distribution

**Setup**: OCP data with worker unallocated distribution enabled. Apply multi-rate cost model. Query costs_by_project.

**Assertions**:
- `cost_breakdown` contains entries ending with `" [worker]"` (e.g., `"JBoss subscription [worker]"`)
- Sum of all `[worker]` entries ≈ `cost["worker_unallocated_distributed"]["value"]`

**Exit criteria**:
- At least 1 entry with `" [worker]"` suffix exists in `cost_breakdown`
- The sum of all `[worker]` entries matches `cost.worker_unallocated_distributed.value` within $0.01

### TS5-10: `cost_breakdown` appears in costs report (not just costs_by_project)

**Business outcome**: The Sankey breakdown is available in the overall costs report view.

**Prerequisites**:
- `cost_breakdown` annotation is added to `provider_map.py` for the `costs` report type
- `reporting_ocp_cost_summary_p` summary table includes `cost_breakdown_source`

**Setup**: Standard OCP test data. Query the `costs` endpoint.

**Assertions**:
- `assertIn("cost_breakdown", values)` for total values

**Exit criteria**:
- The `costs` report type includes `cost_breakdown` in its response structure
- The field structure matches that of `costs_by_project` (same keys: `source`, `value`, `units`)

### TS5-11: `cost_breakdown` appears in costs_by_node report

**Business outcome**: The breakdown is available when grouping by node.

**Prerequisites**:
- `cost_breakdown` annotation is added to `provider_map.py` for the `costs_by_node` report type
- `reporting_ocp_cost_summary_by_node_p` summary table includes `cost_breakdown_source`

**Setup**: Standard OCP test data. Query the `costs_by_node` endpoint.

**Assertions**:
- `assertIn("cost_breakdown", values)` for each node entry

**Exit criteria**:
- Each node entry in the response includes a `cost_breakdown` list
- The field structure matches that of other report types

### TS5-12: Two rates for the same metric appear as separate `cost_breakdown` entries

**Business outcome**: When a customer has two CPU rates (e.g., "JBoss subscription" and "Quota charge"), both appear individually in the Sankey — they are not merged.

**Prerequisites**:
- Cost model has 2 CPU rates with different cost_types and different descriptions
- Per-rate execution produces separate rows with distinct `cost_breakdown_source` values
- The `ArrayAgg` annotation groups by `cost_breakdown_source`, preserving both entries

**Setup**: Apply cost model with 2 CPU rates (different cost_types, different descriptions). Query costs_by_project.

**Assertions**:
- `cost_breakdown` contains separate entries for "JBoss subscription" and "Quota charge"
- Their values are different (based on their respective rate amounts)

**Exit criteria**:
- Both rate descriptions appear as distinct entries in `cost_breakdown`
- Values reflect the individual rate amounts (not the sum of both)
- The API aggregation did not merge them by metric name

---

## Test Suite 6: API View Integration

**File**: [`koku/api/report/test/ocp/view/test_views.py`](../../koku/api/report/test/ocp/view/test_views.py)
**Base class**: `IamTestCase`
**Requirement coverage**: R3, R8, R9, AD-4

### TS6-01: Costs endpoint returns `cost_breakdown` in HTTP 200 response

**Business outcome**: The full API endpoint returns the `cost_breakdown` field when queried.

**Prerequisites**:
- All implementation layers are complete (schema, accessor, updater, SQL, API)
- `IamTestCase` fixtures provide OCP data with a cost model and computed costs
- The Django test server is running and the `reports-openshift-costs` URL route exists

**Setup**: Standard OCP data with cost model. `APIClient().get(reverse("reports-openshift-costs"), **self.headers)`.

**Assertions**:
- `assertEqual(response.status_code, 200)`
- `cost_breakdown` present in response JSON `data[*].values[*]`

**Exit criteria**:
- HTTP 200 response is returned (no server error)
- The JSON response body contains `cost_breakdown` in the expected location within the data structure
- The response is parseable as valid JSON

### TS6-02: Costs by project endpoint returns `cost_breakdown` with per-project data

**Business outcome**: Each project in the grouped response has its own breakdown reflecting the rates applied to that project's usage.

**Prerequisites**:
- All implementation layers are complete
- OCP data spans at least 2 distinct namespaces (projects)
- Cost model with `MULTI_RATE_COST_MODEL_RATES` is applied

**Setup**: OCP data with 2+ projects and cost model. `APIClient().get(reverse("reports-openshift-costs") + "?group_by[project]=*", **self.headers)`.

**Assertions**:
- `assertEqual(response.status_code, 200)`
- Each project entry has `cost_breakdown` list with at least 1 entry
- Sources in `cost_breakdown` match the rate descriptions from the cost model

**Exit criteria**:
- HTTP 200 with valid JSON
- Each project's `cost_breakdown` is independently populated (not a copy of the total)
- Sources are customer-meaningful descriptions from the cost model (not internal identifiers)
- At least 2 projects have `cost_breakdown` entries

### TS6-03: Costs by node endpoint returns `cost_breakdown`

**Business outcome**: Node-grouped reports include the breakdown.

**Prerequisites**:
- `cost_breakdown` annotation is added to `provider_map.py` for `costs_by_node` report type
- OCP data has at least 1 node with cost model applied

**Setup**: OCP data with cost model. `APIClient().get(reverse("reports-openshift-costs") + "?group_by[node]=*", **self.headers)`.

**Assertions**:
- `assertEqual(response.status_code, 200)`
- Each node entry has `cost_breakdown` with valid structure

**Exit criteria**:
- HTTP 200 with valid JSON
- Each node entry contains `cost_breakdown` list with entries having `source`, `value`, `units`

### TS6-04: Existing cost fields in response unchanged after feature

**Business outcome**: No regression — the existing `cost` object with `raw`, `usage`, `markup`, `total`, and overhead fields is identical to pre-feature values.

**Prerequisites**:
- The `cost` object annotations in `provider_map.py` are unchanged
- A known cost model and OCP data exist allowing deterministic expected values
- The expected `cost.total` is pre-computed from the DB aggregate

**Setup**: OCP data with cost model. Query costs endpoint. Compare `cost` object to expected DB aggregation.

**Assertions**:
- `assertIn("raw", cost)` with `value` and `units`
- `assertIn("markup", cost)` with `value` and `units`
- `assertIn("total", cost)` with `value` and `units`
- `assertAlmostEqual(cost["total"]["value"], expected_total, 6)`

**Exit criteria**:
- All pre-existing `cost` keys are present (`raw`, `usage`, `markup`, `total`, plus overhead fields)
- `cost.total.value` matches the expected DB aggregate within 6 decimal places
- No new, renamed, or missing keys in the `cost` object compared to pre-feature behavior

### TS6-05: `cost_breakdown` "Markup" value matches `cost.markup` value

**Business outcome**: The synthetic Markup entry in the breakdown is mathematically consistent with the existing markup field — they show the same dollar amount.

**Prerequisites**:
- Cost model has markup configured (non-zero percentage)
- `populate_markup_cost` has been called, setting `infrastructure_markup_cost`
- The query handler appends the synthetic "Markup" entry from `infrastructure_markup_cost`

**Setup**: OCP data with cost model and markup. Query costs_by_project endpoint.

**Assertions**:
- Find entry in `cost_breakdown` where `source == "Markup"`
- `assertAlmostEqual(markup_entry["value"], cost["markup"]["value"], places=6)`

**Exit criteria**:
- The "Markup" entry exists in `cost_breakdown`
- Its value matches `cost.markup.value` within 6 decimal places
- This proves the synthetic entry is correctly derived from the same underlying data as the existing field

### TS6-06: `cost_breakdown` platform entries sum matches `cost.platform_distributed`

**Business outcome**: Level 2 drill-down is mathematically consistent with Level 1 — platform distributed entries sum to the same value.

**Prerequisites**:
- Platform distribution is enabled
- Platform namespace has costs with `cost_breakdown_source` that are distributed to user projects
- The response includes both `cost.platform_distributed` (Level 1) and `cost_breakdown` with `[platform]` entries (Level 2)

**Setup**: OCP data with platform distribution and cost model. Query costs_by_project.

**Assertions**:
- Sum all entries where `source` ends with `" [platform]"`
- `assertAlmostEqual(platform_sum, cost["platform_distributed"]["value"], places=2)`

**Exit criteria**:
- The sum of all `[platform]`-suffixed `cost_breakdown` entries equals `cost.platform_distributed.value` within $0.01
- This proves Level 1 and Level 2 are mathematically consistent
- The customer can drill down from the aggregated overhead total to individual rate contributions

---

## Requirements Traceability Matrix

| Requirement | Test Scenarios | Description |
|-------------|---------------|-------------|
| R1 — Rate description mandatory | TS1-01, TS1-02, TS1-03, TS1-04 | Serializer validates description is required and non-blank |
| R2 — Per-rate cost tracking | TS2-01, TS2-02, TS3-01, TS4-01, TS4-02 | Each rate produces separate DB entry with description |
| R3 — API cost breakdown field | TS5-01, TS5-02, TS6-01, TS6-02, TS6-03 | `cost_breakdown` list present in API response |
| R4 — Usage rates broken out | TS2-01, TS3-01, TS3-03, TS4-01, TS4-02 | Usage rates individually tracked and inserted |
| R5 — Monthly costs broken out | TS3-04, TS3-07, TS4-04 | Monthly costs carry description |
| R6 — Tag rates broken out | TS2-05, TS2-06, TS2-07, TS3-05, TS4-05 | Tag rates carry 3-tier description fallback |
| R7 — Distributed costs broken out | TS4-08, TS4-09, TS4-10, TS4-11, TS5-08, TS5-09 | Distributed costs qualified with type |
| R8 — Markup as API-level aggregate | TS4-06, TS5-04, TS6-05 | Markup computed at API layer, not DB column |
| R9 — Backward compatibility | TS2-04, TS4-07, TS5-06, TS6-04 | Existing fields/values unchanged |
| R10 — Individual rate breakout | TS2-02, TS3-01, TS5-12 | Duplicate metrics stay separate |

### Coverage Summary

| Test Suite | File | Scenarios | New/Modified Methods Covered |
|------------|------|-----------|------------------------------|
| TS1 | `test_serializers.py` | 4 | `RateSerializer.validate` (description required) |
| TS2 | `test_cost_model_db_accessor.py` | 7 | `itemized_rates`, `tag_based_price_list` (description), `tag_infrastructure_rates` (description), `price_list` (backward compat) |
| TS3 | `test_ocp_cost_model_cost_updater.py` | 7 | `_update_usage_costs` (per-rate), `_update_monthly_cost` (description), `_update_tag_usage_costs` (description), `delete_usage_costs` call ordering |
| TS4 | `test_ocp_report_db_accessor.py` | 11 | `populate_usage_costs` (+source), `delete_usage_costs`, `populate_monthly_cost_sql` (+source), `populate_tag_usage_costs` (+source), `populate_markup_cost` (no overwrite), `populate_distributed_cost_sql` (qualifier) |
| TS5 | `test_ocp_query_handler.py` | 12 | `cost_breakdown` annotation, synthetic Markup, total aggregation, report type coverage |
| TS6 | `test_views.py` | 6 | HTTP endpoint integration, response structure, mathematical consistency |
| **Total** | | **47** | |

### Estimated Coverage

| Layer | Methods/Code Paths | Covered by Tests | Est. Coverage |
|-------|--------------------|-----------------|---------------|
| Serializer | `RateSerializer` validation | TS1-01..04 | ~90% |
| Accessor (`itemized_rates`) | new property + fallback | TS2-01..04 | ~85% |
| Accessor (tag description) | `tag_based_price_list` + derivatives | TS2-05..07 | ~75% |
| Updater (usage) | `_update_usage_costs` rewrite | TS3-01..03, TS3-06 | ~85% |
| Updater (monthly) | `_update_monthly_cost` + description | TS3-04, TS3-07 | ~80% |
| Updater (tags) | `_update_tag_usage_costs` + description | TS3-05 | ~70% |
| DB Accessor (usage) | `populate_usage_costs` + `delete_usage_costs` | TS4-01..03, TS4-07 | ~85% |
| DB Accessor (monthly) | `populate_monthly_cost_sql` + source | TS4-04 | ~75% |
| DB Accessor (tags) | `populate_tag_usage_costs` + source | TS4-05 | ~70% |
| DB Accessor (markup) | `populate_markup_cost` no overwrite | TS4-06 | ~80% |
| DB Accessor (distribute) | `populate_distributed_cost_sql` + qualifier | TS4-08..11 | ~80% |
| API (query handler) | annotations + synthetic Markup | TS5-01..12 | ~80% |
| API (views) | endpoint integration | TS6-01..06 | ~75% |
| **Weighted Average** | | | **~79%** |

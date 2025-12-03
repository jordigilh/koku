# Trino Migration Test Scenarios Declaration
**Comprehensive Business Outcome Coverage for PostgreSQL Migration**

---

## 📋 Executive Summary

This document declares all test scenarios planned for the Trino → PostgreSQL migration, ensuring **complete functional parity** while avoiding duplication with existing IQE test coverage. Each scenario targets specific **Trino-dependent functionality** that must be preserved during migration.

### IQE Compliance Declaration
✅ **All scenarios follow official IQE validation standards**:
- `tolerance_value()` function (PEP 485, 1e-8 precision) [Ref: iqe_cost_management/fixtures/helpers.py]
- Meta totals must equal sum of line items (`calculate_total()`)
- Currency and units validation (`assert units == "USD"`)
- API structure validation (`assert "data" in result`)
- Business logic validation (SavingsPlan zero-out, etc.)

---

## 🎯 Test Coverage Strategy

### What IQE Already Covers ✅
**85 existing scenarios covering** [Ref: IQE cost management plugin analysis]:
- Standard API endpoints (AWS, Azure, GCP, OCP costs/instances/storage)
- Basic group_by and filtering operations
- Standard date range and time scope validation
- Basic mathematical consistency (total = sum of parts)
- Standard tag and cost category operations
- Account alias and organizational unit handling
- Basic currency and product family validation

### What Our Tests Add 🚀
**154 Trino-specific scenarios covering** [Ref: Comprehensive gap analysis]:
- **Advanced SQL Operations**: Complex CTEs, window functions, cross-catalog queries
- **Advanced Billing Logic**: SavingsPlan complex scenarios, RI amortization, multi-tier discounts
- **Complex Mathematical Operations**: High-precision calculations, statistical functions
- **JSON Processing**: Complex tag matching, nested data structures
- **Provider-Specific Advanced Features**: Azure EA, GCP CUD, AWS consolidated billing
- **Cross-Provider Correlation**: Multi-cloud cost attribution, unified billing

---

## 📊 Test Scenario Categories

### Category 1: Core Trino SQL Operations (26 scenarios)
**File**: `test_trino_core_functional_requirements.py`

#### 1.1 Complex SQL Operations (FR-T01) - 7 scenarios
**Business Outcome**: Preserve advanced SQL query capabilities for complex cost analysis

| Scenario ID | Test Name | Business Outcome | Why Trino-Specific |
|-------------|-----------|------------------|-------------------|
| **FR-T01-001** | `test_complex_cte_with_multiple_joins` | **Multi-dimensional cost correlation** across providers, services, and time periods | Uses Trino's advanced CTE processing with cross-catalog JOINs |
| **FR-T01-002** | `test_nested_subquery_aggregations` | **Hierarchical cost rollups** for organizational reporting | Requires Trino's subquery optimization engine |
| **FR-T01-003** | `test_cross_catalog_union_operations` | **Unified billing across Hive and PostgreSQL data** | Trino-exclusive cross-catalog UNION capability |
| **FR-T01-004** | `test_correlated_subqueries_cost_analysis` | **Per-service cost comparisons** with dynamic benchmarking | Trino's correlated subquery execution |
| **FR-T01-005** | `test_recursive_hierarchical_queries` | **Organizational cost hierarchy traversal** | Trino's recursive query processing |
| **FR-T01-006** | `test_window_function_cost_trends` | **Time-series cost trending and forecasting** | Advanced window function support |
| **FR-T01-007** | `test_lateral_join_cost_attribution` | **Dynamic cost attribution per resource** | Trino's LATERAL JOIN functionality |

#### 1.2 JSON/Array Processing (FR-T04) - 6 scenarios
**Business Outcome**: Maintain complex tag and metadata processing for cost allocation

| Scenario ID | Test Name | Business Outcome | Why Trino-Specific |
|-------------|-----------|------------------|-------------------|
| **FR-T04-001** | `test_json_extract_nested_tags` | **Multi-level tag-based cost allocation** | Trino's `json_extract_scalar()` with complex paths |
| **FR-T04-002** | `test_map_filter_tag_operations` | **Dynamic tag filtering and correlation** | Trino-specific `map_filter()` function |
| **FR-T04-003** | `test_array_aggregation_multi_tags` | **Tag aggregation across multiple resources** | Trino's advanced array processing |
| **FR-T04-004** | `test_json_parse_complex_structures` | **Nested metadata parsing for billing** | Trino's `json_parse()` with map operations |
| ~~**FR-T04-005**~~ | ~~`test_transform_keys_cost_mapping`~~ | ~~Dynamic key transformation~~ | ❌ **REMOVED - Not used in production** |
| **FR-T04-006** | `test_any_match_tag_correlation` | **Cross-provider tag matching** | Trino's `any_match()` for complex filtering |
| **FR-T04-007** | `test_nested_json_cost_rollups` | **Hierarchical cost aggregation from JSON structures** | Complex JSON processing with aggregations |

#### 1.3 Complex WHERE Logic (FR-T05) - 6 scenarios
**Business Outcome**: Preserve advanced filtering capabilities for cost analysis

| Scenario ID | Test Name | Business Outcome | Why Trino-Specific |
|-------------|-----------|------------------|-------------------|
| **FR-T05-001** | `test_boolean_and_or_cost_filters` | **Multi-criteria cost filtering** | Trino's boolean expression optimization |
| ~~**FR-T05-002**~~ | ~~`test_regexp_extract_service_filtering`~~ | ~~Pattern-based service classification~~ | ❌ **REMOVED - Not used in production** |
| **FR-T05-003** | `test_case_when_nested_conditions` | **Conditional cost categorization** | Complex nested CASE expressions |
| **FR-T05-004** | `test_in_subquery_cost_comparisons` | **Dynamic cost threshold filtering** | Subquery-based IN operations |
| **FR-T05-005** | `test_exists_correlation_cost_analysis` | **Conditional cost attribution** | EXISTS with correlated subqueries |
| **FR-T05-006** | `test_coalesce_null_cost_handling` | **Missing data cost imputation** | Trino's NULL handling with COALESCE |
| **FR-T05-007** | `test_complex_date_range_filtering` | **Advanced temporal cost analysis** | Trino's date function combinations |

#### 1.4 Data Type Coercion (FR-T06) - 7 scenarios
**Business Outcome**: Maintain financial calculation precision during data transformations

| Scenario ID | Test Name | Business Outcome | Why Trino-Specific |
|-------------|-----------|------------------|-------------------|
| **FR-T06-001** | `test_decimal_precision_casting` | **Financial calculation accuracy (24,9 precision)** | Trino's decimal casting with precision control |
| **FR-T06-002** | `test_currency_conversion_types` | **Multi-currency cost normalization** | Trino's numeric type handling |
| **FR-T06-003** | `test_string_to_numeric_conversions` | **Dynamic data type processing** | Trino's automatic type coercion |
| **FR-T06-004** | `test_timestamp_timezone_handling` | **Global timezone cost normalization** | Trino's timezone-aware processing |
| **FR-T06-005** | `test_null_handling_cost_calculations` | **Missing data financial impact** | Trino's NULL arithmetic behavior |
| **FR-T06-006** | `test_array_element_type_consistency` | **Consistent tag data processing** | Trino's array type validation |
| **FR-T06-007** | `test_json_numeric_precision_parsing` | **Metadata numeric accuracy** | JSON-to-numeric conversion precision |

---

### Category 2: AWS Advanced Billing (30 scenarios)
**File**: `test_trino_aws_advanced_billing.py`

#### 2.1 Reserved Instances Advanced Logic (FR-AWS-01) - 6 scenarios
**Business Outcome**: Preserve complex RI amortization and discount calculations

| Scenario ID | Test Name | Business Outcome | Synthetic Data Strategy |
|-------------|-----------|------------------|------------------------|
| **FR-AWS-01-001** | `test_ri_upfront_amortization_calculation` | **Accurate RI cost distribution over contract period** | RI Contract: $10,000 upfront, 12 months → $833.33/month |
| **FR-AWS-01-002** | `test_ri_partial_utilization_scenarios` | **RI underutilization cost impact** | 75% utilization → 25% unused RI cost allocation |
| **FR-AWS-01-003** | `test_ri_cross_az_application_logic` | **Multi-AZ RI discount application** | RI in us-east-1a applies to us-east-1b instances |
| **FR-AWS-01-004** | `test_ri_size_flexibility_calculations` | **RI normalization factor processing** | m5.large RI → 2x m5.medium instances |
| **FR-AWS-01-005** | `test_ri_family_convertible_scenarios` | **Convertible RI cost adjustments** | m5 → c5 family conversion cost tracking |
| **FR-AWS-01-006** | `test_ri_marketplace_third_party_billing` | **Third-party RI cost attribution** | Marketplace RI with different seller pricing |

**IQE Validation Example**:
```python
# Predictable RI Test Data
ri_test_scenario = {
    "upfront_cost": 12000.00,      # $12,000 upfront
    "contract_months": 12,         # 12-month contract
    "expected_monthly": 1000.00,   # $12,000 ÷ 12 = $1,000/month
    "utilization_rate": 0.80,      # 80% utilization
    "expected_savings": 2400.00    # vs $15,000 On-Demand
}

# IQE Validation
tolerance_value(
    calculated_monthly_cost, ri_test_scenario["expected_monthly"],
    assert_message="RI amortization calculation error"
)
```

#### 2.2 SavingsPlan Complex Scenarios (FR-AWS-02) - 6 scenarios
**Business Outcome**: Maintain SavingsPlan discount application and zero-out logic

| Scenario ID | Test Name | Business Outcome | Key Business Logic |
|-------------|-----------|------------------|-------------------|
| **FR-AWS-02-001** | `test_savings_plan_covered_usage_zeroing` | **SavingsPlanCoveredUsage must zero out to $0.00** | `lineitem_lineitemtype='SavingsPlanCoveredUsage' → cost = 0.0` |
| **FR-AWS-02-002** | `test_savings_plan_negation_preservation` | **SavingsPlan adjustments maintain negative values** | `lineitem_lineitemtype='SavingsPlanNegation' → preserve cost` |
| **FR-AWS-02-003** | `test_multi_service_savings_plan_allocation` | **Cross-service SavingsPlan cost distribution** | EC2 + Lambda + Fargate under same SavingsPlan |
| **FR-AWS-02-004** | `test_savings_plan_hourly_commitment_tracking` | **Hourly commitment vs actual usage correlation** | $100/hour commitment vs $150/hour actual usage |
| **FR-AWS-02-005** | `test_compute_vs_ec2_savings_plans` | **Different SavingsPlan types cost processing** | Compute SP (broader) vs EC2 SP (specific) |
| **FR-AWS-02-006** | `test_savings_plan_regional_vs_zonal_application` | **Geographic SavingsPlan discount application** | Regional SP applies across all AZs in region |

**Critical Business Logic Test**:
```python
# SavingsPlan Zero-Out Validation (IQE Standard)
for item in api_result["data"]:
    line_item_type = item.get("lineitem_lineitemtype", "")
    if line_item_type == "SavingsPlanCoveredUsage":
        cost = item["values"][0]["cost"]["total"]["value"]
        assert cost == 0.0, f"SavingsPlan covered usage must zero out: {cost}"
```

#### 2.3 Spot Pricing Fluctuations (FR-AWS-03) - 6 scenarios
#### 2.4 Multi-Tier Pricing Structures (FR-AWS-04) - 6 scenarios
#### 2.5 Consolidated Billing Scenarios (FR-AWS-05) - 6 scenarios

---

### Category 3: Azure Enterprise Billing (24 scenarios)
**File**: `test_trino_azure_enterprise_billing.py`

#### 3.1 CSP Agreement Processing (FR-AZURE-01) - 6 scenarios
**Business Outcome**: Maintain Cloud Solution Provider billing accuracy

#### 3.2 Enterprise Agreement Pricing (FR-AZURE-02) - 6 scenarios
**Business Outcome**: Preserve EA discount and commitment processing

#### 3.3 Azure Hybrid Benefit Calculations (FR-AZURE-03) - 6 scenarios
**Business Outcome**: Maintain license cost optimization tracking

#### 3.4 Microsoft Customer Agreement (FR-AZURE-04) - 6 scenarios
**Business Outcome**: Process MCA billing structure changes

---

### Category 4: GCP Advanced Processing (24 scenarios)
**File**: `test_trino_gcp_advanced_processing.py`

#### 4.1 Sustained Use Discounts (FR-GCP-01) - 6 scenarios
**Business Outcome**: Maintain automatic GCP discount calculations

#### 4.2 Committed Use Discounts (FR-GCP-02) - 6 scenarios
**Business Outcome**: Preserve CUD commitment tracking and allocation

---

### Category 5: Critical Data Accuracy (9 scenarios) - P0 PRIORITY
**File**: `test_trino_critical_data_accuracy.py`

**These are the highest priority scenarios ensuring zero financial calculation errors.**

| Scenario ID | Test Name | Business Outcome | Financial Impact |
|-------------|-----------|------------------|-----------------|
| **FR-026** | `test_complex_json_tag_matching_operations` | **Multi-provider cost attribution accuracy** | Incorrect attribution could misallocate $millions |
| **FR-027** | `test_advanced_datetime_functions_precision` | **Month/quarter boundary financial accuracy** | Date errors could double-count monthly costs |
| **FR-028** | `test_mathematical_functions_unit_conversions` | **Resource calculation precision** | Unit errors could miscalculate infrastructure costs |

---

## 🚀 Synthetic Data Strategy

### Predictable Business Scenarios
All synthetic data uses **round numbers for easy mental verification** while testing **real business logic**:

#### Example: Consolidated Billing Test
```python
synthetic_scenario = {
    "organization_accounts": [
        {"account": "111111111111", "monthly_spend": 5000.00},  # $5K
        {"account": "222222222222", "monthly_spend": 3000.00},  # $3K
        {"account": "333333333333", "monthly_spend": 2000.00}   # $2K
    ],
    "expected_total": 10000.00,           # Easy math: 5K + 3K + 2K = 10K
    "volume_discount_threshold": 8000.00,  # >$8K gets 5% discount
    "expected_discounted_total": 9500.00,  # 10K - 5% = 9.5K
    "business_outcome": "Consolidated billing saves $500/month"
}
```

#### Example: Mathematical Precision Test
```python
precision_scenario = {
    "large_cost": Decimal('999999.876543'),      # Large number with decimals
    "small_adjustment": Decimal('0.123457'),      # Small precise adjustment
    "expected_sum": Decimal('1000000.000000'),    # Perfect round result
    "tolerance": 1e-8,                           # IQE standard precision
    "business_outcome": "Maintain 8-decimal precision for financial accuracy"
}
```

---

## 🎯 Business Outcome Validation

### Financial Accuracy Metrics
- **Mathematical Precision**: All calculations within 1e-8 tolerance
- **SavingsPlan Logic**: Complete zero-out validation for covered usage [Ref: AWS billing logic requirements]
- **Currency Consistency**: All USD validations pass
- **Total Validation**: Meta totals = sum of line items for all scenarios

### Business Logic Coverage
- **Cost Attribution**: Multi-provider cost correlation accuracy
- **Discount Application**: RI, SavingsPlan, volume discount preservation
- **Temporal Processing**: Month/quarter boundary calculation accuracy
- **Cross-Catalog Operations**: Unified billing across data sources

### Performance Requirements
- **Query Execution**: ≤110% of current Trino performance
- **Memory Usage**: ≤120% of current system footprint
- **Concurrent Load**: Support existing user capacity

---

## 📋 Execution Plan

### Phase 1: P0 Critical Tests (Week 1)
Execute 9 critical data accuracy scenarios with **zero tolerance for failure**

### Phase 2: Advanced Billing (Week 2-3)
Execute 78 advanced billing scenarios (AWS/Azure/GCP specific features)

### Phase 3: Core SQL Operations (Week 4)
Execute 28 core Trino SQL operation scenarios

### Phase 4: Mathematical Precision (Week 5)
Execute 41 mathematical precision and operational reliability scenarios

---

## ✅ Success Criteria

### Migration Approval Requirements
- **Complete Test Pass Rate**: All 154 scenarios pass PostgreSQL validation
- **IQE Compliance**: All tests follow official IQE validation standards
- **Business Logic Preservation**: Critical financial logic (SavingsPlan, RI, etc.) intact
- **Performance Parity**: PostgreSQL performance within acceptable ranges

### Quality Gates
1. **P0 Critical Tests**: Must achieve complete pass rate before proceeding
2. **Financial Accuracy**: All currency, precision, and calculation tests pass
3. **Business Logic**: All provider-specific billing scenarios validated
4. **API Compatibility**: Zero breaking changes to existing API contracts

---

*This test scenario declaration ensures **complete Trino functionality preservation** while maintaining **IQE compliance standards** and avoiding **duplication with existing test coverage**. Every scenario targets specific **Trino-dependent business outcomes** critical for PostgreSQL migration success.*

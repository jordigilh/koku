# Trino Replacement Business Requirements

## Executive Summary

This document defines the comprehensive business requirements for replacing Trino functionality in the Koku cost management system with a PostgreSQL-only solution. The requirements ensure 100% functional parity while maintaining system reliability and data accuracy.

## 1. Data Processing Requirements

### 1.1 CSV to Parquet Processing
**BR-001**: The system must process CSV cost reports from cloud providers (AWS, Azure, GCP) and OpenShift clusters into structured data format for analysis.

**Acceptance Criteria**:
- Process CSV files with sizes up to 10GB+
- Handle chunked processing with configurable batch sizes (default: 200,000 rows)
- Support provider-specific data transformations and normalizations
- Maintain data type accuracy for financial calculations (decimal precision 24,9)
- Process daily file splits for parallel processing efficiency

**Current Implementation**: MASU converts CSV to Parquet, stores in S3, creates Trino external tables

**Replacement Requirement**: Load processed CSV data directly into PostgreSQL partitioned tables

### 1.2 Multi-Provider Data Integration
**BR-002**: The system must integrate cost and usage data from multiple cloud providers and OpenShift in a unified data model.

**Acceptance Criteria**:
- Support AWS Cost and Usage Reports with all service types
- Support Azure Cost Management exports with subscription hierarchies
- Support GCP BigQuery billing exports with project structures
- Support OpenShift usage metrics (pod, node, storage, network)
- Maintain provider-specific metadata (accounts, projects, services, regions)
- Support cross-provider resource correlation for OpenShift-on-Cloud scenarios

### 1.3 Time-Series Data Management
**BR-003**: The system must organize and partition cost data by time periods for efficient querying and retention management.

**Acceptance Criteria**:
- Partition data by year, month, and day for optimal query performance
- Support date range queries with automatic partition pruning
- Handle timezone conversions and date normalization across providers
- Support incremental data loading for daily processing cycles
- Implement data retention policies with automated cleanup

**Current Implementation**: Trino partitioned tables with S3 directory structure
**Replacement Requirement**: PostgreSQL native partitioning with equivalent performance characteristics

## 2. Data Transformation Requirements

### 2.1 JSON Processing and Filtering
**BR-004**: The system must process complex JSON structures for tags, labels, and metadata with filtering capabilities.

**Acceptance Criteria**:
- Parse and filter JSON tag data based on enabled tag keys configuration
- Support dynamic tag key enabling/disabling through admin interface
- Merge multiple JSON objects (node labels + namespace labels + resource tags)
- Filter JSON keys based on PostgreSQL configuration tables
- Maintain JSON structure integrity throughout processing pipeline

**Current Trino Operations**:
```sql
map_filter(
    cast(json_parse(tags) as map(varchar, varchar)),
    (k,v) -> contains(enabled_keys, k)
)
```

**PostgreSQL Equivalent Required**: JSON path operations with dynamic filtering

### 2.2 Cross-Provider Resource Matching
**BR-005**: The system must correlate resources between OpenShift clusters and underlying cloud infrastructure.

**Acceptance Criteria**:
- Match AWS EC2 instances to OpenShift nodes by resource ID suffix matching
- Match AWS EBS volumes to OpenShift persistent volumes by volume ID or CSI handle
- Support tag-based resource correlation when direct ID matching fails
- Handle Azure and GCP equivalent resource matching patterns
- Maintain resource matching accuracy above 95% for cost attribution

**Current Complexity**: Multi-stage CTEs with string suffix matching, tag correlation, array operations

**Algorithm Requirements**:
```sql
-- Resource ID suffix matching
substr(aws_resource_id, -length(ocp_node_id)) = ocp_node_id

-- Tag-based matching with enabled keys
array_join(filter(matched_tags, x -> STRPOS(resource_tags, x) != 0), ',')
```

### 2.3 Cost Calculation and Markup Processing
**BR-006**: The system must apply cost models, markup calculations, and currency conversions with high precision.

**Acceptance Criteria**:
- Support dynamic markup rates applied at processing time via template variables
- Calculate amortized costs for AWS Savings Plans and Reserved Instances
- Handle multiple cost types: unblended, blended, amortized, effective (Savings Plans)
- Apply OpenShift cost models with hourly, daily, and monthly rate structures
- Maintain financial precision with decimal(33,15) for markup calculations
- Support cost attribution across shared resources (storage volumes, network)

**Formula Examples**:
```sql
-- Markup calculation
unblended_cost * {{markup_rate}} AS markup_cost

-- Amortized cost logic
CASE
    WHEN lineitem_lineitemtype='Tax' OR lineitem_lineitemtype='Usage'
    THEN lineitem_unblendedcost
    ELSE savingsplan_savingsplaneffectivecost
END as calculated_amortized_cost
```

## 3. Aggregation and Summary Requirements

### 3.1 Multi-Level Data Aggregation
**BR-007**: The system must generate summary tables at multiple aggregation levels for API performance optimization.

**Acceptance Criteria**:
- Daily aggregation: Roll up hourly usage to daily summaries
- Account/Project aggregation: Group costs by organizational units
- Service/Product aggregation: Categorize costs by cloud services
- Regional aggregation: Group costs by geographic regions
- Cross-provider aggregation: Unified views across AWS/Azure/GCP + OpenShift
- Support incremental aggregation updates (not full rebuilds)

**Summary Table Categories**:
- Cost summaries (overall, by account, by service, by region)
- Compute summaries (instance types, usage patterns)
- Storage summaries (volume types, capacity utilization)
- Network summaries (data transfer, load balancer costs)
- Database summaries (RDS, CosmosDB, Cloud SQL costs)

### 3.2 OpenShift Capacity and Utilization Calculations
**BR-008**: The system must calculate OpenShift resource capacity, utilization, and unallocated resource attribution.

**Acceptance Criteria**:
- Calculate node CPU and memory capacity from raw metrics
- Aggregate cluster capacity across all nodes
- Compute pod CPU and memory usage vs. requests vs. limits
- Calculate effective usage (max of actual usage or requests)
- Attribute unallocated capacity to "Platform unallocated" vs "Worker unallocated" based on node roles
- Support storage capacity and utilization calculations for persistent volumes
- Handle shared volume attribution across multiple nodes

**Complex Calculations Required**:
```sql
-- Effective usage calculation
sum(coalesce(
    pod_effective_usage_cpu_core_seconds,
    greatest(pod_usage_cpu_core_seconds, pod_request_cpu_core_seconds)
)) / 3600.0 as pod_effective_usage_cpu_core_hours

-- Unallocated capacity by node role
CASE max(node_role)
    WHEN 'master' THEN 'Platform unallocated'
    WHEN 'infra' THEN 'Platform unallocated'
    WHEN 'worker' THEN 'Worker unallocated'
END as namespace
```

### 3.3 Cross-Provider Cost Attribution
**BR-009**: The system must attribute cloud infrastructure costs to OpenShift workloads with accurate resource correlation.

**Acceptance Criteria**:
- Correlate AWS costs with OpenShift pods running on matched EC2 instances
- Correlate Azure costs with OpenShift workloads on matched virtual machines
- Correlate GCP costs with OpenShift clusters on matched compute instances
- Support project-level cost rollups for chargeback/showback reporting
- Handle shared infrastructure costs (load balancers, storage) with fair allocation algorithms
- Maintain cost attribution audit trails for compliance and debugging

**Multi-Stage Processing Required**:
1. Resource matching (infrastructure ↔ OpenShift resources)
2. Cost allocation (infrastructure costs → matched OpenShift projects)
3. Summary aggregation (project → cluster → organizational rollups)

## 4. Query Performance Requirements

### 4.1 API Response Time Performance
**BR-010**: The system must maintain API response times within acceptable degradation limits from current Trino performance.

**Acceptance Criteria**:
- Simple cost queries (single provider, basic filtering): < 2 seconds
- Complex cross-provider queries: < 10 seconds
- Large dataset exports (CSV): < 30 seconds for up to 1M rows
- Dashboard refresh queries: < 5 seconds
- Acceptable performance degradation: Up to 50% slower than current Trino performance
- Support for concurrent API requests without significant performance degradation

### 4.2 Data Processing Performance
**BR-011**: The system must process daily cost data updates within acceptable time windows.

**Acceptance Criteria**:
- Daily data processing completion within 4-hour window
- Incremental processing support (process only new/changed data)
- Handle large customer datasets (100GB+ daily data) without failure
- Support parallel processing of multiple data sources simultaneously
- Automatic retry and recovery from processing failures

### 4.3 Storage and Scalability
**BR-012**: The system must efficiently manage large-scale cost data storage requirements.

**Acceptance Criteria**:
- Support data retention for 36+ months with efficient storage utilization
- Handle storage growth rates up to 50GB/month per large customer
- Implement efficient data compression for older partitions
- Support automated data archival and purging based on retention policies
- Maintain query performance as data volumes grow

## 5. API Compatibility Requirements

### 5.1 REST API Response Format Preservation
**BR-013**: All REST API endpoints must return identical response formats and data structures.

**Acceptance Criteria**:
- Maintain exact JSON response structure for all 80+ API endpoints
- Preserve pagination metadata format (`meta`, `links`, `data` structure)
- Maintain cost and usage value formats with units (`{"value": 123.45, "units": "USD"}`)
- Preserve time-series data organization (date-based grouping)
- Support all existing query parameters and filtering options

**API Categories to Preserve**:
- Cost reporting APIs (AWS, Azure, GCP, OpenShift)
- Instance type and compute APIs
- Storage and network APIs
- Cross-provider APIs (OCP-AWS, OCP-Azure, OCP-GCP)
- Resource type and metadata APIs
- Tag management APIs
- Forecast and trending APIs

### 5.2 Query Parameter Support
**BR-014**: All existing API query parameters and filtering capabilities must be preserved.

**Acceptance Criteria**:
- Date range filtering (`start_date`, `end_date`)
- Account/subscription/project filtering with multi-value support
- Service and resource type filtering
- Tag-based filtering with key-value pair support
- Organizational unit and cost center filtering
- Group-by operations (account, service, region, project, etc.)
- Ordering and sorting with multiple column support
- Pagination with configurable page sizes
- CSV export functionality for all endpoints

### 5.3 Data Accuracy and Consistency
**BR-015**: All API responses must return mathematically identical results to current Trino-based implementation.

**Acceptance Criteria**:
- Cost totals and subtotals must match to the cent (0.01 currency units)
- Usage metrics must match to 3 decimal places
- Aggregation results must be identical across all grouping combinations
- Time-series data must show identical trends and patterns
- Cross-provider attribution results must match exactly
- Tag filtering results must be identical
- Resource correlation results must maintain same matching accuracy

## 6. Data Integration Requirements

### 6.1 External Data Source Support
**BR-016**: The system must continue to integrate with all current external data sources and APIs.

**Acceptance Criteria**:
- AWS Cost and Usage Report API integration
- Azure Cost Management API integration
- GCP Cloud Billing API integration
- OpenShift metrics collection from koku-metrics-operator
- Cloud provider metadata APIs (account info, service catalogs, regions)
- Exchange rate APIs for multi-currency support
- RBAC integration with Red Hat SSO systems

### 6.2 Data Validation and Quality Assurance
**BR-017**: The system must implement comprehensive data validation and quality checks.

**Acceptance Criteria**:
- Validate data completeness for each processing cycle
- Detect and alert on data anomalies (cost spikes, missing data periods)
- Verify cross-provider resource matching accuracy
- Implement data reconciliation checks between raw and processed data
- Support data reprocessing capabilities for error correction
- Maintain audit trails for all data transformations

## 7. System Integration Requirements

### 7.1 Django ORM Integration
**BR-018**: The replacement solution must integrate seamlessly with existing Django models and ORM patterns.

**Acceptance Criteria**:
- Utilize existing Django model definitions for summary tables
- Support Django query annotations and aggregations
- Maintain compatibility with existing Django admin interfaces
- Support Django's multi-tenancy (django-tenants) architecture
- Preserve existing database migration patterns
- Support Django's caching framework integration

### 7.2 Celery Task Integration
**BR-019**: Data processing must integrate with existing Celery task management and scheduling.

**Acceptance Criteria**:
- Support existing MASU task scheduling patterns
- Integrate with current Celery retry and error handling mechanisms
- Maintain existing task monitoring and logging capabilities
- Support distributed task processing across multiple workers
- Preserve task dependency management (task chains, groups)

### 7.3 Configuration Management
**BR-020**: The system must use existing configuration management systems and patterns.

**Acceptance Criteria**:
- Utilize existing environment variable configuration patterns
- Support existing feature flag integration (Unleash)
- Maintain compatibility with current deployment configurations (OpenShift)
- Support existing secrets management patterns
- Preserve current logging and monitoring configurations

## 8. Operational Requirements

### 8.1 Monitoring and Observability
**BR-021**: The system must provide comprehensive monitoring and observability capabilities.

**Acceptance Criteria**:
- Maintain existing Prometheus metrics collection
- Support existing Grafana dashboard integrations
- Provide detailed processing time metrics for performance monitoring
- Implement health checks for data processing pipeline components
- Support distributed tracing for complex cross-provider operations
- Maintain existing alerting capabilities for processing failures

### 8.2 Backup and Recovery
**BR-022**: The system must implement robust backup and disaster recovery capabilities.

**Acceptance Criteria**:
- Support point-in-time recovery for data processing errors
- Implement incremental backup strategies for large datasets
- Support cross-region backup replication for disaster recovery
- Provide data export capabilities for compliance and auditing
- Support automated recovery from common failure scenarios
- Maintain existing backup retention policies

### 8.3 Security and Compliance
**BR-023**: The system must maintain current security and compliance standards.

**Acceptance Criteria**:
- Preserve existing tenant data isolation mechanisms
- Support current authentication and authorization patterns
- Maintain compliance with SOC 2, GDPR, and other regulatory requirements
- Support data encryption at rest and in transit
- Implement audit logging for all data access and modifications
- Support existing penetration testing and security scanning processes

## 9. Migration and Testing Requirements

### 9.1 Migration Strategy
**BR-024**: The system must support a safe, incremental migration from Trino to PostgreSQL-only architecture.

**Acceptance Criteria**:
- Support parallel operation during migration period (dual-write capability)
- Provide rollback capabilities if critical issues are discovered
- Support gradual customer migration (feature flags for A/B testing)
- Implement comprehensive pre-migration data validation
- Support zero-downtime migration for critical production workloads

### 9.2 Validation and Testing Framework
**BR-025**: The system must include comprehensive testing framework for validating functional parity.

**Acceptance Criteria**:
- Automated API response comparison between Trino and PostgreSQL implementations
- Automated SQL query result validation for all data processing operations
- Performance benchmark comparisons with acceptable degradation thresholds
- Edge case and error condition testing for all processing scenarios
- Load testing to validate system performance under production conditions
- Data accuracy validation for financial calculations and aggregations

## Business Impact and Success Criteria

### Primary Success Metrics:
1. **100% API Response Accuracy**: All endpoints return identical data
2. **Zero Data Loss**: No cost or usage data lost during migration
3. **Acceptable Performance**: <50% degradation in response times
4. **System Reliability**: 99.9% uptime maintained during and after migration
5. **Operational Simplicity**: Reduced infrastructure complexity and operational overhead

### Secondary Success Metrics:
1. **Cost Reduction**: Lower infrastructure costs from eliminating Trino cluster
2. **Maintenance Reduction**: Simplified system architecture reduces operational burden
3. **Development Velocity**: Faster development cycles with single database technology
4. **Performance Optimization**: Potential for optimization using PostgreSQL-specific features

## 10. Advanced Trino Functional Requirements

### 10.1 Complex Data Processing Operations

#### **FR-026: Complex JSON/Tag Matching Operations** ⭐ CRITICAL DATA ACCURACY
**BR-026**: The system must support advanced JSON/tag correlation operations for multi-provider cost attribution.

**Acceptance Criteria**:
- Support `any_match()` equivalent operations for tag array matching
- Handle complex string operations (`split()`, `strpos()`, `replace()`) for tag processing
- Maintain exact cost attribution logic for OpenShift-on-Cloud scenarios
- Support tag correlation across multiple provider namespaces
- Preserve matching accuracy for multi-million dollar cost allocations

**Current Trino Pattern**:
```sql
any_match(split(aws.matched_tag, ','), x->strpos(ocp.pod_labels, replace(x, ' ')) != 0)
```

**PostgreSQL Equivalent Required**: Array operations with string matching for identical cost attribution results.

#### **FR-027: Advanced Date/Time Functions with Precision** ⭐ CRITICAL DATA ACCURACY
**BR-027**: The system must handle complex date/time operations maintaining exact boundary calculations.

**Acceptance Criteria**:
- Support zero-padding month operations (`lpad(month, 2, '0')`)
- Handle date arithmetic with timezone awareness (`date_add('day', 1, end_date)`)
- Maintain exact month-end boundary processing for financial reporting
- Support cross-provider date normalization and comparison
- Preserve date-based partition matching accuracy

**Current Trino Patterns**:
```sql
lpad(month, 2, '0') = {{month}}
date_add('day', 1, {{end_date}})
```

**PostgreSQL Equivalent Required**: Date functions producing identical results for financial period boundaries.

#### **FR-028: Mathematical Functions for Unit Conversions** ⭐ CRITICAL DATA ACCURACY
**BR-028**: The system must support precision mathematical operations for resource calculations.

**Acceptance Criteria**:
- Support high-precision `power()` functions for binary unit conversions
- Handle memory conversion calculations (bytes → gigabytes) with exact precision
- Maintain floating-point arithmetic precision for resource utilization
- Support scientific notation and large number calculations
- Preserve resource capacity calculation accuracy for cost modeling

**Current Trino Pattern**:
```sql
memory_byte_seconds / 3600.0 * power(2, -30) as memory_gigabyte_hours
```

**PostgreSQL Equivalent Required**: Mathematical functions maintaining identical precision for resource metrics.

### 10.2 System Integration Operations

#### **FR-029: Direct Query API Security & Validation**
**BR-029**: The system must provide secure direct query capabilities with validation.

**Acceptance Criteria**:
- Support direct SQL query execution via REST API endpoint
- Implement SQL injection prevention with keyword filtering
- Support CSV and JSON response formats
- Maintain query result formatting consistency
- Support schema-scoped query execution with tenant isolation

**Security Requirements**:
```python
dissallowed_keywords = {"delete", "insert", "update", "alter", "create", "drop", "grant"}
```

#### **FR-030: Connection Management & Error Handling**
**BR-030**: The system must implement robust connection management with error recovery.

**Acceptance Criteria**:
- Support exponential backoff retry logic for database connections
- Handle specific database error types with appropriate recovery
- Support connection pooling and reuse patterns
- Implement timeout handling with graceful degradation
- Support distributed connection management across worker processes

**Error Handling Patterns**:
```python
@retry(retry_on=(DatabaseConnectionError, PartitionNotFoundError))
retries=8, max_wait=30, exponential_backoff_with_jitter
```

#### **FR-031: Partition Discovery and Lifecycle Management**
**BR-031**: The system must support dynamic partition management and metadata operations.

**Acceptance Criteria**:
- Support partition metadata queries for data lifecycle management
- Handle partition discovery across multiple tenant schemas
- Support automated partition cleanup based on retention policies
- Implement partition existence validation for processing workflows
- Support cross-partition query optimization

**Metadata Query Patterns**:
```sql
SELECT year, month, source FROM partition_metadata
WHERE partition_date < CURRENT_DATE - INTERVAL '90 days'
```

#### **FR-032: Dynamic Schema & Table Validation**
**BR-032**: The system must support runtime schema and table validation operations.

**Acceptance Criteria**:
- Support dynamic schema existence validation with caching
- Handle table existence checks for processing workflows
- Support multi-tenant schema validation patterns
- Implement validation result caching for performance optimization
- Support cross-schema validation for multi-provider scenarios

**Validation Patterns**:
```sql
SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = ?)
SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = ?)
```

#### **FR-033: Cross-Engine Data Validation Framework**
**BR-033**: The system must support automated data consistency validation capabilities.

**Acceptance Criteria**:
- Support cross-engine result comparison for migration validation
- Handle data accuracy validation across processing engines
- Support automated consistency checking for financial calculations
- Implement validation result logging and alerting
- Support selective validation for critical data processing workflows

**Validation Framework Requirements**:
```python
pg_results = execute_query(query, engine='postgresql')
validation_results = compare_results(baseline_results, pg_results, tolerance=0.01)
```

## Enhanced Success Criteria

### Critical Data Accuracy Metrics (Phase 1):
1. **JSON/Tag Matching Accuracy**: 100% cost attribution matching for multi-provider scenarios
2. **Date/Time Boundary Precision**: Exact monthly cutoff calculations with zero variance
3. **Mathematical Calculation Precision**: Resource utilization calculations within 0.001% variance

### Operational Reliability Metrics (Phase 2):
4. **API Security Validation**: 100% prevention of unauthorized query execution
5. **Connection Reliability**: 99.9% connection success rate with proper error recovery
6. **Partition Management Efficiency**: Automated cleanup with zero data loss
7. **Schema Validation Accuracy**: 100% correct schema/table detection across all tenants
8. **Cross-Engine Validation Coverage**: Automated validation for 100% of critical data paths

This requirements document serves as the definitive specification for Trino replacement functionality, ensuring complete business continuity while achieving the strategic goal of infrastructure simplification.









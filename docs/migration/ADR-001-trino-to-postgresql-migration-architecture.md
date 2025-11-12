# ADR-001: Trino to PostgreSQL Migration Architecture Decision

**Status**: Proposed
**Date**: November 9, 2025

---

## Table of Contents

1. [Context and Problem Statement](#context-and-problem-statement)
2. [Decision Drivers](#decision-drivers)
3. [Considered Alternatives](#considered-alternatives)
   - [Alternative 1: Direct PostgreSQL Staging + Business Logic Functions](#alternative-1-direct-postgresql-staging--business-logic-functions)
   - [Alternative 2: Citus Distributed PostgreSQL](#alternative-2-citus-distributed-postgresql)
   - [Alternative 3: PostgreSQL + Foreign Data Wrappers (FDW)](#alternative-3-postgresql--foreign-data-wrappers-fdw)
   - [Alternative 4: PostgreSQL + pg_parquet Extension](#alternative-4-postgresql--pg_parquet-extension)
   - [Alternative 5: PostgreSQL + Materialized Views](#alternative-5-postgresql--materialized-views)
   - [Alternative 6: PostgreSQL + TimescaleDB Extension](#alternative-6-postgresql--timescaledb-extension)
4. [Decision Outcome](#decision-outcome)
5. [Positive Consequences](#positive-consequences)
6. [Negative Consequences](#negative-consequences)
7. [Compliance and Validation](#compliance-and-validation)
8. [Implementation Timeline](#implementation-timeline)
9. [References and External Links](#references-and-external-links)

---

## Context and Problem Statement

Koku's cost management system currently depends on Trino + Hive for complex data processing and analytics. **The primary issue is the lack of internal support expertise for Trino + Hive infrastructure in onprem deployments.** This creates unsustainable operational risk and complexity. The decision has been made to migrate to a **PostgreSQL-only solution** to achieve:

1. **Support & maintenance simplification** - Cannot maintain Trino + Hive onprem infrastructure
2. **Functional parity guarantee** - Seamless transition without any functional impact
3. **Internal support capabilities** - Leverage existing PostgreSQL expertise
4. **Simplified deployment** - Eliminate Trino/Hive dependencies

**Key Constraint**: The solution must use **PostgreSQL-only technologies** with no external distributed systems.

---

## Decision Drivers

### 1. Internal Support Limitations ⭐ **PRIMARY DRIVER**
- **Current Gap**: Lack of internal support expertise for Trino + Hive infrastructure
- **Operational Risk**: Limited internal knowledge for troubleshooting, maintenance, and optimization
- **Support Cost**: External support or training requirements add operational overhead
- **Long-term Sustainability**: PostgreSQL has established internal support capabilities
- **Strategic Decision**: Cannot maintain Trino + Hive onprem deployments without internal expertise

### 2. Onprem Deployment Strategy ⭐ **SECONDARY DRIVER**
- **Current Issue**: Trino + Hive works well in SaaS but requires specialized operational expertise for onprem
- **Onprem Reality**: Cannot maintain Trino + Hive as an onprem solution due to lack of internal expertise
- **Target**: Use technology stack that matches internal support capabilities
- **Support Decision**: Do not want to support Trino + Hive onprem deployments

### 3. Functional Parity Guarantee ⭐ **CRITICAL REQUIREMENT**
- **Requirement**: Complete seamless transition without any functional impact
- **Scope**: All 154 test scenarios must pass identically [Ref: trino-migration-test-scenarios-declaration.md]
- **Business Logic**: SavingsPlan calculations, tag correlation, cross-provider reporting

### 4. Migration Complexity and Timeline
- **Constraint**: Minimize development effort and migration risk
- **Timeline**: Achieve migration within reasonable development timeframe
- **Risk Management**: Prefer proven technologies with clear migration paths

### 5. Operational Learning Curve
- **Team Expertise**: Development team has strong PostgreSQL experience
- **Maintenance**: Reduce operational burden of managing multiple database systems
- **Support**: Leverage existing PostgreSQL operational knowledge

---

## Considered PostgreSQL-Only Alternatives

### Alternative 1: Direct PostgreSQL Staging + Business Logic Functions

#### Architecture Overview
```
CSV Reports → MASU → PostgreSQL Staging Tables → Custom Business Logic Functions → PostgreSQL Summaries → API
```

#### Implementation Details
- **Raw Data Storage**: PostgreSQL partitioned tables (year/month/day)
- **Complex Processing**: Custom PostgreSQL functions replacing Trino operations
- **JSON Processing**: PostgreSQL native JSON operators + custom functions
- **Cross-Catalog Logic**: Eliminated (single PostgreSQL database)
- **Performance**: Table partitioning + selective indexing + materialized views

#### Advantages ✅
- **Internal Support**: Red Hat has established PostgreSQL expertise and support capabilities, eliminating the Trino + Hive support gap [Ref: PostgreSQL enterprise adoption and internal support advantages](https://www.cybertec-postgresql.com/en/postgresql-overview/advantages-of-postgresql/)

#### Disadvantages ❌
- **Data Growth**: Potential storage increase due to PostgreSQL row-oriented storage vs. Parquet columnar compression [Ref: Cybertec PostgreSQL storage comparison shows heap storage requires significantly more space than columnar formats](https://www.cybertec-postgresql.com/en/postgresql-storage-comparing-storage-options/)
- **Custom Logic**: Requires implementing complex business functions from scratch [Ref: PostgreSQL custom function development and maintenance considerations](https://www.crunchydata.com/blog/postgres-functions-vs-stored-procedures-whats-the-difference)

---

### Alternative 2: Citus Distributed PostgreSQL

#### Architecture Overview
```
CSV Reports → MASU → Citus Coordinator → Citus Worker Nodes → Distributed Tables → API
```

#### Implementation Details
- **Technology**: [Citus open source extension](https://docs.citusdata.com/en/stable/get_started/what_is_citus.html) for distributed PostgreSQL
- **Sharding**: Distribute tables across worker nodes by tenant/provider
- **Query Engine**: Distributed query execution with parallelism
- **Compatibility**: Complete PostgreSQL compatibility (extension, not fork)
- **Scaling**: Start single-node, scale to multi-node cluster when needed

#### Advantages ✅
- **Internally Supported**: Citus expertise available within the organization - eliminates support concerns
- **True Horizontal Scaling**: Distributed query execution similar to Trino capabilities [Ref: Citus horizontal scaling and distributed architecture](https://docs.citusdata.com/en/stable/get_started/concepts.html)
- **PostgreSQL Native**: Complete PostgreSQL compatibility with full SQL support [Ref: Citus maintains full PostgreSQL compatibility as an extension](https://docs.citusdata.com/en/stable/get_started/what_is_citus.html)
- **Proven Scale**: Citus extension enables PostgreSQL large-scale distributed deployments [Ref: Citus distributed PostgreSQL architecture and scaling](https://docs.citusdata.com/en/stable/get_started/concepts.html)
- **Multi-Tenant Optimized**: Perfect architectural fit for Koku's tenant-based data model [Ref: Citus multi-tenant SaaS architecture](https://docs.citusdata.com/en/stable/use_cases/multi_tenant.html)
- **Future-Proof Scaling**: Start single-node, scale out seamlessly when needed [Ref: Citus scaling documentation](https://docs.citusdata.com/en/stable/admin_guide/cluster_management.html)
- **Query Performance**: Distributed execution for analytical workloads vs single-node limitations [Ref: Citus distributed query execution](https://docs.citusdata.com/en/stable/develop/reference_processing.html)
- **Linear Scalability**: Distributed query execution improves performance through parallel processing [Ref: Citus parallel query execution and performance](https://docs.citusdata.com/en/stable/develop/reference_processing.html)
- **Columnar Storage Efficiency**: Citus columnar tables achieve 6x-10x compression vs row storage, potentially matching Parquet efficiency [Ref: Citus cstore_fdw documentation shows up to 10x compression](https://github.com/citusdata/cstore_fdw) and [Citus 10.0+ native columnar support](https://www.citusdata.com/blog/2021/03/05/citus-10-release-open-source-rebalancer-and-columnar-for-postgres/)

#### Disadvantages ❌
- **Added Operational Complexity**: Multi-node cluster management vs single-node simplicity [Ref: Citus cluster management and administration](https://docs.citusdata.com/en/stable/admin_guide/cluster_management.html)
- **Learning Curve**: Team needs to learn Citus-specific concepts (sharding keys, distribution strategies) [Ref: Citus data modeling and distribution strategies](https://docs.citusdata.com/en/stable/sharding/data_modeling.html)
- **Initial Overhead**: More complex setup and configuration than single PostgreSQL instance [Ref: Citus installation and configuration requirements](https://docs.citusdata.com/en/stable/installation/single_node.html)
- **Current Scale Necessity**: May be more than needed for current onprem deployment volumes

#### Decision Rationale for Selection/Rejection
**Citus is now a VIABLE OPTION** since it's internally supported. The decision becomes:
- **Current Needs**: Single PostgreSQL meets immediate requirements with simpler operations
- **Future Scaling**: Citus provides superior long-term scalability and query performance
- **Team Readiness**: Direct PostgreSQL leverages existing expertise immediately
- **Migration Strategy**: Can migrate to Citus later if scaling needs emerge

**Decision**: Proceed with Direct PostgreSQL for immediate migration, with Citus as the **recommended scaling path** when distributed performance becomes necessary.

---

### Alternative 3: PostgreSQL Foreign Data Wrappers (FDW)

#### Architecture Overview
```
CSV Reports → External Storage (S3/MinIO) → PostgreSQL FDW → Virtual Tables → API
```

#### Implementation Details
- **Technology**: PostgreSQL Foreign Data Wrappers (file_fdw, s3_fdw)
- **Storage**: Keep raw data in external files (CSV/Parquet)
- **Access**: Query external data through PostgreSQL virtual tables
- **Processing**: Combine FDW data with PostgreSQL processing logic

#### Advantages ✅
- **Storage Efficiency**: Raw data stays in compressed external format (Parquet, ORC, or CSV with compression) [Ref: Foreign Data Wrapper capabilities and external data access](https://www.crunchydata.com/blog/performance-tips-for-postgres-fdw)
- **PostgreSQL Native**: Uses built-in PostgreSQL FDW capabilities
- **Flexible**: Can access multiple external data sources

#### Disadvantages ❌
- **Performance**: FDW queries significantly slower than native tables [Ref: PostgreSQL FDW performance studies show network latency and limited pushdown capabilities](https://www.crunchydata.com/blog/performance-tips-for-postgres-fdw)
- **Limited Functionality**: FDW pushdown capabilities limited for complex operations [Ref: Complex queries require data transfer to local server for processing](https://www.svix.com/blog/fdw-pitfalls/)
- **Query Planning**: PostgreSQL planner lacks detailed statistics about foreign tables, leading to suboptimal execution plans [Ref: FDW planning overhead documentation](https://www.svix.com/blog/fdw-pitfalls/)

#### Decision Rationale for Rejection
**Primary Reason**: **Performance concerns** - FDW performance would not meet query response requirements due to network latency, limited pushdown capabilities, and suboptimal query planning for foreign tables.

---

### Alternative 4: PostgreSQL with pg_parquet Extension

#### Architecture Overview
```
CSV Reports → Parquet Files → PostgreSQL + pg_parquet → Direct Parquet Queries → API
```

#### Implementation Details
- **Technology**: pg_parquet extension for direct Parquet file access
- **Storage**: Convert CSV to Parquet, query directly from PostgreSQL
- **Performance**: Leverage Parquet columnar compression benefits
- **Integration**: Native PostgreSQL queries against Parquet files

#### Advantages ✅
- **Storage Efficiency**: Maintains Parquet compression benefits
- **Performance**: Columnar access for analytical queries
- **PostgreSQL Native**: Extension provides seamless integration

#### Disadvantages ❌
- **Extension Maturity**: pg_parquet is relatively new extension [Ref: pg_parquet PostgreSQL extension by Crunchy Data](https://github.com/CrunchyData/pg_parquet)
- **External Storage**: Still requires managing Parquet files outside PostgreSQL
- **Setup Requirements**: Requires S3/cloud storage configuration and pg_parquet extension installation [Ref: Installation requires extension compilation and cloud storage setup](https://github.com/CrunchyData/pg_parquet)

#### Decision Rationale for Rejection
**Primary Reason**: **Extension maturity concerns** - pg_parquet is a relatively new extension (2023) requiring additional evaluation for mission-critical financial data processing.

---

### Alternative 5: PostgreSQL Partitioning + Materialized Views

#### Architecture Overview
```
CSV Reports → PostgreSQL Partitioned Tables → Materialized Views → Aggressive Indexing → API
```

#### Implementation Details
- **Partitioning**: Extensive table partitioning (time, provider, tenant)
- **Materialized Views**: Pre-computed aggregations for common queries
- **Indexing**: Comprehensive index strategy for performance optimization
- **Refresh Strategy**: Automated materialized view refresh workflows

#### Advantages ✅
- **PostgreSQL Native**: Uses only built-in PostgreSQL features
- **Performance Optimized**: Materialized views provide fast query responses
- **Operational Simplicity**: No extensions or external dependencies

#### Disadvantages ❌
- **Storage Overhead**: Materialized views significantly increase storage requirements
- **Refresh Complexity**: Managing materialized view refresh workflows
- **Limited Flexibility**: Pre-computed views may not cover all query patterns
- **Maintenance Burden**: Complex partitioning + indexing strategy maintenance

#### Decision Rationale for Rejection
**Primary Reason**: **Storage overhead and maintenance complexity** - The extensive materialized view strategy would create excessive storage overhead and operational complexity.

---

### Alternative 6: TimescaleDB (PostgreSQL Extension)

#### Architecture Overview
```
CSV Reports → TimescaleDB Hypertables → Time-Series Optimization → Automated Partitioning → API
```

#### Implementation Details
- **Technology**: TimescaleDB extension optimized for time-series workloads
- **Hypertables**: Automatic partitioning by time dimension
- **Compression**: Built-in columnar compression for older data
- **Analytics**: Time-series specific analytical functions

#### Advantages ✅
- **Time-Series Optimized**: Perfect fit for cost data's temporal nature
- **Automatic Partitioning**: Handles partitioning strategy automatically
- **Compression**: Excellent compression for historical data
- **PostgreSQL Compatible**: Full SQL compatibility maintained

#### Disadvantages ❌
- **Extension Dependency**: Adds another extension to manage and maintain
- **Licensing**: Enterprise features require commercial licensing
- **Operational Learning**: Team needs to learn TimescaleDB-specific concepts
- **Overkill**: Many TimescaleDB features not needed for Koku's use case

#### Decision Rationale for Rejection
**Primary Reason**: **Unnecessary complexity** - TimescaleDB's specialized time-series features are more than needed for Koku's use case, adding operational overhead without sufficient benefit.

---

## Decision Outcome

### Recommended Alternative: PostgreSQL Migration (Deployment Option TBD)

#### Detailed Rationale

**Note**: The migration targets **PostgreSQL** generically. Both Direct PostgreSQL and Citus are **viable deployment options** with nearly identical business logic. **Team decision pending** on deployment approach - this ADR provides analysis for both options.

**✅ Primary Decision Factors:**

1. **Internal Support Capabilities** ⭐ **MAIN MOTIVATION**
   - **Lack of internal Trino + Hive expertise** is the primary driver for migration
   - **Both PostgreSQL and Citus are internally supported** - eliminates external dependencies
   - **Existing PostgreSQL expertise** provides immediate implementation capability
   - **Direct PostgreSQL** requires no additional learning curve
   - **Long-term sustainability** with established internal capabilities

2. **Functional Parity Guarantee** ⭐
   - **Direct business logic control** ensures identical calculations
   - **Custom PostgreSQL functions** can replicate any Trino operation exactly
   - **Comprehensive testing approach** validates 154 scenarios for complete parity [Ref: trino-migration-test-scenarios-declaration.md]

3. **Deployment Options** ⭐
   - **Direct PostgreSQL**: Immediate solution with familiar operations and lower initial complexity
   - **Citus**: Distributed solution with columnar storage efficiency and horizontal scaling
   - **Team decision required** on deployment approach based on operational preferences

4. **Strategic Flexibility** ⭐
   - **PostgreSQL-generic migration** allows deployment choice flexibility
   - **Citus deployment option** available without code changes if scaling needs emerge
   - **Nearly identical business logic** regardless of deployment choice

**✅ Implementation Approach:**
- **Replace Trino functions** with equivalent PostgreSQL custom functions
- **Migrate complex SQL** from Trino-specific syntax to PostgreSQL-compatible queries
- **Implement performance optimizations** through partitioning, indexing, and query optimization
- **Ensure deployment flexibility** for both Direct PostgreSQL and Citus options

---

## 🔄 **PostgreSQL Deployment Decision - PENDING TEAM INPUT**

**Recommended Approach**: **PostgreSQL-Generic Migration** with deployment option to be determined by team.

**Key Decision Points for Team Discussion**:
- **Both Direct PostgreSQL and Citus are viable deployment options** with nearly identical business logic
- **Direct PostgreSQL**: Simpler operations, faster implementation, single-node architecture
- **Citus**: Columnar storage efficiency (6x-10x compression), distributed processing, addresses storage concerns
- **Team decision required** on deployment approach based on operational preferences and scaling priorities

---

## Consequences

### Positive Consequences ✅

1. **Support & Operational Simplification** ⭐ **PRIMARY BENEFIT**
   - **Leverage existing PostgreSQL expertise** - eliminates need for Trino + Hive specialized knowledge
   - **Single database system** to maintain, monitor, troubleshoot, and optimize
   - **Eliminate external support dependencies** for big data infrastructure
   - **Proven internal support capabilities** for PostgreSQL operations
   - **Long-term sustainability** without requiring big data infrastructure expertise

2. **Functional Parity Assurance** ⭐
   - **Direct control over business logic** ensures identical financial calculations
   - **Custom PostgreSQL functions** provide exact Trino operation replication
   - **Comprehensive testing validation** through 154 scenario verification [Ref: trino-migration-test-scenarios-declaration.md]

3. **Infrastructure Maintenance Simplification** ⭐
   - **Elimination of Trino + Hive multi-service architecture** (JVMs, distributed query engines, Metastore services)
   - **Single PostgreSQL instance** maintenance vs. specialized big data stack
   - **No specialized big data infrastructure** requiring dedicated expertise

4. **Deployment & Development Simplification**
   - **Eliminate Trino/Hive from deployment stack** - simpler container orchestration
   - **Faster development cycles** with familiar PostgreSQL tools and patterns
   - **Reduced onprem deployment complexity** and resource requirements

### Negative Consequences ❌

1. **Data Storage Growth**
   - Expected storage increase due to row-oriented vs columnar storage [Ref: Cybertec PostgreSQL storage comparison analysis](https://www.cybertec-postgresql.com/en/postgresql-storage-comparing-storage-options/)
   - Mitigation: Aggressive partitioning, compression, and retention policies

2. **Performance Risk**
   - PostgreSQL single-node performance may not match Trino distributed queries
   - Mitigation: Comprehensive performance testing, optimization strategies, and fallback plans

3. **Custom Logic Implementation Effort**
   - Significant development effort to implement Trino functionality in PostgreSQL
   - Mitigation: Incremental migration, comprehensive testing, and IQE validation

4. **Temporary Loss of Distributed Query Benefits**
   - Single-node PostgreSQL lacks distributed query execution capabilities
   - Mitigation: PostgreSQL parallel queries, aggressive optimization, and **future Citus migration path**

---

## Implementation Plan

### Phase 1: PostgreSQL Migration Implementation (Weeks 1-4)
- Design PostgreSQL schema and business logic functions
- Convert Trino SQL files to PostgreSQL equivalents
- Implement comprehensive testing and validation

### Phase 2: Production Deployment (Weeks 5-6)
- Deploy PostgreSQL-based solution alongside existing Trino system
- Gradual traffic migration with performance validation
- Monitor and optimize as needed

### Future Consideration: Alternative Deployment Options
- **Citus deployment** can be considered if scaling requirements emerge
- **Migration path available** without business logic changes
- **Decision based on** operational needs and performance requirements

---

## Compliance

**✅ Meets All Decision Drivers:**
- **Internal Support Limitations**: PostgreSQL migration eliminates Trino + Hive support gap - THE PRIMARY MOTIVATION
- **Functional Parity Guarantee**: PostgreSQL custom functions ensure identical business logic
- **Onprem Deployment Strategy**: PostgreSQL provides supported solution with deployment flexibility
- **Migration Complexity**: PostgreSQL-based migration minimizes risk with familiar technology
- **Operational Learning Curve**: Leverages existing PostgreSQL expertise

**✅ Alternative Analysis Complete:**
All viable PostgreSQL-only alternatives were considered and evaluated against decision drivers.

**✅ Risk Mitigation Planned:**
Comprehensive mitigation strategies address identified negative consequences including data growth, performance risks, and implementation complexity.

---

## References

- [Citus Distributed PostgreSQL Documentation](https://docs.citusdata.com/en/stable/get_started/what_is_citus.html)
- [Crunchy Data PostgreSQL FDW Performance Analysis](https://www.crunchydata.com/blog/performance-tips-for-postgres-fdw)
- [TimescaleDB PostgreSQL Extension](https://docs.timescale.com/)
- [Trino to PostgreSQL Technical Migration Analysis](./trino-to-postgresql-technical-migration-analysis.md)
- [Trino Migration Test Scenarios Declaration](./trino-migration-test-scenarios-declaration.md)

---

**ADR Status**: 📋 **PROPOSED** - PostgreSQL migration recommended. **Team input required** on deployment approach (Direct PostgreSQL vs Citus) based on operational preferences and scaling priorities.

---

## References and Data Sources

### Factual References:
- **Test Scenarios**: 154 comprehensive scenarios documented in `trino-migration-test-scenarios-declaration.md`
- **Trino SQL Migration Scope**: 63 SQL files, 4,064 lines of code [Ref: `find koku/masu/database/trino_sql -name "*.sql"`]
- **Core Trino Functions**: `json_parse()`, `map_filter()`, `contains()` [Ref: koku/masu/database/trino_sql/reporting_awscostentrylineitem_daily_summary.sql:69-71]
- **Current Processing**: 200,000 row batch processing [Ref: koku/koku/settings.py:620 - `PARQUET_PROCESSING_BATCH_SIZE`]
- **PostgreSQL Models**: Time-partitioned tables [Ref: koku/reporting/provider/*/models.py]
- **Technical Analysis**: Detailed in `trino-to-postgresql-technical-migration-analysis.md`

### Decision Basis:
- **Internal Support Assessment**: Based on current team expertise and operational capabilities
- **Migration Complexity**: Derived from codebase analysis and technical requirements
- **Functional Parity**: Validated through comprehensive test scenario development

# Trino to PostgreSQL Migration - Quick Start Guide

**For Developers Ready to Begin Implementation**

---

## 🚀 Getting Started (5 minutes)

### **Step 1: Read the Summary**
📄 **[IMPLEMENTATION-PLAN-SUMMARY.md](./IMPLEMENTATION-PLAN-SUMMARY.md)**

This 5-minute read gives you:
- Overview of the 6-week timeline
- Key technical components
- Architecture changes (7 components → 2 components)
- Success criteria

### **Step 2: Review the Full Plan**
📋 **[TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md)**

This is your **complete implementation guide** with:
- 30 days of detailed tasks (Days 1-30)
- 60 SQL file migrations
- 5 custom PostgreSQL functions
- Docker Compose dev environment
- Helm chart updates
- Testing strategy
- Deployment procedures

### **Step 3: Set Up Your Environment**
Choose your development environment:

#### **Option A: Docker Compose (Recommended for Development)**
```bash
# Clone the repository
cd /Users/jgil/go/src/github.com/insights-onprem/koku

# Start all services
docker-compose -f docker-compose.dev.yml up -d

# Verify services are running
docker-compose -f docker-compose.dev.yml ps

# Access services:
# - Koku API (Reads): http://localhost:8000
# - Koku API (Writes): http://localhost:8001
# - PostgreSQL: localhost:5432
# - pgAdmin: http://localhost:5050 (admin@koku.dev / admin)
```

#### **Option B: OpenShift (For Production Testing)**
```bash
# Navigate to Helm chart directory
cd /Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart

# Deploy with PostgreSQL-only mode
helm install cost-mgmt-dev ./cost-management-onprem \
    --namespace cost-mgmt-dev \
    --create-namespace \
    --values cost-management-onprem/values-koku.yaml \
    --set costManagement.usePostgreSQLOnly=true \
    --set trino.enabled=false \
    --set hiveMetastore.enabled=false \
    --wait

# Verify deployment
kubectl get pods -n cost-mgmt-dev
```

---

## 📅 Week-by-Week Breakdown

### **Week 1: Foundation (Days 1-5)**
**Goal**: Set up PostgreSQL 16 infrastructure

**Tasks**:
1. Deploy PostgreSQL 16 with extensions
2. Create staging tables with partitioning
3. Implement 5 custom PostgreSQL functions
4. Create CSV direct loader
5. Set up feature flag infrastructure

**Deliverable**: Core infrastructure ready

**Time Estimate**: 5 days (1 developer)

**Start Here**: [Week 1 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-1-infrastructure-setup-week-1-days-1-5)

---

### **Week 2: Core SQL Migration (Days 6-10)**
**Goal**: Migrate daily summary queries for all providers

**Tasks**:
1. Migrate AWS daily summary
2. Migrate Azure daily summary
3. Migrate GCP daily summary
4. Migrate OCP daily summary
5. Migrate tag matching queries

**Deliverable**: 10/60 SQL files migrated (17%)

**Time Estimate**: 5 days (1 developer)

**Start Here**: [Week 2 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-2-core-sql-migration-week-2-days-6-10)

---

### **Week 3: OCP-on-Cloud Integration (Days 11-15)**
**Goal**: Migrate OCP-on-Cloud integration queries

**Tasks**:
1. OCP-on-AWS tag matching
2. OCP-on-Azure tag matching
3. OCP-on-GCP tag matching
4. Cost summary aggregations (15 queries)
5. Database cleanup queries

**Deliverable**: 43/60 SQL files migrated (72%)

**Time Estimate**: 5 days (1 developer)

**Start Here**: [Week 3 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-3-ocp-on-cloud-integration-week-3-days-11-15)

---

### **Week 4: Specialized Queries & Performance (Days 16-20)**
**Goal**: Complete SQL migration and optimize performance

**Tasks**:
1. RI/Savings Plan amortization
2. Network/storage queries
3. Performance indexes (15 indexes)
4. Materialized views
5. Performance benchmarks

**Deliverable**: 60/60 SQL files migrated (100%)

**Time Estimate**: 5 days (1 developer)

**Start Here**: [Week 4 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-4-specialized-queries--performance-week-4-days-16-20)

---

### **Week 5: Testing & Validation (Days 21-25)**
**Goal**: Validate migration with comprehensive testing

**Tasks**:
1. IQE test environment setup
2. Run 85 IQE core tests
3. Run 128 extended tests
4. Data accuracy validation
5. Load testing (50 concurrent users)

**Deliverable**: All tests passing, data accuracy validated

**Time Estimate**: 5 days (1 developer + 1 QA)

**Start Here**: [Week 5 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-5-testing--validation-week-5-days-21-25)

---

### **Week 6: Production Deployment (Days 26-30)**
**Goal**: Deploy to production and hand off to operations

**Tasks**:
1. Production readiness checklist
2. Blue-green deployment
3. Production deployment
4. Monitoring setup (Prometheus/Grafana)
5. Operations runbook and handoff

**Deliverable**: Production deployment complete

**Time Estimate**: 5 days (1 developer + 1 ops)

**Start Here**: [Week 6 in Implementation Plan](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#-phase-6-production-deployment-week-6-days-26-30)

---

## 🔑 Key Files to Know

### **SQL Files (60 total)**
Located in: `koku/masu/database/trino_sql/` (current) → `koku/masu/database/postgresql_sql/` (new)

**AWS** (15 files):
- `reporting_awscostentrylineitem_daily_summary.sql`
- `reporting_aws_cost_summary_by_account.sql`
- `reporting_aws_cost_summary_by_service.sql`
- ... (12 more)

**Azure** (12 files):
- `reporting_azurecostentrylineitem_daily_summary.sql`
- ... (11 more)

**GCP** (10 files):
- `reporting_gcpcostentrylineitem_daily_summary.sql`
- ... (9 more)

**OCP** (8 files):
- `reporting_ocpusagelineitem_daily_summary.sql`
- ... (7 more)

**OCP-on-Cloud** (12 files):
- `reporting_ocpawstags_summary.sql`
- ... (11 more)

**Cleanup** (3 files):
- `reporting_aws_delete_line_items.sql`
- ... (2 more)

### **Python Files**
- `koku/masu/database/sql/postgres_functions.sql` - Custom PostgreSQL functions
- `koku/masu/database/csv_loader.py` - CSV direct loader
- `koku/masu/database/aws_report_db_accessor.py` - AWS report accessor (update for feature flag)
- `koku/masu/database/azure_report_db_accessor.py` - Azure report accessor
- `koku/masu/database/gcp_report_db_accessor.py` - GCP report accessor
- `koku/masu/database/ocp_report_db_accessor.py` - OCP report accessor

### **Configuration Files**
- `docker-compose.dev.yml` - Docker Compose dev environment
- `../ros-helm-chart/cost-management-onprem/values-koku.yaml` - Helm values
- `koku/settings.py` - Django settings (add `USE_POSTGRESQL_ONLY` feature flag)

---

## 🧪 Testing Strategy

### **Unit Tests**
Run after each SQL file migration:
```bash
python manage.py test masu.database.test.test_aws_postgresql_migration -v 2
```

### **IQE Tests** (85 tests)
Run weekly:
```bash
iqe tests plugin cost_management -v -s
```

### **Extended Tests** (128 tests)
Run at end of Week 4:
```bash
python manage.py test \
    masu.database.test.test_aws_postgresql_migration \
    masu.database.test.test_azure_postgresql_migration \
    masu.database.test.test_gcp_postgresql_migration \
    --verbosity=2 --parallel=4
```

### **Performance Benchmarks**
Run at end of Week 4:
```bash
python manage.py test masu.database.test.benchmark_postgresql_vs_trino
```

### **Load Testing**
Run in Week 5:
```bash
python manage.py test masu.database.test.load_test_postgresql
```

---

## 🐛 Common Issues & Solutions

### **Issue 1: PostgreSQL Connection Errors**
**Symptom**: `psycopg2.OperationalError: could not connect to server`

**Solution**:
```bash
# Check PostgreSQL is running
docker-compose -f docker-compose.dev.yml ps postgres

# Check connection settings
docker-compose -f docker-compose.dev.yml exec koku-api-reads \
    python -c "from django.db import connection; connection.ensure_connection(); print('✅ Connected')"
```

### **Issue 2: Migration Job Fails**
**Symptom**: `django.db.utils.ProgrammingError: relation "api_tenant" does not exist`

**Solution**:
```bash
# Run migrations manually
docker-compose -f docker-compose.dev.yml exec koku-api-reads \
    python manage.py migrate --noinput
```

### **Issue 3: SQL Syntax Errors**
**Symptom**: `ERROR: syntax error at or near "uuid"`

**Solution**:
- Check you're using PostgreSQL syntax, not Trino syntax
- Common replacements:
  - `uuid()` → `gen_random_uuid()`
  - `json_parse(tags)` → `tags::jsonb`
  - `date_add('day', 1, date)` → `date + INTERVAL '1 day'`
  - `arbitrary(value)` → `max(value)`

### **Issue 4: Performance Issues**
**Symptom**: Queries taking >5 seconds

**Solution**:
```sql
-- Check indexes are being used
EXPLAIN ANALYZE SELECT ...;

-- Check cache hit ratio (should be >90%)
SELECT
    sum(blks_hit)*100/sum(blks_hit+blks_read) AS cache_hit_ratio
FROM pg_stat_database;

-- Run ANALYZE
ANALYZE VERBOSE;
```

---

## 📚 Reference Documents

### **Must Read**
1. **[IMPLEMENTATION-PLAN-SUMMARY.md](./IMPLEMENTATION-PLAN-SUMMARY.md)** - Start here!
2. **[TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md)** - Your daily guide

### **Background Reading**
3. **[ADR-001-trino-to-postgresql-migration-architecture.md](./ADR-001-trino-to-postgresql-migration-architecture.md)** - Architecture decision
4. **[trino-function-replacement-confidence-assessment.md](./trino-function-replacement-confidence-assessment.md)** - Function replacements

### **Testing**
5. **[tests/trino-test-overlap-summary.md](./tests/trino-test-overlap-summary.md)** - Test coverage summary
6. **[tests/trino-test-overlap-analysis.md](./tests/trino-test-overlap-analysis.md)** - Detailed test mapping

---

## 🎯 Success Checklist

Use this checklist to track your progress:

### **Week 1: Foundation**
- [ ] PostgreSQL 16 deployed
- [ ] Extensions installed (`uuid-ossp`, `pg_stat_statements`, `btree_gin`)
- [ ] Staging tables created with partitioning
- [ ] 5 custom functions implemented
- [ ] CSV direct loader working
- [ ] Feature flag infrastructure in place

### **Week 2: Core SQL Migration**
- [ ] AWS daily summary migrated
- [ ] Azure daily summary migrated
- [ ] GCP daily summary migrated
- [ ] OCP daily summary migrated
- [ ] Tag matching queries migrated
- [ ] Unit tests passing for all 10 files

### **Week 3: OCP-on-Cloud Integration**
- [ ] OCP-on-AWS queries migrated (3 files)
- [ ] OCP-on-Azure queries migrated (3 files)
- [ ] OCP-on-GCP queries migrated (3 files)
- [ ] Cost summary aggregations migrated (15 files)
- [ ] Database cleanup queries migrated (8 files)
- [ ] Unit tests passing for all 32 files

### **Week 4: Specialized Queries & Performance**
- [ ] RI/Savings Plan queries migrated (5 files)
- [ ] Network/storage queries migrated (8 files)
- [ ] Performance indexes created (15 indexes)
- [ ] Materialized views created
- [ ] Performance benchmarks run
- [ ] All 60 SQL files migrated

### **Week 5: Testing & Validation**
- [ ] IQE test environment configured
- [ ] 85 IQE tests passing (100%)
- [ ] 128 extended tests passing (95%+)
- [ ] Data accuracy validated (99.9%+)
- [ ] Load testing passed (50 concurrent users)

### **Week 6: Production Deployment**
- [ ] Production readiness checklist complete
- [ ] Blue-green deployment tested
- [ ] Production deployment successful
- [ ] Monitoring configured (Prometheus/Grafana)
- [ ] Alerts configured
- [ ] Operations runbook created
- [ ] Handoff to operations complete

---

## 🚨 When to Ask for Help

### **Immediate Escalation Required**
- Data loss or corruption
- Production outage
- Security vulnerability discovered
- Critical test failures (>10% of tests failing)

### **Standard Escalation**
- Unexpected performance degradation (>2x slower)
- Test failures (1-10% of tests failing)
- Unclear requirements or specifications
- Blocked on external dependencies

### **Normal Support**
- Implementation questions
- Code review requests
- Testing assistance
- Documentation clarifications

---

## 📞 Support Contacts

**Implementation Team Lead**: [Contact Info]
**Database Engineer**: [Contact Info]
**QA Lead**: [Contact Info]
**Operations Team**: [Contact Info]

---

## 🎉 Ready to Start?

1. ✅ Read the [Implementation Plan Summary](./IMPLEMENTATION-PLAN-SUMMARY.md)
2. ✅ Set up your development environment (Docker Compose or OpenShift)
3. ✅ Start with [Week 1, Day 1](./TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md#day-1-postgresql-16-setup--extensions)

**Good luck! You've got this!** 🚀

---

*Last Updated: November 11, 2025*



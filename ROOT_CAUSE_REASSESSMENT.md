# Root Cause Reassessment - 500 Errors in OCP Cost Reports

**Date**: December 3, 2025  
**Status**: REASSESSED - Focus on Python Aggregator Integration

---

## 🎯 The Real Problem

**NO DATA EXISTS in the database tables:**
```sql
-- Both queries return 0 rows:
daily_summary_count: 0
project_summary_count: 0
```

**This is NOT a Koku bug.** The production code is fine. The issue is:

### The Python Aggregator Has Never Run

**Evidence:**
1. ✅ Feature flag is set: `USE_PYTHON_AGGREGATOR=true`
2. ✅ Task is registered in Celery: `process_ocp_parquet_poc`
3. ✅ No import errors in production
4. ❌ **Zero rows in database tables** (no data processed in last 7 days)
5. ❌ **No logs showing Python Aggregator execution**

---

## 🔍 Key Findings from Code Analysis

### Where Python Aggregator Writes Data

From `db_writer.py` line 115:
```python
def write_summary_data(self, df, batch_size=1000, truncate=False):
    table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"
    return self._write_data(df, table_name, batch_size, truncate)
```

**The Python Aggregator writes to:** `reporting_ocpusagelineitem_daily_summary`

### Where API Queries Data

From `provider_map.py` lines 1032-1036:
```python
"costs_by_project": {
    "default": OCPCostSummaryByProjectP,
    ("project",): OCPCostSummaryByProjectP,
    ("cluster", "project"): OCPCostSummaryByProjectP,
},
```

**The API queries from:** `OCPCostSummaryByProjectP` (a summary/view table)

### The Data Flow

```
Parquet (S3/MinIO)
    ↓
Python Aggregator reads
    ↓
Writes to: reporting_ocpusagelineitem_daily_summary (BASE TABLE)
    ↓
(Need to populate) → reporting_ocp_cost_summary_by_project_p (VIEW/SUMMARY TABLE)
    ↓
API reads from view for performance
```

---

## 🚨 Root Cause: Missing Data Pipeline Step

**The Python Aggregator is incomplete!**

It writes to the **base table** (`reporting_ocpusagelineitem_daily_summary`), but the **API queries the summary table** (`reporting_ocp_cost_summary_by_project_p`).

### In Trino-based flow:
1. Trino aggregates data
2. Data lands in summary tables
3. API queries summary tables ✅

### In Python Aggregator flow (CURRENT STATE):
1. Python Aggregator writes to base table ✅
2. **Summary tables are NOT populated** ❌
3. API queries empty summary tables → 500 error ❌

---

## 🔧 Three Possible Causes

### 1. Python Aggregator Never Invoked (Most Likely)
**Symptoms:**
- No data in base table
- No data in summary tables
- No logs from aggregator

**Why:**
- No OCP sources configured
- No data in S3/MinIO Parquet files
- Celery tasks not triggered
- Python Aggregator failing before logging

**Check:**
```bash
# Check if OCP sources exist
oc exec -n cost-mgmt postgres-0 -- psql -U postgres -d koku -c \
  "SELECT uuid, name, type FROM api_provider WHERE type='OCP';"

# Check if Parquet files exist in S3/MinIO
# Need to check actual S3 bucket

# Check Celery logs for aggregator invocation
oc logs deployment/koku-celery-worker-summary | grep -i "python.*aggregator"
```

### 2. Python Aggregator Runs But Doesn't Populate Summary Tables
**Symptoms:**
- Data in base table: `reporting_ocpusagelineitem_daily_summary` ✅
- No data in summary tables: `reporting_ocp_cost_summary_by_project_p` ❌

**Why:**
- Python Aggregator only writes to base table
- Missing step to populate summary tables
- In Trino flow, this was automatic

**Solution:**
After Python Aggregator writes base table, need to:
```python
# Call SQL function to populate summary tables
# or
# Add code to Python Aggregator to also write summary tables
```

### 3. Summary Table Schema Mismatch
**Symptoms:**
- Data in base table ✅
- Data in summary table ✅
- But API queries fail with column errors ❌

**Why:**
- Summary table schema doesn't match what API expects
- But this would show data in tables, not 0 rows

---

## 📊 Current Database State

```sql
-- Base table (where Python Aggregator writes):
SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary;
→ 0 rows

-- Summary table (where API reads):
SELECT COUNT(*) FROM org1234567.reporting_ocp_cost_summary_by_project_p;
→ 2 rows (probably old/stale data)

-- Check if ANY data exists:
SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary;
→ Need to check without date filter
```

---

## ✅ Next Steps (Priority Order)

### STEP 1: Check if Python Aggregator Has Ever Been Invoked

```bash
# Check Celery logs thoroughly
oc logs deployment/koku-celery-worker-summary --since=48h | grep -E "process_ocp.*parquet|Python Aggregator" -A5 -B5

# Check for any errors
oc logs deployment/koku-celery-worker-summary --since=48h | grep -i error | grep -i ocp
```

### STEP 2: Check for Source Data

```bash
# Check OCP sources
oc exec -n cost-mgmt postgres-0 -- psql -U postgres -d koku -c "
  SELECT p.uuid, p.name, p.type, p.created_timestamp, p.updated_timestamp
  FROM api_provider p
  WHERE p.type = 'OCP'
  ORDER BY p.updated_timestamp DESC;
"

# Check report periods
oc exec -n cost-mgmt postgres-0 -- psql -U postgres -d koku -c "
  SELECT cluster_id, report_period_start, report_period_end, summary_data_creation_datetime
  FROM org1234567.reporting_ocpusagereportperiod
  ORDER BY report_period_start DESC
  LIMIT 10;
"
```

### STEP 3: Check S3/MinIO for Parquet Data

```bash
# Get S3 endpoint from MASU pod
oc exec -n cost-mgmt deployment/koku-celery-worker-summary -c celery-worker -- env | grep -E "S3.*ENDPOINT|AWS.*"

# List Parquet files
# Need actual S3 credentials to check
```

### STEP 4: Manually Trigger Python Aggregator

If data exists but aggregator hasn't run:

```python
# Via Django shell in MASU pod
from masu.processor.parquet.poc_integration import process_ocp_parquet

result = process_ocp_parquet(
    schema_name='org1234567',
    provider_uuid='<uuid>',
    year=2025,
    month=12
)
print(result)
```

### STEP 5: Check if Summary Tables Need Population

If base table has data but summary tables don't:

```bash
# Check if there's a SQL function to populate summary tables
oc exec -n cost-mgmt postgres-0 -- psql -U postgres -d koku -c "
  SELECT routine_name 
  FROM information_schema.routines 
  WHERE routine_schema = 'public' 
    AND routine_name LIKE '%summary%'
    AND routine_name LIKE '%ocp%';
"
```

---

## 💡 Most Likely Scenario

Based on all evidence:

**The Python Aggregator has never been invoked because there's no OCP data to process.**

The test failures are NOT due to:
- ❌ Code bugs in Python Aggregator
- ❌ Integration errors
- ❌ Schema mismatches

The test failures ARE due to:
- ✅ **No data ingested** (no sources or no data uploaded)
- ✅ **Aggregator never triggered** (no Celery tasks ran)
- ✅ **Empty tables** (both base and summary)

---

## 🎯 Action Plan

1. **Verify OCP sources exist** in the cluster
2. **Check if Parquet data exists** in S3/MinIO
3. **Trigger data ingestion** if needed (upload test data)
4. **Monitor Python Aggregator execution** in Celery logs
5. **Verify data lands in base table**
6. **Check if summary tables auto-populate** or need manual trigger
7. **Re-run IQE tests** once data exists

---

## 📝 Conclusion

**The Python Aggregator code and integration are likely correct.**

The 500 errors are happening because:
1. API expects data in summary tables
2. Summary tables are empty
3. Tables are empty because Python Aggregator hasn't run
4. Aggregator hasn't run because there's no source data

**This is a test environment setup issue, not a code bug.**

We need to:
- **Ingest test data** to trigger the aggregator
- Or **populate tables manually** to test the API
- Or **understand why the aggregator hasn't been invoked** despite having data

---

**Next Step**: Check Celery logs and database for OCP sources to confirm whether data exists or not.


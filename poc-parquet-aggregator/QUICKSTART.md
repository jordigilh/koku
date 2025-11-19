# Quick Start Guide

## Prerequisites

- Python 3.9+
- Access to OpenShift cluster with Cost Management deployed
- S3/MinIO credentials
- PostgreSQL credentials
- OCP provider with Parquet data already uploaded

## Installation

### 1. Install Dependencies

```bash
cd poc-parquet-aggregator
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example environment file and edit it:

```bash
cp env.example .env
# Edit .env with your credentials
```

**Required Variables**:
- `S3_ENDPOINT`: S3/MinIO endpoint URL
- `S3_ACCESS_KEY`: S3 access key
- `S3_SECRET_KEY`: S3 secret key
- `POSTGRES_HOST`: PostgreSQL host
- `POSTGRES_PASSWORD`: PostgreSQL password
- `POSTGRES_SCHEMA`: Tenant schema (e.g., "org1234567")
- `OCP_PROVIDER_UUID`: Provider UUID
- `OCP_CLUSTER_ID`: Cluster ID

### 3. Load Environment Variables

```bash
export $(cat .env | xargs)
```

## Running the POC

### Basic Run

```bash
python -m src.main
```

### With Truncate (Fresh Start)

```bash
python -m src.main --truncate
```

This will truncate the summary table before inserting new data.

### Custom Config

```bash
python -m src.main --config /path/to/config.yaml
```

## Expected Output

The POC will execute these phases:

1. **Initialize components** - Connect to S3 and PostgreSQL
2. **Fetch enabled tag keys** - Read from PostgreSQL
3. **Read Parquet files** - Load pod usage, node labels, namespace labels
4. **Calculate capacity** - Node and cluster capacity
5. **Aggregate** - Perform aggregation logic
6. **Write to PostgreSQL** - Insert summary rows
7. **Validate** - Check results

### Success Output

```
================================================================================
POC COMPLETED SUCCESSFULLY
================================================================================
Total duration: 45.2s
Input rows: 1,234,567
Output rows: 12,345
Compression ratio: 100.0x
Processing rate: 27,326 rows/sec
================================================================================
```

## Troubleshooting

### S3 Connectivity Failed

- Check `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- Verify SSL certificate if using HTTPS
- Check network connectivity to S3 endpoint

### Database Connectivity Failed

- Check `POSTGRES_HOST`, `POSTGRES_PASSWORD`
- Verify PostgreSQL is accessible
- Check schema exists: `POSTGRES_SCHEMA`

### No Parquet Files Found

- Verify provider UUID is correct: `OCP_PROVIDER_UUID`
- Check year/month: `OCP_YEAR`, `OCP_MONTH`
- Verify Parquet files exist in S3:
  ```
  s3://{bucket}/data/{provider_uuid}/{year}/{month}/
  ```

### Empty Results

- Check date range: `OCP_START_DATE`, `OCP_END_DATE`
- Verify pod usage data exists in Parquet files
- Check filters (enabled tags, cost categories)

## Validation

After a successful run, validate the results in PostgreSQL:

```sql
-- Connect to PostgreSQL
psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB

-- Check row count
SELECT COUNT(*) 
FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '<your-provider-uuid>'
  AND year = '2025'
  AND month = '11';

-- Check aggregates
SELECT 
    usage_start,
    COUNT(*) as row_count,
    SUM(pod_usage_cpu_core_hours) as total_cpu,
    SUM(pod_usage_memory_gigabyte_hours) as total_memory
FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '<your-provider-uuid>'
  AND year = '2025'
  AND month = '11'
GROUP BY usage_start
ORDER BY usage_start;

-- Sample data
SELECT 
    usage_start,
    namespace,
    node,
    pod_usage_cpu_core_hours,
    pod_usage_memory_gigabyte_hours
FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '<your-provider-uuid>'
  AND year = '2025'
  AND month = '11'
LIMIT 10;
```

## Comparing with Trino

To validate correctness, compare POC results with Trino:

### 1. Run Trino SQL (via Koku MASU)

The original Trino SQL is in:
```
koku/masu/database/trino_sql/reporting_ocpusagelineitem_daily_summary.sql
```

### 2. Compare Aggregates

```sql
-- POC results
SELECT SUM(pod_usage_cpu_core_hours) FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '<uuid>' AND year = '2025' AND month = '11';

-- Compare with Trino execution (use same filters)
```

Expected: Results should match within 0.01% tolerance.

## Performance Benchmarks

Track these metrics:

| Metric | Target | Your Result |
|--------|--------|-------------|
| Total time | < 60s | ______ s |
| Read Parquet | < 10s | ______ s |
| Aggregation | < 30s | ______ s |
| Write PostgreSQL | < 10s | ______ s |
| Peak memory | < 2 GB | ______ MB |

## Next Steps

1. ✅ **Run basic POC** - Verify it works end-to-end
2. ⏳ **Measure performance** - Compare with target benchmarks
3. ⏳ **Validate correctness** - Compare with Trino results
4. ⏳ **Test edge cases** - Large clusters, missing labels, etc.
5. ⏳ **Optimize** - Identify bottlenecks and improve

## Support

For issues or questions:
1. Check the `README.md` for detailed documentation
2. Review `docs/TRINO_SQL_ANALYSIS.md` for SQL logic breakdown
3. Enable DEBUG logging: `export LOG_LEVEL=DEBUG`


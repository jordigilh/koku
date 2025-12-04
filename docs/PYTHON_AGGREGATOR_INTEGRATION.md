# Python Aggregator Integration with Koku

## Overview

The Python Aggregator (formerly "POC Aggregator") is now fully integrated into koku as an alternative to Trino-based OCP and OCP-on-AWS data processing. This document explains the architecture, changes made, and how to use the aggregator.

## Architecture

### Before Integration (Standalone POC)

```
┌─────────────────────────────────────────────────────────────┐
│                    Standalone POC                            │
├─────────────────────────────────────────────────────────────┤
│  config.yaml ──► config_loader.py                           │
│       │                                                      │
│       ▼                                                      │
│  s3_adapter.py (s3fs) ──► ParquetReader                     │
│       │                                                      │
│       ▼                                                      │
│  db_adapter.py (psycopg2) ──► DatabaseWriter                │
│       │                                                      │
│       ▼                                                      │
│  Aggregators (config dict API)                              │
└─────────────────────────────────────────────────────────────┘
```

### After Integration (Koku Native)

```
┌─────────────────────────────────────────────────────────────┐
│                    Koku Integration                          │
├─────────────────────────────────────────────────────────────┤
│  django.conf.settings ──► ParquetReader                     │
│       │                    (boto3 via get_s3_resource)      │
│       ▼                                                      │
│  Django ORM + connection ──► DatabaseWriter                 │
│       │                      (django.db.connection)         │
│       ▼                                                      │
│  Aggregators (koku-native parameter API)                    │
│       │                                                      │
│       ▼                                                      │
│  poc_integration.py ──► Celery Tasks                        │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
koku/masu/processor/parquet/
├── python_aggregator/           # Renamed from poc_aggregator
│   ├── __init__.py             # Module exports
│   ├── aggregator_pod.py       # OCP pod usage aggregation
│   ├── aggregator_storage.py   # OCP storage aggregation
│   ├── aggregator_unallocated.py # Unallocated capacity
│   ├── aggregator_ocp_aws.py   # OCP-on-AWS cost attribution
│   ├── parquet_reader.py       # S3 Parquet reading (boto3)
│   ├── db_writer.py            # PostgreSQL writing (Django)
│   ├── resource_matcher.py     # AWS↔OCP resource matching
│   ├── tag_matcher.py          # AWS↔OCP tag matching
│   ├── cost_attributor.py      # Cost distribution logic
│   ├── network_cost_handler.py # Network cost handling
│   ├── disk_capacity_calculator.py # EBS capacity
│   ├── streaming_processor.py  # Chunk-based processing
│   └── utils.py                # Shared utilities
└── poc_integration.py          # Integration layer (will be renamed)
```

## Key Changes

### 1. Removed Standalone Configuration

**Deleted files:**
- `config_loader.py` - YAML config loading
- `s3_adapter.py` - Standalone S3 client
- `db_adapter.py` - Standalone DB connection

**Reason:** These were bridges for standalone operation. Now we use koku's native configuration.

### 2. ParquetReader Refactored

**Before (s3fs-based):**
```python
class ParquetReader:
    def __init__(self, config: Dict):
        s3_config = config["s3"]
        self.fs = s3fs.S3FileSystem(
            key=s3_config["access_key"],
            secret=s3_config["secret_key"],
            endpoint_url=s3_config["endpoint"],
        )
```

**After (koku boto3-based):**
```python
class ParquetReader:
    def __init__(self, schema_name: str):
        self.schema = schema_name
        # Uses koku's settings
        self.endpoint = settings.S3_ENDPOINT
        self.bucket = settings.S3_BUCKET_NAME
        self.access_key = settings.S3_ACCESS_KEY
        self.secret_key = settings.S3_SECRET

    @property
    def s3_resource(self):
        # Uses koku's S3 utility
        return get_s3_resource(
            self.access_key,
            self.secret_key,
            self.region,
            endpoint_url=self.endpoint,
        )
```

### 3. DatabaseWriter Refactored

**Before (psycopg2-based):**
```python
class DatabaseWriter:
    def __init__(self, config: Dict):
        pg_config = config["postgresql"]
        self.connection = psycopg2.connect(
            host=pg_config["host"],
            port=pg_config["port"],
            database=pg_config["database"],
            user=pg_config["user"],
            password=pg_config["password"],
        )
```

**After (Django-based):**
```python
class DatabaseWriter:
    def __init__(self, schema_name: str):
        self.schema = schema_name
        # Uses Django's connection

    def get_enabled_tag_keys(self) -> List[str]:
        with schema_context(self.schema):
            return list(
                EnabledTagKeys.objects.filter(enabled=True)
                .values_list("key", flat=True)
            )
```

### 4. Aggregator Constructors

**Before (config dict):**
```python
class PodAggregator:
    def __init__(self, config: Dict, enabled_tag_keys: List[str]):
        self.cluster_id = config["ocp"]["cluster_id"]
        self.provider_uuid = config["ocp"]["provider_uuid"]
```

**After (koku-native parameters):**
```python
class PodAggregator:
    def __init__(
        self,
        schema_name: str,
        provider_uuid: str,
        cluster_id: str,
        cluster_alias: str,
        report_period_id: int,
        enabled_tag_keys: List[str],
    ):
        self.schema = schema_name
        self.provider_uuid = provider_uuid
        self.cluster_id = cluster_id
```

### 5. Helper Components Simplified

Components like `ResourceMatcher`, `TagMatcher`, `CostAttributor` no longer take `config: Dict`:

**Before:**
```python
class ResourceMatcher:
    def __init__(self, config: Dict):
        self.config = config  # Stored but never used
```

**After:**
```python
class ResourceMatcher:
    def __init__(self, logger=None):
        self.logger = logger or get_logger("resource_matcher")
```

## Integration Entry Points

### OCP-Only Processing

**File:** `koku/masu/processor/ocp/ocp_report_parquet_summary_updater.py`

```python
USE_PYTHON_AGGREGATOR = os.getenv("USE_PYTHON_AGGREGATOR", "false").lower() == "true"

def update_summary_tables(self, ...):
    if USE_PYTHON_AGGREGATOR:
        return self._update_summary_tables_python()
    return self._update_summary_tables_trino()
```

### OCP-on-AWS Processing

**File:** `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py`

```python
USE_PYTHON_AGGREGATOR = os.getenv("USE_PYTHON_AGGREGATOR", "false").lower() == "true"

def update_aws_summary_tables(self, ...):
    if USE_PYTHON_AGGREGATOR:
        return self._update_aws_summary_tables_python()
    return self._update_aws_summary_tables_trino()
```

### Integration Layer

**File:** `koku/masu/processor/parquet/poc_integration.py`

```python
def process_ocp_parquet(schema_name, provider_uuid, year, month, cluster_id=None):
    """Process OCP parquet data using Python aggregator."""

    # Get provider info from koku's database
    provider_info = get_ocp_provider_info(schema_name, provider_uuid, year, month)

    # Get enabled tag keys using Django ORM
    enabled_tag_keys = get_enabled_tag_keys(schema_name)

    # Initialize aggregators with koku-native API
    pod_agg = PodAggregator(
        schema_name=schema_name,
        provider_uuid=provider_uuid,
        cluster_id=provider_info["cluster_id"],
        cluster_alias=provider_info["cluster_alias"],
        report_period_id=provider_info["report_period_id"],
        enabled_tag_keys=enabled_tag_keys,
    )

    # Run aggregation...


def process_ocp_aws_parquet(schema_name, ocp_provider_uuid, aws_provider_uuid, ...):
    """Process OCP-on-AWS parquet data using Python aggregator."""
    # Similar pattern...
```

## Feature Flag

Enable the Python Aggregator by setting the environment variable:

```bash
USE_PYTHON_AGGREGATOR=true
```

When enabled:
- OCP summary processing uses `PodAggregator`, `StorageAggregator`, `UnallocatedCapacityAggregator`
- OCP-on-AWS summary processing uses `OCPAWSAggregator`

When disabled (default):
- Uses existing Trino-based SQL processing

## Data Flow

### OCP-Only Scenario

```
1. Celery Task triggers OCPReportParquetSummaryUpdater
2. Feature flag check: USE_PYTHON_AGGREGATOR
3. If True:
   a. Get provider info from OCPReportDBAccessor
   b. Get enabled tag keys from EnabledTagKeys model
   c. Read parquet from S3 via ParquetReader (boto3)
   d. Run PodAggregator.aggregate()
   e. Run StorageAggregator.aggregate()
   f. Run UnallocatedCapacityAggregator.calculate_unallocated()
   g. Write to PostgreSQL via DatabaseWriter (Django connection)
4. If False:
   a. Execute Trino SQL queries (existing path)
```

### OCP-on-AWS Scenario

```
1. Celery Task triggers OCPCloudParquetReportSummaryUpdater
2. Feature flag check: USE_PYTHON_AGGREGATOR
3. If True:
   a. Get OCP provider info
   b. Get enabled tag keys
   c. Initialize OCPAWSAggregator
   d. Load OCP data (pod + storage)
   e. Load AWS CUR data
   f. Match by resource ID (ResourceMatcher)
   g. Match by tags (TagMatcher)
   h. Calculate disk capacities (DiskCapacityCalculator)
   i. Attribute costs (CostAttributor)
   j. Handle network costs (NetworkCostHandler)
   k. Write combined results to PostgreSQL
4. If False:
   a. Execute Trino SQL queries (existing path)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_PYTHON_AGGREGATOR` | `false` | Enable Python aggregator |
| `POC_USE_STREAMING` | `false` | Enable streaming mode for large datasets |
| `POC_CHUNK_SIZE` | `100000` | Rows per chunk in streaming mode |
| `POC_PARALLEL_READERS` | `4` | Parallel S3 readers |
| `POC_USE_ARROW_COMPUTE` | `false` | Use PyArrow for label processing |
| `POC_PARALLEL_CHUNKS` | `false` | Parallel chunk processing |
| `POC_MAX_WORKERS` | `4` | Worker threads for parallel ops |

## Database Tables

The Python Aggregator writes to the same tables as Trino:

| Scenario | Target Table |
|----------|-------------|
| OCP Pod | `reporting_ocpusagelineitem_daily_summary` |
| OCP Storage | `reporting_ocpusagelineitem_daily_summary` |
| OCP Unallocated | `reporting_ocpusagelineitem_daily_summary` |
| OCP-on-AWS | `reporting_ocpawscostlineitem_project_daily_summary_p` |

## Testing

### Unit Tests

```bash
cd koku
python manage.py test masu.test.processor.parquet.python_aggregator
```

### Integration Tests

```bash
python manage.py test masu.test.processor.ocp.test_ocp_python_aggregator_integration
```

### E2E Tests with IQE

```bash
# Set feature flag
export USE_PYTHON_AGGREGATOR=true

# Run IQE OCP tests
iqe tests plugin cost_management -k "ocp" --trino
```

## Migration from Trino

1. **Deploy with feature flag disabled** (default)
2. **Run parallel validation**: Process same data with both Trino and Python Aggregator
3. **Compare results**: Ensure output matches within tolerance
4. **Enable feature flag**: `USE_PYTHON_AGGREGATOR=true`
5. **Monitor**: Watch for errors, performance metrics

## Performance Considerations

- **Memory**: Python Aggregator loads data into pandas DataFrames
- **Streaming**: Enable `POC_USE_STREAMING=true` for large datasets
- **Parallelism**: Adjust `POC_PARALLEL_READERS` based on S3 throughput

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure `python_aggregator` directory exists
2. **S3 access**: Verify `S3_*` settings in koku config
3. **DB permissions**: Ensure schema access for Django connection
4. **Memory errors**: Enable streaming mode or increase pod memory

### Logs

Look for log messages prefixed with:
- `Python Aggregator:` - Integration layer
- `aggregator_pod` - Pod aggregation
- `aggregator_storage` - Storage aggregation
- `aggregator_ocp_aws` - OCP-on-AWS aggregation

## Summary of Changes

| Component | Change |
|-----------|--------|
| Directory | `poc_aggregator` → `python_aggregator` |
| S3 Access | `s3fs` → `boto3` via koku's `get_s3_resource()` |
| DB Access | `psycopg2` → Django's `connection` |
| Config | `config.yaml` → Django settings |
| Feature Flag | `USE_POC_AGGREGATOR` → `USE_PYTHON_AGGREGATOR` |
| API | `config: Dict` → koku-native parameters |



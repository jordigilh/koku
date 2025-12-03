# Python Aggregator Integration - Session Handoff

## Overview

This document provides context for continuing the Python Aggregator integration into koku. The Python Aggregator (formerly "POC Aggregator") is a pure Python replacement for Trino-based OCP and OCP-on-AWS data processing.

## End Goal

**Replace Trino SQL queries with pure Python (pandas/numpy) aggregation** for:
1. OCP-only cost processing
2. OCP-on-AWS cost attribution

The koku dev team requires all IQE tests to pass before accepting this integration.

## Current State

### Branch
- **Koku branch**: `poc-parquet-integration-rebased`
- **POC branch**: `main` (reference only - code has been migrated to koku)

### What's Done ✅

1. **Directory renamed**: `poc_aggregator` → `python_aggregator`
2. **Removed standalone adapters**:
   - `config_loader.py` - YAML config loading
   - `s3_adapter.py` - Standalone S3 client (s3fs)
   - `db_adapter.py` - Standalone DB connection (psycopg2)

3. **Refactored for koku-native patterns**:
   - `parquet_reader.py` - Now uses `django.conf.settings` and `get_s3_resource()` from `masu.util.aws.common`
   - `db_writer.py` - Now uses `django.db.connection` and Django ORM
   - All aggregator constructors changed from `config: Dict` to explicit parameters

4. **Feature flag**: `USE_PYTHON_AGGREGATOR=true` (environment variable)

5. **Integration entry points**:
   - `koku/masu/processor/ocp/ocp_report_parquet_summary_updater.py` - OCP-only
   - `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py` - OCP-on-AWS

6. **Documentation**: `docs/PYTHON_AGGREGATOR_INTEGRATION.md`

### What's In Progress 🔄

**Import errors need fixing** - Several files are missing `Dict` in their typing imports:

```
NameError: name 'Dict' is not defined
File: aws_data_loader.py, line 523
```

**Files to check and fix** (add `Dict` to typing imports):
- `koku/masu/processor/parquet/python_aggregator/aws_data_loader.py`
- Any other file with `Dict` type hints but missing import

### What's Remaining ❌

1. **Fix all import errors** in python_aggregator modules
2. **Run koku unit tests** to ensure stability
3. **Build new image** with fixes
4. **Deploy to cluster** (namespace: `cost-mgmt`)
5. **Run IQE tests** for OCP-only and OCP-on-AWS scenarios
6. **Fix any test failures**
7. **Get dev team approval**

## Cluster Information

- **Namespace**: `cost-mgmt`
- **API Route**: `http://koku-api-cost-mgmt.apps.stress.parodos.dev`
- **Image Registry**: `quay.io/jordigilh/koku:python-aggregator`

### Key Deployments to Update
```bash
# Summary workers (handle aggregation tasks)
koku-celery-worker-summary
koku-celery-worker-summary-penalty
koku-celery-worker-summary-xl

# OCP workers
koku-celery-worker-ocp
koku-celery-worker-ocp-penalty
koku-celery-worker-ocp-xl
```

### Build Process
```bash
# Build on remote Fedora host (amd64)
ssh -p 2022 jgil@localhost "cd ~/koku-build && podman build -t quay.io/jordigilh/koku:python-aggregator -f Dockerfile ."

# Push to registry
ssh -p 2022 jgil@localhost "podman push quay.io/jordigilh/koku:python-aggregator"

# Update deployments
oc set image deployment/koku-celery-worker-summary celery-worker=quay.io/jordigilh/koku:python-aggregator -n cost-mgmt
oc set env deployment/koku-celery-worker-summary USE_PYTHON_AGGREGATOR=true -n cost-mgmt
```

## Directory Structure

```
koku/masu/processor/parquet/
├── python_aggregator/           # Main aggregator package
│   ├── __init__.py             # Exports: PodAggregator, StorageAggregator, etc.
│   ├── aggregator_pod.py       # OCP pod usage aggregation
│   ├── aggregator_storage.py   # OCP storage aggregation
│   ├── aggregator_unallocated.py # Unallocated capacity
│   ├── aggregator_ocp_aws.py   # OCP-on-AWS cost attribution (main orchestrator)
│   ├── parquet_reader.py       # S3 Parquet reading (boto3, koku settings)
│   ├── db_writer.py            # PostgreSQL writing (Django connection)
│   ├── aws_data_loader.py      # AWS CUR data loading
│   ├── resource_matcher.py     # AWS↔OCP resource ID matching
│   ├── tag_matcher.py          # AWS↔OCP tag matching
│   ├── cost_attributor.py      # Cost distribution logic
│   ├── network_cost_handler.py # Network cost handling
│   ├── disk_capacity_calculator.py # EBS capacity calculations
│   ├── streaming_processor.py  # Chunk-based processing
│   └── utils.py                # Logging, helpers (no longer uses structlog)
└── poc_integration.py          # Integration layer for Celery tasks
```

## Key Files Changed

### Feature Flag Entry Points
```python
# koku/masu/processor/ocp/ocp_report_parquet_summary_updater.py
USE_PYTHON_AGGREGATOR = os.getenv("USE_PYTHON_AGGREGATOR", "false").lower() == "true"

def update_summary_tables(self, ...):
    if USE_PYTHON_AGGREGATOR:
        return self._update_summary_tables_python()
    return self._update_summary_tables_trino()
```

### Aggregator Constructor Pattern
```python
# OLD (config dict)
class PodAggregator:
    def __init__(self, config: Dict, enabled_tag_keys: List[str]):
        self.cluster_id = config["ocp"]["cluster_id"]

# NEW (koku-native parameters)
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
        self.cluster_id = cluster_id
```

## IQE Test Setup

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin

# Environment
export DYNACONF_IQE_VAULT_LOADER_ENABLED=false
export DYNACONF_MAIN__HOSTNAME=koku-api-cost-mgmt.apps.stress.parodos.dev
export DYNACONF_MAIN__PORT=80
export DYNACONF_MAIN__SCHEME=http
export KOKU_API_PATH_PREFIX=/api/cost-management

# Run OCP tests
iqe tests plugin cost_management -k "ocp" --trino
```

## Immediate Next Steps

1. **Fix Dict imports** - Check all python_aggregator/*.py files:
   ```bash
   grep -rn "-> Dict\|: Dict" koku/masu/processor/parquet/python_aggregator/
   ```
   Add `Dict` to typing imports where missing.

2. **Verify imports work** in cluster:
   ```bash
   POD=$(oc get pods -n cost-mgmt -l app=koku-celery-worker-summary -o name | head -1)
   oc exec $POD -n cost-mgmt -c celery-worker -- python -c "
   from masu.processor.parquet.python_aggregator import PodAggregator
   print('OK')
   "
   ```

3. **Run IQE tests** once imports work.

## Related Documents

- `docs/PYTHON_AGGREGATOR_INTEGRATION.md` - Full technical documentation
- `docs/KOKU_INTEGRATION_FINDINGS.md` - Integration findings (in POC repo)
- `docs/KOKU_INTEGRATION_PLAN.md` - Original 7-phase plan (in POC repo)

## Contact

This work is being done to replace Trino-based processing with Python for on-prem deployments where Trino may not be available or is resource-constrained.

---

*Last updated: December 3, 2025*


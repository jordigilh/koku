# Python Aggregator Integration - Session Handoff

## Overview

This document provides context for continuing the Python Aggregator integration into koku. The Python Aggregator (formerly "POC Aggregator") is a pure Python replacement for Trino-based OCP and OCP-on-AWS data processing.

## End Goal

**Replace Trino SQL queries with pure Python (pandas/numpy) aggregation** for:
1. OCP-only cost processing
2. OCP-on-AWS cost attribution

**Success Criteria**: OCP-only and OCP-on-AWS **end-to-end tests must pass**. The koku dev team requires these e2e tests (run via IQE framework) to pass before accepting this integration.

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

## Questions for Handoff Team ❓

**Please answer these questions before shutting down your work:**

### 1. Import Errors Status
- **Q**: The document mentions `NameError: name 'Dict' is not defined` in `aws_data_loader.py` line 523.
  - Have you confirmed this error actually occurs when running the code?
  - When/where did you encounter this error? (cluster pod? local testing? CI/CD?)
  - I verified that `aws_data_loader.py` line 16 has `from typing import Iterator, List, Optional` (missing `Dict`), and line 523 uses `-> Dict`. Is this the exact error you saw?

**A**: Yes, confirmed. The error occurs when running in the **cluster pod**. I tested by exec'ing into `koku-celery-worker-summary-*` and running:
```python
from masu.processor.parquet.python_aggregator import PodAggregator
```
The exact traceback was:
```
File "/opt/koku/koku/masu/processor/parquet/python_aggregator/aws_data_loader.py", line 523, in AWSDataLoader
    def get_aws_resource_summary(self, df: pd.DataFrame) -> Dict:
NameError: name 'Dict' is not defined
```
Yes, your verification is correct - line 16 is missing `Dict` in the import.

### 2. Testing Status
- **Q**: Have you attempted to run any tests since the refactoring?
  - Local unit tests?
  - Cluster deployment?
  - IQE tests?
  - If yes, what were the results/errors?

**A**: 
- **Local unit tests**: Could not run locally because Django is not installed on the Mac - the tests require Django environment.
- **Cluster deployment**: Yes, deployed multiple times. Got as far as verifying the image deploys and `USE_PYTHON_AGGREGATOR=true` is set. Import tests fail due to the `Dict` error.
- **IQE tests**: Not yet - blocked by import errors. Once imports work, IQE tests are next.
- **Python syntax check**: All `.py` files pass `python3 -m py_compile` locally.

### 3. Build/Deploy Status
- **Q**: Has the `quay.io/jordigilh/koku:python-aggregator` image been built with the current `poc-parquet-integration-rebased` branch code?
  - If yes, when was it last built?
  - If no, is the remote Fedora build host (ssh -p 2022 jgil@localhost) still accessible?

**A**: 
- **Yes**, the image has been built and pushed multiple times today (Dec 3, 2025).
- **Last build**: ~30 minutes ago, but it still has the `Dict` import bug (I fixed `aggregator_pod.py` and `utils.py` but haven't rebuilt since discovering `aws_data_loader.py` also needs fixing).
- **Build host**: Yes, `ssh -p 2022 jgil@localhost` is accessible. The koku source is synced to `~/koku-build/` on that host.

### 4. Cluster Status
- **Q**: What is the current state of the `cost-mgmt` namespace?
  - Are any deployments currently using `USE_PYTHON_AGGREGATOR=true`?
  - Are any deployments using the `python-aggregator` image tag?
  - Should I reset everything to baseline before testing?

**A**:
- **USE_PYTHON_AGGREGATOR=true**: Yes, set on `koku-celery-worker-summary`, `koku-celery-worker-ocp` and their penalty/xl variants.
- **python-aggregator image**: Yes, those same deployments are using `quay.io/jordigilh/koku:python-aggregator`.
- **Reset recommendation**: No need to reset. The feature flag means Trino is still the default. Just fix the imports, rebuild, and the pods will work. If you want a clean slate, set `USE_PYTHON_AGGREGATOR=false` on all deployments.
- **Replica count**: All workers scaled to 1 replica due to cluster memory constraints.

### 5. Known Issues
- **Q**: Beyond the `Dict` import issue, are there any other known problems?
  - Other import errors?
  - Runtime errors discovered during testing?
  - Integration issues with koku's Celery tasks?
  - Database schema mismatches?

**A**:
- **Other import errors**: 
  - Fixed: `structlog` was used in `utils.py` - replaced with standard `logging` module.
  - Fixed: `Dict` missing in `aggregator_pod.py` - added to imports.
  - **Still broken**: `Dict` missing in `aws_data_loader.py` (and possibly other files).
- **Runtime errors**: Not reached yet - blocked by import errors.
- **Celery integration**: Not tested yet - the integration entry points exist in `ocp_report_parquet_summary_updater.py` and `ocp_cloud_parquet_summary_updater.py` but haven't been exercised.
- **Database schema**: No mismatches expected - the Python Aggregator writes to the same tables as Trino.

### 6. Code Completeness
- **Q**: The "What's In Progress" section only mentions import errors. Is the actual aggregation logic complete?
  - Have you verified that the refactored code (using Django settings, Django DB connection) works end-to-end in a koku environment?
  - Or is this untested since the refactoring from standalone POC to koku integration?

**A**:
- **Logic complete**: Yes, the aggregation logic is complete. It was working as a standalone POC before integration.
- **End-to-end verified**: **No** - the refactored code has NOT been tested end-to-end in koku yet. The refactoring (Django settings, Django DB connection) is done but untested due to import errors.
- **Risk assessment**: Medium risk. The logic is proven, but the plumbing (S3 access via koku's `get_s3_resource()`, DB access via Django's `connection`) is new and untested.

### 7. Documentation Accuracy
- **Q**: Is everything in this handoff document accurate and up-to-date?
  - Are the file paths correct?
  - Are the integration entry points (`ocp_report_parquet_summary_updater.py`, `ocp_cloud_parquet_summary_updater.py`) actually implemented?
  - Is `docs/PYTHON_AGGREGATOR_INTEGRATION.md` complete and accurate?

**A**:
- **File paths**: Yes, all paths are correct.
- **Integration entry points**: Yes, implemented. Check lines ~98 and ~166 in those files for `USE_PYTHON_AGGREGATOR` checks.
- **PYTHON_AGGREGATOR_INTEGRATION.md**: Yes, complete and accurate as of Dec 3.

### 8. Success Criteria
- **Q**: What exactly needs to pass for this to be considered "done"?
  - All IQE tests with `--trino` flag?
  - Specific test scenarios?
  - Performance benchmarks?
  - Dev team code review?

**A**:
- **E2E tests**: **OCP-only and OCP-on-AWS end-to-end tests must pass.** This means the full pipeline: data ingestion → Python Aggregator processing → correct results in PostgreSQL → API returns correct data.
- **IQE tests**: The dev team requested IQE tests run against koku with the Python Aggregator before they will consider it.
- **Specific scenarios**: Start with OCP-only, then OCP-on-AWS.
- **Performance**: Not explicitly required, but the POC was benchmarked favorably against Trino.
- **Code review**: Likely required, but e2e tests passing is the gate to get there.

### 9. Rollback Plan
- **Q**: If the Python Aggregator doesn't work, what's the rollback procedure?
  - Just set `USE_PYTHON_AGGREGATOR=false`?
  - Revert to a specific image tag?
  - Any database migrations that need to be undone?

**A**:
- **Rollback**: Yes, just set `USE_PYTHON_AGGREGATOR=false`. The feature flag is the safety mechanism.
- **Image**: You can also revert to `quay.io/jordigilh/koku:poc-test` (previous working image without Python Aggregator integration) or the original koku image.
- **Database migrations**: None. The Python Aggregator writes to existing tables with existing schema. No migrations needed.

### 10. Timeline/Urgency
- **Q**: What's the timeline for this work?
  - Is there a deadline for getting IQE tests passing?
  - Is the dev team actively waiting for this?
  - Can I take time to thoroughly test, or is this urgent?

**A**:
- **Deadline**: Not explicitly stated, but the user has been actively working on this for days and wants it done.
- **Dev team waiting**: Yes, the koku dev team is waiting for IQE test results before reviewing.
- **Urgency**: Medium-high. Fix the imports, test, and report back. Don't rush and break things, but don't delay unnecessarily.

---

## Handoff Checklist

**Before the other team shuts down, please confirm:**

- [x] All questions above are answered ✅
- [x] Current branch state is committed and pushed ✅ (branch: `poc-parquet-integration-rebased`)
- [x] Any uncommitted work is documented ✅ (need to fix `Dict` in `aws_data_loader.py`)
- [x] Access credentials (cluster, registry, build host) are verified working ✅
- [x] Known blockers are clearly documented ✅ (`Dict` import errors)
- [x] Success criteria are explicitly defined ✅ (OCP-only and OCP-on-AWS **e2e tests** must pass)

---

## Quick Start for New Session

```bash
# 1. Fix the Dict import in aws_data_loader.py
cd /Users/jgil/go/src/github.com/insights-onprem/koku
grep -n "from typing import" koku/masu/processor/parquet/python_aggregator/aws_data_loader.py
# Add Dict to that import line

# 2. Check for any other files with Dict usage but missing import
grep -rn "-> Dict\|: Dict" koku/masu/processor/parquet/python_aggregator/ | grep -v "from typing"

# 3. Sync to build host and rebuild
rsync -avz -e "ssh -p 2022" koku/ jgil@localhost:~/koku-build/
ssh -p 2022 jgil@localhost "cd ~/koku-build && podman build -t quay.io/jordigilh/koku:python-aggregator -f Dockerfile . && podman push quay.io/jordigilh/koku:python-aggregator"

# 4. Restart workers
oc rollout restart deployment/koku-celery-worker-summary -n cost-mgmt
oc rollout restart deployment/koku-celery-worker-ocp -n cost-mgmt

# 5. Test imports in pod
POD=$(oc get pods -n cost-mgmt --no-headers | grep "celery-worker-summary-" | grep Running | head -1 | awk '{print $1}')
oc exec $POD -n cost-mgmt -c celery-worker -- python -c "from masu.processor.parquet.python_aggregator import PodAggregator; print('OK')"

# 6. If imports work, run IQE tests (from iqe-cost-management-plugin directory)
```

---

## Contact

This work is being done to replace Trino-based processing with Python for on-prem deployments where Trino may not be available or is resource-constrained.

---

*Last updated: December 3, 2025*


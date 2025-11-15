# Environment Validation Results

**Date**: November 11, 2025
**Status**: 🔴 **BLOCKED** - Critical issue found

---

## ✅ Passed Validations

### Phase 1: Infrastructure
- ✅ **1.1 Cluster Access**: PASSED
  - Cluster: `api.stress.parodos.dev:6443`
  - Namespace: `cost-mgmt` (Active)
  - Context: `cost-mgmt/api-stress-parodos-dev:6443/kube:admin`

- ✅ **1.2 Pod Health**: PASSED
  - All 24 pods Running
  - 1 migration job Completed (expected)
  - No pods in Error/CrashLoopBackOff state

- ✅ **1.3 Database Migration**: PASSED
  - Migration job completed successfully
  - "Migration completed successfully" in logs
  - Hive role error is expected and handled

### Phase 3: API
- ✅ **3.1 API Accessibility**: PASSED
  - API responds on `localhost:8000`
  - Status endpoint returns valid JSON
  - API version: 1
  - Python version: 3.11.11

---

## ❌ Failed Validations

### Phase 3: API Authentication

**Status**: ❌ **FAILED** - CRITICAL BLOCKER

**Issue**: API returns `401 Unauthorized` when using `x-rh-identity` header

**Root Cause**: `DEVELOPMENT` environment variable is set to `False` instead of `True`

**Evidence**:
```bash
$ kubectl get deployment -n cost-mgmt cost-mgmt-cost-management-onprem-koku-api-reads \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEVELOPMENT")]}'

{
  "name": "DEVELOPMENT",
  "value": "False"
}
```

**Impact**:
- 🔴 API requires RBAC service for authentication (not available on-prem)
- 🔴 Cannot test API endpoints
- 🔴 Cannot create providers
- 🔴 Cannot run IQE tests
- 🔴 **BLOCKS MIGRATION IMPLEMENTATION**

**Expected Configuration**:
```yaml
env:
  - name: DEVELOPMENT
    value: "True"  # Must be string "True", not boolean
```

---

## 🔧 Required Fix

### Fix Location

**File**: `/Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart/cost-management-onprem/values-koku.yaml`

**Current Configuration** (INCORRECT):
```yaml
costManagement:
  api:
    reads:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "False"  # ❌ WRONG - Should be "True"
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

    writes:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "False"  # ❌ WRONG - Should be "True"
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"
```

**Required Configuration** (CORRECT):
```yaml
costManagement:
  api:
    reads:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "True"  # ✅ CORRECT - Enables on-prem auth bypass
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

    writes:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "True"  # ✅ CORRECT - Enables on-prem auth bypass
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"
```

### Why This Matters

When `DEVELOPMENT=True`:
- ✅ API accepts `x-rh-identity` header without RBAC validation
- ✅ No external RBAC service required
- ✅ Suitable for on-prem deployments
- ✅ Enables testing and development

When `DEVELOPMENT=False` (current state):
- ❌ API requires RBAC service for authorization
- ❌ `x-rh-identity` header alone is insufficient
- ❌ Designed for SaaS environments only
- ❌ Blocks all API testing

---

## 🚀 Remediation Steps

### Step 1: Update Helm Values

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart

# Edit values-koku.yaml
# Change DEVELOPMENT: "False" to DEVELOPMENT: "True" in both api.reads and api.writes
```

### Step 2: Upgrade Helm Release

```bash
helm upgrade cost-mgmt ./cost-management-onprem \
    -n cost-mgmt \
    -f cost-management-onprem/values-koku.yaml
```

### Step 3: Wait for Rollout

```bash
# Wait for API pods to restart
kubectl rollout status deployment/cost-mgmt-cost-management-onprem-koku-api-reads -n cost-mgmt
kubectl rollout status deployment/cost-mgmt-cost-management-onprem-koku-api-writes -n cost-mgmt
```

### Step 4: Verify Fix

```bash
# Check DEVELOPMENT env var
kubectl get deployment -n cost-mgmt cost-mgmt-cost-management-onprem-koku-api-reads \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEVELOPMENT")]}'

# Should show: {"name":"DEVELOPMENT","value":"True"}

# Test authentication
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &
sleep 3

IDENTITY=$(echo -n '{"identity":{"account_number":"10001","org_id":"1234567","type":"User","user":{"username":"test","is_org_admin":true}},"entitlements":{"cost_management":{"is_entitled":true}}}' | base64)

curl -s -H "x-rh-identity: $IDENTITY" http://localhost:8000/api/cost-management/v1/providers/ | jq '.meta.count'

# Should return: 0 (or number of providers)
# NOT: 401 Unauthorized
```

---

## ⏸️ Validations Paused

The following validations are paused until the DEVELOPMENT mode fix is applied:

- ⏸️ Phase 3.3: API Endpoints Health
- ⏸️ Phase 4: Trino Validation
- ⏸️ Phase 5: Hive Metastore Validation
- ⏸️ Phase 6: Data Processing Validation
- ⏸️ Phase 7: End-to-End Validation

---

## 📊 Summary

| Phase | Status | Blocker |
|-------|--------|---------|
| 1. Infrastructure | ✅ PASSED | None |
| 2. Database | ⏸️ PAUSED | Waiting for API fix |
| 3. API | ❌ FAILED | DEVELOPMENT=False |
| 4. Trino | ⏸️ PAUSED | Waiting for API fix |
| 5. Hive Metastore | ⏸️ PAUSED | Waiting for API fix |
| 6. Data Processing | ⏸️ PAUSED | Waiting for API fix |
| 7. End-to-End | ⏸️ PAUSED | Waiting for API fix |

**Overall Status**: 🔴 **BLOCKED**

**Critical Blocker**: `DEVELOPMENT=False` in API configuration

**Action Required**: Update `values-koku.yaml` and redeploy

---

## 🎯 Next Steps

1. **IMMEDIATE**: Fix `DEVELOPMENT` environment variable in `values-koku.yaml`
2. **IMMEDIATE**: Redeploy Helm chart
3. **IMMEDIATE**: Re-run validation checklist
4. **AFTER FIX**: Complete remaining validation phases
5. **AFTER VALIDATION**: Proceed with migration implementation

---

**Validated By**: Cost Management Team
**Date**: November 11, 2025
**Status**: Validation incomplete - blocker identified




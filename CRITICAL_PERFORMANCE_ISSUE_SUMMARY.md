# Critical Performance Issue - Code Changes Causing 600x Slowdown

**Status**: 🔴 **CRITICAL - BLOCKING E2E TESTING**
**Date**: November 10, 2025
**Impact**: `/status/` endpoint timeout causing pod readiness failures

---

## 🎯 Problem Summary

Our code changes are causing the `/status/` endpoint to become **600x slower**:
- **Old pods (upstream code)**: 0.04 seconds ✅
- **New pods (our changes)**: 25+ seconds (timeout) ❌

This prevents pods from passing readiness/liveness probes, blocking deployment and E2E testing.

---

## 📊 Evidence

### Old Pods (Working)
```bash
$ kubectl exec cost-mgmt-...-d8f4b98c4-6vswq -- curl -w "Time: %{time_total}s" http://localhost:8000/api/cost-management/v1/status/
Time: 0.039711s  ✅
```

### New Pods (Failing)
```bash
$ kubectl exec cost-mgmt-...-8456b77b65pn7b9 -- curl -m 25 -w "Time: %{time_total}s" http://localhost:8000/api/cost-management/v1/status/
Time: 25.001159s  ❌ (timeout)
```

### Pod Events
```
Warning  Unhealthy  Readiness probe failed: context deadline exceeded (Client.Timeout exceeded while awaiting headers)
Warning  Unhealthy  Liveness probe failed: context deadline exceeded (Client.Timeout exceeded while awaiting headers)
```

---

## 🔍 Code Changes Analysis

### Files Modified
```bash
$ git diff upstream/main..HEAD --stat
 koku/api/report/view.py    |  2 +-
 koku/koku/feature_flags.py | 56 ++++++++++++++++++++++++++++++++++++----------
 2 files changed, 45 insertions(+), 13 deletions(-)
```

### Change 1: `koku/api/report/view.py` (Bug Fix)
**Purpose**: Fix `CACHE_RH_IDENTITY_HEADER` AttributeError

**Before**:
```python
@method_decorator(vary_on_headers(CACHE_RH_IDENTITY_HEADER))
def get(self, request, **kwargs):
```

**After**:
```python
@method_decorator(vary_on_headers(CACHE_RH_IDENTITY_HEADER()))  # Call function to get header name
def get(self, request, **kwargs):
```

**Impact**: This change is on `ReportView.get()`, not the status endpoint. Unlikely to be the cause.

### Change 2: `koku/koku/feature_flags.py` (Onprem Enhancement)
**Purpose**: Add `UNLEASH_DISABLED` flag for onprem deployments

**Changes**:
1. Added `DisabledUnleashClient` mock class
2. Added `UNLEASH_DISABLED` environment variable check
3. Conditional client creation (mock vs real)

**Code**:
```python
class DisabledUnleashClient:
    """Mock Unleash client that never makes network calls - for onprem deployments"""

    def __init__(self):
        self.unleash_instance_id = "disabled-unleash-client"

    def is_enabled(self, feature_name: str, context: dict = None, fallback_function=None):
        if fallback_function:
            return fallback_function(feature_name, context or {})
        return False

    def initialize_client(self):
        pass

    def destroy(self):
        pass

# Check if Unleash should be disabled for onprem deployments
UNLEASH_DISABLED = ENVIRONMENT.bool("UNLEASH_DISABLED", default=False)

if UNLEASH_DISABLED:
    UNLEASH_CLIENT = DisabledUnleashClient()
    LOG.info("Unleash disabled for onprem deployment - using mock client with zero network calls")
else:
    UNLEASH_CLIENT = KokuUnleashClient(...)
    LOG.debug("Unleash client initialized for SaaS deployment")
```

**Impact**: This is loaded at module import time. If there's an issue with `ENVIRONMENT.bool()` or the conditional logic, it could cause slowness.

---

## 🤔 Possible Root Causes

### Theory 1: Feature Flag Checks in Status Endpoint
The `/status/` endpoint might be checking feature flags, and our `DisabledUnleashClient` might be causing slowness in the fallback logic.

**Test**: Check if status endpoint calls `UNLEASH_CLIENT.is_enabled()`

### Theory 2: Module Import Slowness
The `feature_flags.py` module is imported by many modules. If our changes cause slow imports, it could cascade.

**Test**: Add timing logs to `feature_flags.py` initialization

### Theory 3: Environment Variable Parsing
`ENVIRONMENT.bool("UNLEASH_DISABLED", default=False)` might be slow if it's reading from a slow source.

**Test**: Check `ENVIRONMENT` implementation

### Theory 4: Logging in Module Scope
The `LOG.info()` and `LOG.debug()` calls at module scope might be causing issues if logging isn't fully initialized.

**Test**: Remove logging statements temporarily

### Theory 5: Other Requests Work, Status Doesn't
The logs show "Identity" entries (meaning other requests are being processed), but `/status/` specifically times out.

**Observation**: This suggests the issue is specific to the status endpoint, not a general slowness.

---

## 📋 Recommended Actions

### Immediate (To Unblock Testing)
1. **Option A**: Revert all changes, test with upstream code
2. **Option B**: Revert `feature_flags.py` changes only, keep `view.py` fix
3. **Option C**: Remove `UNLEASH_DISABLED` from Helm values, use real Unleash client

### Investigation (To Fix Properly)
1. Add detailed timing logs to `/status/` endpoint
2. Profile the status endpoint execution
3. Check if status endpoint uses feature flags
4. Test `DisabledUnleashClient` in isolation
5. Compare module import times between old and new code

### Long-Term (Architecture Review)
1. Review with dev team: Is `UNLEASH_DISABLED` the right approach?
2. Consider alternative solutions (see `UNLEASH_DISABLED_FLAG_REVIEW_NEEDED.md`)
3. Add performance tests for critical endpoints

---

## 🔗 Related Files

- `UNLEASH_DISABLED_FLAG_REVIEW_NEEDED.md` - Dev team review needed
- `BUG_REPORT_CACHE_RH_IDENTITY_HEADER.md` - Original bug we were fixing
- `FINAL_STATUS_SUMMARY.md` - Overall deployment status
- `E2E_TESTING_STATUS.md` - E2E testing progress

---

## ✅ Next Steps

**Immediate Action Required**:
1. Decide: Revert changes or investigate further?
2. If reverting: Which changes to keep (if any)?
3. If investigating: Add timing/profiling to identify bottleneck

**Goal**: Get pods healthy so we can run E2E tests

**Priority**: 🔴 **CRITICAL** - Blocking all E2E testing


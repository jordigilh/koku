# UNLEASH_DISABLED Flag - Dev Team Review Needed

**Status**: ⚠️ **Requires Dev Team Review**
**Date**: November 10, 2025
**Author**: Jordi Gil

---

## 🎯 Problem Statement

During onprem deployment testing, we discovered that Koku's Unleash feature flag client was causing application startup failures because:

1. Unleash service doesn't exist in onprem deployments
2. The Unleash client initialization blocks application startup
3. Gunicorn workers fail to boot when Unleash client is misconfigured

---

## 🔧 Current Implementation (Temporary Solution)

### What We Added

**Commit**: `5119414b` (Nov 9, 2025) and `cf794cd9` (Nov 10, 2025)

**Files Modified**:
- `koku/koku/feature_flags.py`

**Changes**:
1. Added `UNLEASH_DISABLED` environment variable (default: `False`)
2. Created `DisabledUnleashClient` mock class that:
   - Returns `False` for all feature flags (or uses fallback functions)
   - Makes **zero network calls**
   - Implements minimal interface for compatibility

**Code**:
```python
class DisabledUnleashClient:
    """Mock Unleash client that never makes network calls - for onprem deployments"""

    def __init__(self):
        # Add attributes that gunicorn_conf.py and other code expects
        self.unleash_instance_id = "disabled-unleash-client"

    def is_enabled(self, feature_name: str, context: dict = None, fallback_function=None):
        # Always use fallback function when disabled (no network calls)
        if fallback_function:
            return fallback_function(feature_name, context or {})
        return False  # Safe default when no fallback provided

    def initialize_client(self):
        # No-op for disabled client (no network calls)
        pass

    def destroy(self):
        pass  # No cleanup needed for mock client

# Check if Unleash should be disabled for onprem deployments
UNLEASH_DISABLED = ENVIRONMENT.bool("UNLEASH_DISABLED", default=False)

# Conditional client creation for onprem vs SaaS
if UNLEASH_DISABLED:
    UNLEASH_CLIENT = DisabledUnleashClient()
    LOG.info("Unleash disabled for onprem deployment - using mock client with zero network calls")
else:
    # Normal SaaS client (unchanged)
    UNLEASH_CLIENT = KokuUnleashClient(...)
```

**Helm Configuration**:
```yaml
# values-koku.yaml
costManagement:
  api:
    reads:
      env:
        UNLEASH_DISABLED: "true"
    writes:
      env:
        UNLEASH_DISABLED: "true"
```

---

## ⚠️ Concerns & Issues

### 1. **Incomplete Interface Implementation**

**Initial Bug**: The `DisabledUnleashClient` was missing attributes that other parts of the codebase expected:
- `unleash_instance_id` (used by `gunicorn_conf.py`)
- `initialize_client()` (used by management commands)

**Impact**: Application failed to start with `AttributeError`

**Fix**: Added missing attributes in commit `cf794cd9`

**Risk**: There may be other attributes/methods we haven't discovered yet that will cause failures in production.

### 2. **Tight Coupling to Unleash Client Interface**

The codebase has tight coupling to the Unleash client interface in multiple places:
- `koku/gunicorn_conf.py` - modifies `unleash_instance_id` in post_fork
- `koku/koku/celery.py` - calls `initialize_client()` in worker init
- `koku/masu/management/commands/listener.py` - calls `initialize_client()`
- `koku/sources/management/commands/sources_listener.py` - calls `initialize_client()`

**Risk**: Any changes to the Unleash client interface upstream will require updates to our mock.

### 3. **Feature Flag Behavior in Onprem**

With `UNLEASH_DISABLED=true`, all feature flags will:
- Return `False` by default
- Use fallback functions if provided
- Never fetch real feature flag state

**Risk**: If any critical features are gated behind feature flags without fallback functions, they will be disabled in onprem.

### 4. **Maintenance Burden**

This approach requires maintaining a mock client that mirrors the real Unleash client interface.

**Risk**: As Koku evolves and adds more Unleash client usage, we'll need to update the mock.

---

## 🤔 Questions for Dev Team

### 1. **Is this the right approach?**
- Should onprem deployments use a mock Unleash client?
- Or should we refactor to make Unleash optional throughout the codebase?

### 2. **What feature flags are critical?**
- Which feature flags are required for basic Koku functionality?
- Can we provide a static configuration file for onprem feature flags?

### 3. **Alternative approaches?**
- **Option A**: Deploy a minimal Unleash instance in onprem (adds complexity)
- **Option B**: Refactor code to make Unleash optional (larger code change)
- **Option C**: Use environment variables instead of feature flags for onprem (simpler)
- **Option D**: Continue with mock client but with better testing (current approach)

### 4. **Testing requirements?**
- How do we ensure the mock client doesn't break in future releases?
- Should we add integration tests for `UNLEASH_DISABLED=true` mode?

---

## 📋 Recommended Actions

### Immediate (For Testing)
1. ✅ Fix `DisabledUnleashClient` to include all required attributes
2. ⏳ Rebuild image and test in onprem deployment
3. ⏳ Verify all API endpoints work with `UNLEASH_DISABLED=true`

### Short-Term (Dev Team Review)
1. Review this approach with dev team
2. Identify all feature flags used in Koku
3. Document which features are affected by `UNLEASH_DISABLED=true`
4. Decide on long-term strategy

### Long-Term (If Approved)
1. Add integration tests for `UNLEASH_DISABLED=true` mode
2. Document onprem-specific configuration
3. Consider refactoring to reduce Unleash coupling

---

## 📊 Impact Analysis

### SaaS Deployments
- ✅ **No impact** - `UNLEASH_DISABLED` defaults to `False`
- ✅ **Backward compatible** - existing behavior unchanged

### Onprem Deployments
- ✅ **Fixes startup issues** - no more Unleash network timeouts
- ⚠️ **Feature flags disabled** - all flags return `False` or use fallbacks
- ⚠️ **Untested in production** - needs thorough testing

---

## 🔗 Related Files

- `koku/koku/feature_flags.py` - Main implementation
- `koku/gunicorn_conf.py` - Uses `unleash_instance_id`
- `koku/koku/celery.py` - Calls `initialize_client()`
- `ros-helm-chart/cost-management-onprem/values-koku.yaml` - Helm configuration
- `BUG_REPORT_CACHE_RH_IDENTITY_HEADER.md` - Related onprem bug
- `koku-onprem-enhancement-roadmap.md` - Onprem enhancement tracking

---

## ✅ Testing Checklist (After Rebuild)

- [ ] Application starts successfully with `UNLEASH_DISABLED=true`
- [ ] All API endpoints respond (no 500 errors)
- [ ] Reports API works (`/reports/aws/costs/`, etc.)
- [ ] Sources API works (`/sources/`)
- [ ] Status endpoint works (`/status/`)
- [ ] MASU processing works (if applicable)
- [ ] No AttributeError or other Unleash-related errors in logs

---

**Next Steps**:
1. Rebuild image with fixed `DisabledUnleashClient`
2. Test in onprem deployment
3. Schedule dev team review meeting
4. Document findings and recommendations

**Priority**: 🔴 **HIGH** - Blocking onprem deployment testing


# Unleash Rate Limiting Investigation

## Problem Summary
Unleash's rate limiting feature is blocking Koku's connection attempts in the on-premise deployment, preventing the system from functioning properly.

## Investigation Timeline

### 1. Initial Rate Limit Encounter
- **Token**: `koku-onprem-token-2024`
- **Issue**: Multiple failed authentication attempts (401 Unauthorized) triggered rate limiting
- **Rate Limit Duration**: 5 minutes per incident
- **Rate Limit Expiry**: Extended with each failed attempt

### 2. Attempted Solution: `RATE_LIMIT_ENABLED=false`
- **Result**: ❌ Failed - Environment variable not recognized by Unleash
- **Evidence**: Rate limiting continued despite setting this variable

### 3. SME Consultation
- **Recommendation**: Use `DISABLE_RATE_LIMIT=true` instead
- **Source**: SME indicated this is the correct variable for disabling Redis-based rate limiting
- **Implementation**: Updated Helm deployment with `DISABLE_RATE_LIMIT=true`

### 4. Testing `DISABLE_RATE_LIMIT=true`
- **Actions Taken**:
  - Set `DISABLE_RATE_LIMIT=true` in Unleash deployment
  - Restarted Redis pod to clear cache
  - Restarted Unleash pod to pick up new environment variable
  - **Result**: ❌ Failed - Rate limiting continued

### 5. Clean Installation Test
- **Actions Taken**:
  - Completely undeployed Unleash
  - Deleted PostgreSQL PVC (`data-cost-mgmt-cost-management-onprem-unleash-db-0`)
  - Created fresh token: `koku-fresh-token-20251110`
  - Redeployed Unleash with clean database and `DISABLE_RATE_LIMIT=true`
- **Result**: ❌ **FAILED - New token was rate-limited immediately upon first connection attempt**

## Critical Finding

**Even with a brand new token on a clean installation with `DISABLE_RATE_LIMIT=true`, rate limiting was triggered immediately.**

This proves that:
1. `DISABLE_RATE_LIMIT=true` does **NOT** work in this version of Unleash
2. The SME's information was either incorrect or applies to a different Unleash version
3. Rate limiting cannot be disabled via environment variables in the current Unleash image

## Evidence

### Fresh Token Rate Limiting (20:08 UTC)
```
[INFO] Token koku-fresh-token-20251110 rate limited until: Mon Nov 10 2025 20:12:55 GMT+0000
```

**This occurred within seconds of deployment on a completely clean installation.**

## Unleash Configuration Details

### Image
- **Repository**: `quay.io/insights-onprem/unleashorg/unleash-server`
- **Tag**: `latest`

### Environment Variables Tested
1. `RATE_LIMIT_ENABLED=false` ❌ Not recognized
2. `DISABLE_RATE_LIMIT=true` ❌ Not effective

### PostgreSQL Version Warning
```
[ERROR] You are running an unsupported version of PostgreSQL: 13.22.
You'll have to upgrade to Postgres 14 or newer to continue getting our support.
```

## Root Cause Analysis

The rate limiting appears to be:
1. **Built into Unleash's core logic** - Not configurable via environment variables
2. **Triggered by authentication failures** - Even valid tokens get rate-limited if there are connection issues
3. **Persistent across restarts** - Stored somewhere (possibly in-memory with a timer)
4. **Applied per-token** - Each token has its own rate limit counter

## Recommended Solution

**Use `DisabledUnleashClient` in Koku's code** (`koku/koku/feature_flags.py`):

### Advantages
✅ Zero network calls to Unleash
✅ No rate limiting issues
✅ Simpler deployment (no Unleash server needed)
✅ Faster startup (no Unleash connection wait)
✅ Already implemented and tested

### Disadvantages
⚠️ Requires code modification in Koku
⚠️ Needs review by Koku dev team
⚠️ Feature flags always return fallback values

## Alternative Solutions Considered

### 1. Wait for Rate Limit to Expire
- **Pros**: Eventually works
- **Cons**: 5-minute delays on every deployment/restart, not acceptable for production

### 2. Deploy Unleash with Pre-configured Database
- **Pros**: Could avoid initial authentication failures
- **Cons**: Still doesn't solve the `DISABLE_RATE_LIMIT` issue, complex to maintain

### 3. Use Different Unleash Version
- **Pros**: Might have working `DISABLE_RATE_LIMIT` flag
- **Cons**: Unknown which version supports it, requires investigation

### 4. Modify Unleash Source Code
- **Pros**: Could disable rate limiting at source level
- **Cons**: Requires maintaining a fork, not sustainable

## SME Confirmation (November 10, 2025)

The Unleash SME confirmed our findings:

> **"There is no officially supported environment variable called DISABLE_RATE_LIMIT in the latest Unleash documentation or community discussions that reliably disables rate limiting globally."**

### SME Recommendations:
1. **Custom Middleware or Code Patch**: Modify Unleash server source code to remove rate limiting middleware
2. **Custom Build**: Fork Unleash and rebuild without rate limiting
3. **No Quick Fix**: No API endpoint or database command to reset rate limits

### Why Custom Unleash Build is NOT Recommended:
- ❌ Requires maintaining a fork of Unleash
- ❌ Ongoing maintenance burden for security updates
- ❌ Complexity in deployment and versioning
- ❌ Not sustainable for long-term support

## Conclusion

**The `DisabledUnleashClient` approach is the ONLY pragmatic solution for on-premise deployments.**

The investigation, confirmed by the Unleash SME, has proven that:
1. Unleash's rate limiting **cannot** be disabled via environment variables
2. Disabling rate limiting requires **forking and modifying Unleash source code**
3. Maintaining a custom Unleash build is **not sustainable**
4. **Modifying Koku to use `DisabledUnleashClient` is simpler, safer, and more maintainable**

## Next Steps

1. ✅ Document findings for dev team review
2. ⏳ Get approval for `DisabledUnleashClient` approach
3. ⏳ Proceed with E2E testing using baseline Koku code + `DisabledUnleashClient`
4. ⏳ Create PR for Koku with `UNLEASH_DISABLED` flag for on-premise deployments

## Files Modified

- `/Users/jgil/go/src/github.com/insights-onprem/koku/koku/koku/feature_flags.py` - Added `DisabledUnleashClient`
- `/Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart/cost-management-onprem/values-koku.yaml` - Unleash configuration
- `/Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart/cost-management-onprem/templates/unleash/*.yaml` - Unleash Helm templates

---

**Investigation Date**: November 10, 2025
**Investigator**: AI Assistant with User
**Status**: ❌ Unleash rate limiting cannot be disabled - Recommend `DisabledUnleashClient` approach


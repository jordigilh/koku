# Unleash Integration Requirements for Koku

**Date**: November 10, 2025
**Purpose**: Document what Koku expects from Unleash before deployment

---

## 📋 Koku's Unleash Usage Analysis

### Environment Variables Koku Uses

From `koku/koku/configurator.py` and `koku/koku/settings.py`:

```python
# Required by Koku
UNLEASH_HOST = ENVIRONMENT.get_value("UNLEASH_HOST", default="unleash")
UNLEASH_PORT = ENVIRONMENT.get_value("UNLEASH_PORT", default="4242")
UNLEASH_TOKEN = ENVIRONMENT.get_value("UNLEASH_TOKEN", default="")  # Optional
UNLEASH_CACHE_DIR = ENVIRONMENT.get_value("UNLEASH_CACHE_DIR", default=".unleash")
UNLEASH_LOGGING_LEVEL = ENVIRONMENT.get_value("UNLEASH_LOG_LEVEL", default="WARNING")

# Constructed URL
UNLEASH_PREFIX = "https" if str(UNLEASH_PORT) == "443" else "http"
UNLEASH_URL = f"{UNLEASH_PREFIX}://{UNLEASH_HOST}:{UNLEASH_PORT}/api"
```

### UnleashClient Initialization

From `koku/koku/feature_flags.py`:

```python
UNLEASH_CLIENT = KokuUnleashClient(
    url=settings.UNLEASH_URL,  # http://unleash:4242/api
    app_name="Cost Management",
    environment=ENVIRONMENT.get_value("KOKU_SENTRY_ENVIRONMENT", default="development"),
    instance_id=ENVIRONMENT.get_value("APP_POD_NAME", default="unleash-client-python"),
    custom_headers=headers,  # Authorization header if UNLEASH_TOKEN is set
    cache_directory=settings.UNLEASH_CACHE_DIR,
    verbose_log_level=log_level,
)
```

---

## 🎯 Feature Flags Used by Koku

Koku uses **17 feature flags** for various backend operations:

### Processing Control Flags
1. `cost-management.backend.disable-cloud-source-processing` - Disable cloud source processing
2. `cost-management.backend.disable-summary-processing` - Disable summary processing
3. `cost-management.backend.disable-ocp-on-cloud-summary` - Disable OCP-on-Cloud summary
4. `cost-management.backend.disable-source` - Disable specific source processing
5. `cost-management.backend.disable-ingress-rate-limit` - Disable ingress rate limiting
6. `cost-management.backend.is_tag_processing_disabled` - Disable tag processing

### Customer Classification Flags
7. `cost-management.backend.large-customer` - Identify large customers
8. `cost-management.backend.penalty-customer` - Identify penalty customers
9. `cost-management.backend.large-customer.rate-limit` - Rate limit for large customers
10. `cost-management.backend.large-customer-cost-model` - Cost model for large customers
11. `cost-management.backend.override_customer_group_by_limit` - Override group-by limits

### Feature Enablement Flags
12. `cost-management.backend.enable-purge-turnpike` - Enable Trino file purging
13. `cost-management.backend.enable_data_validation` - Enable data validation
14. `cost-management.backend.is_status_api_update_enabled` - Enable status API updates
15. `cost-management.backend.subs-data-extraction` - Enable subscription data extraction
16. `cost-management.backend.subs-data-messaging` - Enable subscription messaging
17. `cost-management.backend.hcs-data-processor` - Enable HCS data processing

### Fallback Behavior

Most flags use `fallback_development_true`:
```python
def fallback_development_true(feature_name: str, context: dict) -> bool:
    return context.get("environment", "").lower() == "development"
```

**Implication**: If Unleash is unavailable or a flag doesn't exist, flags return `True` in development environment.

---

## 🔧 What Unleash Server Needs

### 1. Database (PostgreSQL)

Unleash requires PostgreSQL to store:
- Feature toggle definitions
- Strategies
- Client registrations
- Metrics

**Requirements**:
- PostgreSQL 12+ (we have PostgreSQL 13 in Koku)
- Separate database: `unleash` (not `koku`)
- User: `unleash` with full access to `unleash` database

### 2. Environment Variables for Unleash Server

```yaml
DATABASE_URL: postgres://unleash:password@host:5432/unleash
DATABASE_SSL: false  # For internal cluster communication
LOG_LEVEL: info
INIT_CLIENT_API_TOKENS: ""  # Optional: comma-separated list of initial tokens
```

### 3. API Endpoints Unleash Must Provide

Koku's UnleashClient expects these endpoints at `/api`:

- **`GET /api/client/features`** - Fetch all feature toggles
- **`POST /api/client/register`** - Register client instance
- **`POST /api/client/metrics`** - Send usage metrics
- **`GET /api/health`** - Health check (for liveness/readiness probes)

### 4. Initial Feature Toggles (Optional)

For onprem deployments, we can pre-configure feature toggles to safe defaults:

**Recommended defaults for onprem**:
- All `disable-*` flags: `false` (enable all processing)
- All `enable-*` flags: `true` (enable all features)
- All customer classification flags: `false` (no special handling)

**However**: If no toggles are defined, Koku's fallback functions will handle it gracefully.

---

## ✅ Deployment Requirements Checklist

### Unleash Server
- [ ] Deploy Unleash server container (`quay.io/insights-onprem/unleashorg/unleash-server:latest`)
- [ ] Create `unleash` database in PostgreSQL
- [ ] Create `unleash` user with password
- [ ] Configure `DATABASE_URL` environment variable
- [ ] Expose service on port 4242
- [ ] Configure liveness/readiness probes on `/health`

### Koku Configuration
- [ ] Set `UNLEASH_HOST=cost-mgmt-cost-management-onprem-unleash`
- [ ] Set `UNLEASH_PORT=4242`
- [ ] Set `UNLEASH_TOKEN=""` (empty for basic setup)
- [ ] Verify `KOKU_SENTRY_ENVIRONMENT=development` (for fallback behavior)

### Database Setup
- [ ] Create Unleash database:
  ```sql
  CREATE DATABASE unleash;
  CREATE USER unleash WITH PASSWORD 'unleash-password';
  GRANT ALL PRIVILEGES ON DATABASE unleash TO unleash;
  ```
- [ ] Unleash will auto-create schema on first startup

### Network
- [ ] Ensure Koku API pods can reach Unleash service on port 4242
- [ ] Ensure Unleash can reach PostgreSQL on port 5432

---

## 🧪 Testing Plan

### 1. Verify Unleash Server Health
```bash
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-unleash 4242:4242
curl http://localhost:4242/health
# Expected: {"health": "GOOD"}
```

### 2. Verify Koku Can Connect
```bash
kubectl logs -n cost-mgmt <koku-api-pod> | grep -i unleash
# Expected: No connection errors
# Expected: "Unleash client initialized" or similar
```

### 3. Verify Feature Flags Work
Check Koku logs for feature flag evaluations:
```bash
kubectl logs -n cost-mgmt <koku-api-pod> | grep "is_enabled"
```

### 4. Verify Fallback Behavior
If Unleash is down, Koku should still work with fallback values (all flags return `True` in development).

---

## 🎯 Success Criteria

1. ✅ Unleash server starts and passes health checks
2. ✅ Unleash creates its database schema automatically
3. ✅ Koku API pods connect to Unleash without errors
4. ✅ Koku API pods become Ready (pass readiness probes)
5. ✅ `/status/` endpoint responds in < 1 second
6. ✅ No performance degradation compared to baseline
7. ✅ Feature flags can be toggled in Unleash UI (optional)

---

## 📊 Comparison: Unleash vs UNLEASH_DISABLED

| Aspect | Unleash Server | UNLEASH_DISABLED Flag |
|--------|---------------|----------------------|
| Code Changes | ✅ None | ❌ Requires code changes |
| Performance | ✅ Fast (cached) | ❌ Caused 600x slowdown |
| Maintenance | ✅ Standard deployment | ❌ Custom mock implementation |
| Feature Flags | ✅ Fully functional | ❌ Always return fallback |
| Production Ready | ✅ Yes | ❌ No (dev team review needed) |
| Complexity | ✅ Low (standard service) | ❌ High (custom code) |

**Recommendation**: Deploy Unleash server (this approach)

---

## 🔗 References

- Koku feature flags: `koku/koku/feature_flags.py`
- Koku configurator: `koku/koku/configurator.py`
- Koku settings: `koku/koku/settings.py`
- Feature flag usage: `koku/masu/processor/__init__.py`, `koku/subs/tasks.py`, `koku/hcs/tasks.py`
- Unleash Python client: https://github.com/Unleash/unleash-client-python
- Unleash server: https://github.com/Unleash/unleash

---

**Next Steps**: Deploy Unleash with these requirements and test integration


# Unleash Deployment Options for On-Prem Koku

**Date**: November 10, 2025  
**Status**: For Future Consideration After E2E Testing

---

## Current Approach: DisabledUnleashClient ✅

### What We're Using Now:
- `UNLEASH_DISABLED=true` environment variable
- `DisabledUnleashClient` in Koku code
- Zero network calls to Unleash
- All feature flags use fallback functions

### Advantages:
- ✅ Simple deployment (no Unleash server needed)
- ✅ No rate limiting issues
- ✅ Fast startup (90% improvement: 25s → 2.6s)
- ✅ No token management
- ✅ Works immediately

### Disadvantages:
- ⚠️ Requires code modification in Koku
- ⚠️ Feature flags always use fallback values (can't be toggled dynamically)
- ⚠️ No feature flag visibility/management UI

---

## Future Option: Deploy Unleash with Pre-Created Tokens

### When to Consider This:
- ✅ After E2E tests pass successfully
- ✅ If dynamic feature flag control is needed
- ✅ If dev team prefers not to modify Koku code
- ✅ If on-prem customers want feature flag management UI

---

## Option A: Unleash with Pre-Created API Token (Recommended)

### Deployment Sequence:

#### Step 1: Deploy Unleash Server First
```yaml
# unleash-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: unleash
  namespace: cost-mgmt
spec:
  replicas: 1
  selector:
    matchLabels:
      app: unleash
  template:
    metadata:
      labels:
        app: unleash
    spec:
      initContainers:
      # Wait for PostgreSQL to be ready
      - name: wait-for-db
        image: postgres:14
        command: 
          - sh
          - -c
          - |
            until pg_isready -h unleash-db -U unleash; do 
              echo "Waiting for database..."
              sleep 2
            done
            echo "Database is ready!"
      
      containers:
      - name: unleash
        image: unleashorg/unleash-server:latest
        ports:
        - containerPort: 4242
          name: http
        env:
        - name: DATABASE_URL
          value: "postgres://unleash:unleash-password@unleash-db:5432/unleash"
        - name: DATABASE_SSL
          value: "false"
        - name: LOG_LEVEL
          value: "info"
        # CRITICAL: Set token BEFORE first startup with empty database
        - name: INIT_CLIENT_API_TOKENS
          value: "*:koku-onprem-client-token-2024"
        
        livenessProbe:
          httpGet:
            path: /health
            port: 4242
          initialDelaySeconds: 30
          periodSeconds: 10
        
        readinessProbe:
          httpGet:
            path: /health
            port: 4242
          initialDelaySeconds: 10
          periodSeconds: 5
```

#### Step 2: Deploy Unleash PostgreSQL Database
```yaml
# unleash-postgres.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: unleash-db
  namespace: cost-mgmt
spec:
  serviceName: unleash-db
  replicas: 1
  selector:
    matchLabels:
      app: unleash-db
  template:
    metadata:
      labels:
        app: unleash-db
    spec:
      containers:
      - name: postgres
        image: postgres:14
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: "unleash"
        - name: POSTGRES_USER
          value: "unleash"
        - name: POSTGRES_PASSWORD
          value: "unleash-password"
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 5Gi
```

#### Step 3: Verify Unleash is Ready
```bash
# Wait for Unleash to be ready
kubectl wait --for=condition=ready pod -l app=unleash -n cost-mgmt --timeout=300s

# Verify token was created
kubectl port-forward -n cost-mgmt svc/unleash 4242:4242 &
curl -H "Authorization: koku-onprem-client-token-2024" \
  http://localhost:4242/api/client/features

# Should return: {"version": 1, "features": [...]}
# NOT: 401 Unauthorized
```

#### Step 4: Configure Koku with Matching Token
```yaml
# values-koku.yaml
api:
  reads:
    env:
      # Unleash configuration
      UNLEASH_HOST: "unleash"
      UNLEASH_PORT: "4242"
      UNLEASH_TOKEN: "koku-onprem-client-token-2024"  # MUST match Step 1
      
      # Remove these if using Unleash:
      # UNLEASH_DISABLED: "true"  # <-- REMOVE THIS
  
  writes:
    env:
      UNLEASH_HOST: "unleash"
      UNLEASH_PORT: "4242"
      UNLEASH_TOKEN: "koku-onprem-client-token-2024"
```

#### Step 5: Deploy Koku
```bash
helm upgrade cost-mgmt ./cost-management-onprem \
  -f cost-management-onprem/values-koku.yaml \
  -n cost-mgmt
```

#### Step 6: Verify Koku Connects Successfully
```bash
# Check Koku logs for successful Unleash connection
kubectl logs -n cost-mgmt -l app=koku-api-reads --tail=100 | grep -i unleash

# Should see:
# "Unleash client initialized successfully"
# NO rate limiting messages
# NO connection errors
```

---

## Critical Success Factors

### ✅ DO:
1. **Deploy Unleash FIRST** with empty database
2. **Set `INIT_CLIENT_API_TOKENS`** before first Unleash startup
3. **Wait for Unleash to be ready** before deploying Koku
4. **Use the EXACT SAME token** in Koku configuration
5. **Test the token** via curl before deploying Koku
6. **Keep token consistent** - don't change it after initial setup

### ❌ DON'T:
1. **Don't deploy Koku and Unleash simultaneously**
2. **Don't change tokens** after Unleash database is created
3. **Don't use `INIT_CLIENT_API_TOKENS`** with existing database
4. **Don't skip the verification step** (Step 3)
5. **Don't expect `DISABLE_RATE_LIMIT` to work** (it doesn't exist)

---

## Comparison: DisabledUnleashClient vs. Real Unleash

| Aspect | DisabledUnleashClient | Real Unleash Server |
|--------|----------------------|---------------------|
| **Deployment Complexity** | ✅ Simple (no extra services) | ⚠️ Complex (Unleash + PostgreSQL) |
| **Startup Time** | ✅ Fast (2.6s) | ⚠️ Slower (network calls) |
| **Code Modifications** | ⚠️ Requires Koku code change | ✅ No code changes |
| **Feature Flag Control** | ❌ Static (fallback values only) | ✅ Dynamic (toggle via UI) |
| **Management UI** | ❌ None | ✅ Web UI for flag management |
| **Token Management** | ✅ Not needed | ⚠️ Required |
| **Rate Limiting Risk** | ✅ Zero risk | ⚠️ Risk if misconfigured |
| **Maintenance** | ✅ Low (no extra services) | ⚠️ Higher (Unleash + DB) |
| **Dev Team Approval** | ⚠️ Needs review | ✅ Standard approach |

---

## Recommendation

### For Initial On-Prem Deployment:
**Use `DisabledUnleashClient`** (current approach)
- ✅ Simpler to deploy and maintain
- ✅ Proven to work in our testing
- ✅ No risk of rate limiting or token issues
- ✅ Faster startup and better performance

### Consider Unleash Server If:
1. ✅ E2E tests pass successfully with `DisabledUnleashClient`
2. ✅ On-prem customers need dynamic feature flag control
3. ✅ Dev team prefers not to maintain `DisabledUnleashClient` code
4. ✅ Feature flag management UI is valuable
5. ✅ Team has capacity to manage additional services

---

## Migration Path: DisabledUnleashClient → Real Unleash

If we decide to switch later:

### Step 1: Deploy Unleash (Option A above)
```bash
# Deploy Unleash with pre-created token
kubectl apply -f unleash-deployment.yaml
kubectl apply -f unleash-postgres.yaml
```

### Step 2: Update Koku Configuration
```yaml
# values-koku.yaml - REMOVE DisabledUnleashClient settings
api:
  reads:
    env:
      # UNLEASH_DISABLED: "true"  # <-- REMOVE THIS LINE
      UNLEASH_HOST: "unleash"      # <-- ADD THIS
      UNLEASH_PORT: "4242"         # <-- ADD THIS
      UNLEASH_TOKEN: "koku-onprem-client-token-2024"  # <-- ADD THIS
```

### Step 3: Revert Koku Code Changes
```bash
# Remove DisabledUnleashClient from feature_flags.py
# Use upstream Koku code without modifications
git checkout main -- koku/koku/feature_flags.py
```

### Step 4: Rebuild and Redeploy Koku
```bash
# Build new image without DisabledUnleashClient
podman build -t quay.io/jordigilh/koku:with-unleash .
podman push quay.io/jordigilh/koku:with-unleash

# Update Helm values
# values-koku.yaml:
#   api.image.tag: "with-unleash"

# Deploy
helm upgrade cost-mgmt ./cost-management-onprem -f values-koku.yaml
```

### Step 5: Verify
```bash
# Check Koku connects to Unleash successfully
kubectl logs -n cost-mgmt -l app=koku-api-reads | grep -i unleash
```

---

## Decision Criteria

### Stick with DisabledUnleashClient if:
- ✅ E2E tests pass successfully
- ✅ Feature flags don't need dynamic control
- ✅ Simpler deployment is preferred
- ✅ Dev team approves the code modification

### Switch to Real Unleash if:
- ✅ Dynamic feature flag control is required
- ✅ Feature flag management UI is valuable
- ✅ Dev team prefers no code modifications
- ✅ On-prem customers request it

---

## Next Steps

1. ✅ **Complete E2E testing** with `DisabledUnleashClient`
2. ⏳ **Get dev team approval** for `DisabledUnleashClient` approach
3. ⏳ **Document feature flag behavior** for on-prem deployments
4. ⏳ **Decide**: Keep `DisabledUnleashClient` or migrate to real Unleash
5. ⏳ **If migrating**: Follow Option A deployment sequence above

---

**Status**: `DisabledUnleashClient` is working. Real Unleash deployment is **optional** and should be considered after successful E2E testing.

**Recommendation**: Proceed with E2E tests using current approach, then decide based on results and dev team feedback.


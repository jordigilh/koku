# Environment Validation Checklist

**Purpose**: Verify the Koku on-prem environment is fully operational before starting Trino to PostgreSQL migration
**Date**: November 11, 2025
**Status**: 🔄 In Progress

---

## 📋 Overview

This checklist ensures all components are working correctly before beginning the migration implementation. Each item must pass before proceeding.

---

## ✅ Phase 1: Infrastructure Validation

### 1.1 OpenShift Cluster Access

**Test**: Verify cluster authentication and access

```bash
# Check cluster access
kubectl cluster-info

# Check namespace exists
kubectl get namespace cost-mgmt

# Check current context
kubectl config current-context
```

**Expected Result**:
- ✅ Cluster info displays correctly
- ✅ `cost-mgmt` namespace exists
- ✅ Context points to correct cluster

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 1.2 Pod Health Check

**Test**: Verify all Koku pods are running

```bash
# Check all pods in cost-mgmt namespace
kubectl get pods -n cost-mgmt

# Check for any pods not in Running state
kubectl get pods -n cost-mgmt --field-selector=status.phase!=Running
```

**Expected Result**:
```
NAME                                                    READY   STATUS    RESTARTS   AGE
cost-mgmt-cost-management-onprem-celery-beat-xxx       1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-celery-worker-xxx     1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-hive-metastore-0      1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-koku-api-reads-xxx    1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-koku-api-writes-xxx   1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-koku-db-0             1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-masu-xxx              1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-trino-coordinator-0   1/1     Running   0          Xh
cost-mgmt-cost-management-onprem-trino-worker-0        1/1     Running   0          Xh
```

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 1.3 Database Migration Status

**Test**: Verify Django migrations are applied

```bash
# Check migration job completion
kubectl get jobs -n cost-mgmt | grep migrate

# Check migration logs
kubectl logs -n cost-mgmt job/cost-mgmt-cost-management-onprem-db-migrate --tail=50
```

**Expected Result**:
- ✅ Migration job shows `Completed` status
- ✅ Logs show "Migration completed successfully"
- ✅ No migration errors in logs

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 2: Database Validation

### 2.1 PostgreSQL Connectivity

**Test**: Verify PostgreSQL is accessible and responding

```bash
# Port-forward to PostgreSQL
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-db 5432:5432 &

# Test connection (requires psql client)
PGPASSWORD=koku psql -h localhost -p 5432 -U koku -d koku -c "SELECT version();"

# Kill port-forward
pkill -f "port-forward.*5432"
```

**Expected Result**:
- ✅ Connection succeeds
- ✅ PostgreSQL version displays
- ✅ No connection errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 2.2 Database Schema Validation

**Test**: Verify core tables exist

```bash
# Check if core tables exist
kubectl exec -n cost-mgmt deployment/cost-mgmt-cost-management-onprem-koku-api-reads -- \
    python manage.py shell -c "
from django.db import connection
cursor = connection.cursor()
cursor.execute(\"\"\"
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name IN (
        'api_tenant',
        'api_provider',
        'reporting_awscostentrylineitem_daily_summary',
        'reporting_azurecostentrylineitem_daily_summary',
        'reporting_gcpcostentrylineitem_daily_summary',
        'reporting_ocpusagelineitem_daily_summary'
    )
    ORDER BY table_name;
\"\"\")
tables = [row[0] for row in cursor.fetchall()]
print('Found tables:', tables)
print('Missing tables:', set(['api_tenant', 'api_provider', 'reporting_awscostentrylineitem_daily_summary', 'reporting_azurecostentrylineitem_daily_summary', 'reporting_gcpcostentrylineitem_daily_summary', 'reporting_ocpusagelineitem_daily_summary']) - set(tables))
"
```

**Expected Result**:
- ✅ All 6 core tables exist
- ✅ No missing tables
- ✅ No schema errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 2.3 Tenant Configuration

**Test**: Verify tenant exists and is configured

```bash
# Check tenant exists
kubectl exec -n cost-mgmt deployment/cost-mgmt-cost-management-onprem-koku-api-reads -- \
    python manage.py shell -c "
from api.models import Tenant
tenants = Tenant.objects.all()
print(f'Total tenants: {tenants.count()}')
for tenant in tenants:
    print(f'  - {tenant.schema_name} (ID: {tenant.id})')
"
```

**Expected Result**:
- ✅ At least one tenant exists
- ✅ Tenant has valid schema_name
- ✅ No tenant errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 3: API Validation

### 3.1 API Accessibility

**Test**: Verify Koku API is accessible

```bash
# Port-forward to API
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &

# Wait for port-forward to establish
sleep 3

# Test API status endpoint
curl -s http://localhost:8000/api/cost-management/v1/status/ | jq '.'

# Kill port-forward
pkill -f "port-forward.*8000"
```

**Expected Result**:
```json
{
  "api_version": "1",
  "commit": "...",
  "server_address": "...",
  "platform_info": {...},
  "python_version": "...",
  "modules": {...}
}
```

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 3.2 API Authentication

**Test**: Verify API accepts x-rh-identity header

```bash
# Port-forward to API (if not already running)
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &
sleep 3

# Create x-rh-identity header
IDENTITY=$(echo -n '{"identity":{"account_number":"10001","org_id":"1234567","type":"User","user":{"username":"test","is_org_admin":true}},"entitlements":{"cost_management":{"is_entitled":true}}}' | base64)

# Test authenticated endpoint
curl -s -H "x-rh-identity: $IDENTITY" \
    http://localhost:8000/api/cost-management/v1/providers/ | jq '.'

# Kill port-forward
pkill -f "port-forward.*8000"
```

**Expected Result**:
- ✅ Returns 200 OK
- ✅ Returns JSON response (may be empty list)
- ✅ No 401 Unauthorized error

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 3.3 API Endpoints Health

**Test**: Verify core API endpoints respond

```bash
# Port-forward to API
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &
sleep 3

# Create x-rh-identity header
IDENTITY=$(echo -n '{"identity":{"account_number":"10001","org_id":"1234567","type":"User","user":{"username":"test","is_org_admin":true}},"entitlements":{"cost_management":{"is_entitled":true}}}' | base64)

# Test multiple endpoints
echo "Testing /providers/"
curl -s -H "x-rh-identity: $IDENTITY" http://localhost:8000/api/cost-management/v1/providers/ | jq '.data | length'

echo "Testing /settings/"
curl -s -H "x-rh-identity: $IDENTITY" http://localhost:8000/api/cost-management/v1/settings/ | jq '.'

echo "Testing /reports/aws/costs/"
curl -s -H "x-rh-identity: $IDENTITY" http://localhost:8000/api/cost-management/v1/reports/aws/costs/ | jq '.data | length'

# Kill port-forward
pkill -f "port-forward.*8000"
```

**Expected Result**:
- ✅ All endpoints return 200 OK
- ✅ No 500 Internal Server Error
- ✅ JSON responses are valid

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 4: Trino Validation

### 4.1 Trino Coordinator Health

**Test**: Verify Trino coordinator is running and accessible

```bash
# Check Trino coordinator pod
kubectl get pod -n cost-mgmt -l app.kubernetes.io/component=coordinator

# Check Trino coordinator logs
kubectl logs -n cost-mgmt -l app.kubernetes.io/component=coordinator --tail=50
```

**Expected Result**:
- ✅ Coordinator pod is Running
- ✅ Logs show "SERVER STARTED"
- ✅ No error messages in logs

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 4.2 Trino Worker Health

**Test**: Verify Trino workers are connected

```bash
# Check Trino worker pods
kubectl get pods -n cost-mgmt -l app.kubernetes.io/component=worker

# Check worker logs
kubectl logs -n cost-mgmt -l app.kubernetes.io/component=worker --tail=50
```

**Expected Result**:
- ✅ Worker pods are Running
- ✅ Logs show successful registration with coordinator
- ✅ No connection errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 4.3 Trino Query Execution

**Test**: Verify Trino can execute queries

```bash
# Port-forward to Trino coordinator
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-trino-coordinator 8080:8080 &
sleep 3

# Test simple query
curl -s -X POST http://localhost:8080/v1/statement \
    -H "X-Trino-User: admin" \
    -H "Content-Type: text/plain" \
    -d "SELECT 1 as test" | jq '.data'

# Test catalog query
curl -s -X POST http://localhost:8080/v1/statement \
    -H "X-Trino-User: admin" \
    -H "Content-Type: text/plain" \
    -d "SHOW CATALOGS" | jq '.data'

# Kill port-forward
pkill -f "port-forward.*8080"
```

**Expected Result**:
- ✅ Simple query returns `[[1]]`
- ✅ Catalogs include `hive` and `postgres`
- ✅ No query errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 5: Hive Metastore Validation

### 5.1 Hive Metastore Health

**Test**: Verify Hive Metastore is running

```bash
# Check Hive Metastore pod
kubectl get pod -n cost-mgmt -l app.kubernetes.io/name=hive-metastore

# Check Metastore logs
kubectl logs -n cost-mgmt -l app.kubernetes.io/name=hive-metastore --tail=50
```

**Expected Result**:
- ✅ Metastore pod is Running
- ✅ Logs show "Starting Hive Metastore service"
- ✅ No schema initialization errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 5.2 Hive Metastore Schema

**Test**: Verify Metastore schema is initialized

```bash
# Check schema version
kubectl exec -n cost-mgmt -it deployment/cost-mgmt-cost-management-onprem-hive-metastore -- \
    /opt/hive/bin/schematool -dbType postgres -info
```

**Expected Result**:
- ✅ Schema version displays (e.g., "3.1.0")
- ✅ "schemaTool completed" message
- ✅ No schema errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 5.3 Hive Tables Accessibility

**Test**: Verify Trino can access Hive tables

```bash
# Port-forward to Trino
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-trino-coordinator 8080:8080 &
sleep 3

# List Hive schemas
curl -s -X POST http://localhost:8080/v1/statement \
    -H "X-Trino-User: admin" \
    -H "Content-Type: text/plain" \
    -d "SHOW SCHEMAS FROM hive" | jq '.data'

# Kill port-forward
pkill -f "port-forward.*8080"
```

**Expected Result**:
- ✅ Returns list of schemas (may include `default`, `org1234567`, etc.)
- ✅ No connection errors to Metastore
- ✅ Query completes successfully

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 6: Data Processing Validation

### 6.1 MASU Service Health

**Test**: Verify MASU (data ingestion service) is running

```bash
# Check MASU pod
kubectl get pod -n cost-mgmt -l app.kubernetes.io/component=masu

# Check MASU logs
kubectl logs -n cost-mgmt -l app.kubernetes.io/component=masu --tail=50
```

**Expected Result**:
- ✅ MASU pod is Running
- ✅ Logs show service started
- ✅ No critical errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 6.2 Celery Workers Health

**Test**: Verify Celery workers are processing tasks

```bash
# Check Celery worker pods
kubectl get pods -n cost-mgmt -l app.kubernetes.io/component=celery-worker

# Check worker logs
kubectl logs -n cost-mgmt -l app.kubernetes.io/component=celery-worker --tail=50

# Check Celery beat (scheduler)
kubectl get pod -n cost-mgmt -l app.kubernetes.io/component=celery-beat
kubectl logs -n cost-mgmt -l app.kubernetes.io/component=celery-beat --tail=50
```

**Expected Result**:
- ✅ Worker pods are Running
- ✅ Beat pod is Running
- ✅ Logs show workers are ready
- ✅ No task processing errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## ✅ Phase 7: End-to-End Validation

### 7.1 Create Test Provider

**Test**: Verify we can create a provider through the API

```bash
# Port-forward to API
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &
sleep 3

# Create x-rh-identity header
IDENTITY=$(echo -n '{"identity":{"account_number":"10001","org_id":"1234567","type":"User","user":{"username":"test","is_org_admin":true}},"entitlements":{"cost_management":{"is_entitled":true}}}' | base64)

# Create test provider (AWS)
curl -s -X POST http://localhost:8000/api/cost-management/v1/providers/ \
    -H "x-rh-identity: $IDENTITY" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "test-aws-provider",
        "type": "AWS",
        "authentication": {
            "credentials": {
                "role_arn": "arn:aws:iam::123456789012:role/CostManagement"
            }
        },
        "billing_source": {
            "data_source": {
                "bucket": "test-bucket"
            }
        }
    }' | jq '.'

# Kill port-forward
pkill -f "port-forward.*8000"
```

**Expected Result**:
- ✅ Returns 201 Created
- ✅ Provider UUID is returned
- ✅ No validation errors

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

### 7.2 IQE Tests Execution

**Test**: Verify IQE tests can run against the environment

```bash
# Navigate to IQE plugin
cd /Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin

# Activate venv
source iqe-venv/bin/activate

# Port-forward to API
kubectl port-forward -n cost-mgmt svc/cost-mgmt-cost-management-onprem-koku-api 8000:8000 &
sleep 3

# Run simple IQE test
DYNACONF_IQE_VAULT_LOADER_ENABLED=false \
ENV_FOR_DYNACONF=onprem \
DYNACONF_MAIN__HOSTNAME="localhost" \
DYNACONF_MAIN__PORT="8000" \
DYNACONF_MAIN__SCHEME="http" \
DYNACONF_MAIN__SSL_VERIFY="false" \
DYNACONF_DEFAULT_USER="onprem_user" \
DYNACONF_HTTP__DEFAULT_AUTH_TYPE="identity" \
pytest iqe_cost_management/tests/rest_api/v1/ -k "test_api" --collect-only

# Kill port-forward
pkill -f "port-forward.*8000"
```

**Expected Result**:
- ✅ Tests are collected successfully
- ✅ No import errors
- ✅ Authentication fixtures work

**Status**: ⬜ Not Started | 🔄 In Progress | ✅ Passed | ❌ Failed

---

## 📊 Validation Summary

### Overall Status

| Phase | Component | Status | Notes |
|-------|-----------|--------|-------|
| 1 | Infrastructure | ⬜ | Cluster, pods, migrations |
| 2 | Database | ⬜ | PostgreSQL, schema, tenants |
| 3 | API | ⬜ | Accessibility, auth, endpoints |
| 4 | Trino | ⬜ | Coordinator, workers, queries |
| 5 | Hive Metastore | ⬜ | Health, schema, tables |
| 6 | Data Processing | ⬜ | MASU, Celery workers |
| 7 | End-to-End | ⬜ | Provider creation, IQE tests |

### Blockers

List any blockers discovered during validation:

1. ⬜ None identified yet

### Sign-Off

- [ ] All phases passed
- [ ] No critical blockers
- [ ] Environment is ready for migration implementation

**Validated By**: _________________
**Date**: _________________
**Signature**: _________________

---

## 🚀 Next Steps

Once all validations pass:

1. ✅ **Proceed to Migration Implementation**
   - Start with Week 1, Day 1 of `TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md`
   - Begin with custom PostgreSQL functions

2. ✅ **Set Up Monitoring**
   - Configure Prometheus metrics collection
   - Set up alerting for migration issues

3. ✅ **Create Baseline Metrics**
   - Capture current Trino query performance
   - Document current data volumes
   - Establish success criteria

---

**Document Version**: 1.0
**Last Updated**: November 11, 2025
**Maintainer**: Cost Management Team




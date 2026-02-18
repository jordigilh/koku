# Kessel/ReBAC Integration -- Test Plan

| Field         | Value                                                                        |
|---------------|------------------------------------------------------------------------------|
| Jira          | [FLPATH-3294](https://issues.redhat.com/browse/FLPATH-3294)                 |
| DD Reference  | [kessel-ocp-detailed-design.md](./kessel-ocp-detailed-design.md)            |
| Author        | Jordi Gil                                                                    |
| Status        | Draft                                                                        |
| Created       | 2026-02-18                                                                  |
| Last updated  | 2026-02-18                                                                  |

## Table of Contents

1. [Conventions](#1-conventions)
2. [Tier 1 -- Unit Tests (UT)](#2-tier-1----unit-tests-ut)
3. [Tier 2 -- Integration Tests (IT)](#3-tier-2----integration-tests-it)
4. [Tier 3 -- Contract Tests (CT)](#4-tier-3----contract-tests-ct)
5. [Tier 4 -- E2E Tests (E2E)](#5-tier-4----e2e-tests-e2e)
6. [Coverage Summary](#6-coverage-summary)

---

## 1. Conventions

### 1.1 Scenario ID Format

`{TIER}-{MODULE}-{FEATURE}-{NNN}`

| Segment | Values | Description |
|---------|--------|-------------|
| TIER | `UT`, `IT`, `CT`, `E2E` | Unit, Integration, Contract, End-to-End |
| MODULE | `KESSEL`, `MW`, `SETTINGS`, `MASU`, `API`, `COSTMODEL` | Koku module where the test code lives |
| FEATURE | Short mnemonic | Feature under test |
| NNN | `001`-`999` | Sequential scenario number |

### 1.2 Module Reference

| Code | Koku module | Covers |
|------|-------------|--------|
| `KESSEL` | `koku/kessel/` | access_provider, client, resource_reporter, models, views, serializers, management commands |
| `MW` | `koku/koku/middleware.py` | Middleware integration |
| `SETTINGS` | `koku/koku/settings.py` | Configuration and startup |
| `MASU` | `koku/masu/` | Pipeline hook |
| `API` | `koku/api/` | ProviderBuilder hook, URL registration |
| `COSTMODEL` | `koku/cost_models/` | CostModelViewSet hook |

### 1.3 Feature Mnemonics

| Mnemonic | Feature |
|----------|---------|
| `AP` | AccessProvider |
| `CL` | Kessel gRPC Client |
| `RR` | Resource Reporter |
| `MDL` | Models (KesselSyncedResource) |
| `AUTH` | Auth dispatch / cache |
| `CFG` | Configuration / settings |
| `SYNC` | Pipeline sync |
| `PB` | ProviderBuilder hook |
| `CM` | Cost model hook |
| `SEED` | Role seeding command |
| `SCHEMA` | Schema update command |
| `VIEW` | Access Management API views |
| `SER` | Access Management API serializers |
| `URL` | URL registration |
| `FLOW` | Full auth flow |

### 1.4 Priority Levels

| Level | Meaning | Triage guidance |
|-------|---------|-----------------|
| P0 (Critical) | Core contract, blocks all downstream | Must fix immediately; blocks PR merge |
| P1 (High) | Key feature, significant user impact | Fix before phase checkpoint |
| P2 (Medium) | Important but not blocking | Fix before final PR merge |
| P3 (Low) | Defensive, unlikely paths | Can defer to follow-up |

### 1.5 Per-Scenario Format

Each scenario follows an IEEE 829-inspired structure with Priority, Business Value, Fixtures, BDD Steps, and Acceptance Criteria.

### 1.6 Tier Infrastructure

| Tier | Runner | CI? | Kessel? |
|------|--------|-----|---------|
| UT | Django `manage.py test` / tox | Yes | Mocked gRPC |
| IT | Django `manage.py test` + `@override_settings` | Yes | Mocked gRPC |
| CT | Django `manage.py test` | Yes | Mocked gRPC |
| E2E | IQE plugin with Kessel markers | No (OCP) | Full stack |

---

## 2. Tier 1 -- Unit Tests (UT)

Coverage target: >80% on `koku/kessel/` module.

---

### UT-KESSEL-AP-001: Returns correct dict shape for OCP cluster access

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Core contract -- KesselAccessProvider must produce output identical to RbacService for the query layer to function without changes |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning mock with 2 cluster UUIDs for `lookup_resources`
- `@override_settings(AUTHORIZATION_BACKEND="rebac", KESSEL_CACHE_TTL=300)`

**Steps:**
- **Given** a mocked Kessel client where `lookup_resources(resource_type="cost_management/openshift_cluster", ...)` returns `["cluster-uuid-1", "cluster-uuid-2"]`
- **When** `KesselAccessProvider().get_access_for_user(user)` is called
- **Then** the returned dict contains key `"openshift.cluster"` with `{"read": ["cluster-uuid-1", "cluster-uuid-2"]}`

**Acceptance Criteria:**
- Dict shape matches `RbacService.get_access_for_user()` output (same keys, same nesting)
- No `"*"` wildcard appears in the output
- All `RESOURCE_TYPES` keys are present in the returned dict

---

### UT-KESSEL-AP-002: Returns empty lists for resource types with no access

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Users without access to specific resources must see no data, not receive errors |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning mock with empty lists for all `lookup_resources` calls
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a mocked Kessel client where `lookup_resources` returns `[]` for all resource types
- **When** `KesselAccessProvider().get_access_for_user(user)` is called
- **Then** the returned value is `None` (no access to any resource)

**Acceptance Criteria:**
- Return value is `None` when all resource type lookups yield empty lists
- Matches RBAC behavior where no ACLs results in `None`

---

### UT-KESSEL-AP-003: Returns None when Kessel is unreachable

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Kessel connection failures must propagate as KesselConnectionError so middleware returns HTTP 424 |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` where `lookup_resources` raises `grpc.RpcError`
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a mocked Kessel client where `lookup_resources` raises `grpc.RpcError`
- **When** `KesselAccessProvider().get_access_for_user(user)` is called
- **Then** a `KesselConnectionError` is raised

**Acceptance Criteria:**
- `KesselConnectionError` is raised (not swallowed)
- Error message includes the resource type that failed

---

### UT-KESSEL-AP-004: Maps all RESOURCE_TYPES to Kessel types

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Every Koku resource type must have a corresponding Kessel type mapping to avoid KeyError at runtime |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** the `KOKU_TO_KESSEL_TYPE_MAP` constant in `access_provider.py`
- **When** compared against `RESOURCE_TYPES` from `koku/koku/rbac.py`
- **Then** every key in `RESOURCE_TYPES` has a corresponding entry in `KOKU_TO_KESSEL_TYPE_MAP`

**Acceptance Criteria:**
- `set(RESOURCE_TYPES.keys()) == set(KOKU_TO_KESSEL_TYPE_MAP.keys())`
- No unmapped resource types

---

### UT-KESSEL-AP-005: Handles mixed access -- some types with resources, some empty

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Real-world users have partial access (e.g., 2 clusters, 0 AWS accounts). Dict must reflect this accurately |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning mixed results: 2 clusters, 0 AWS accounts, 1 cost model
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a mocked Kessel client returning `["uuid-1", "uuid-2"]` for `openshift_cluster`, `[]` for `aws_account`, `["cm-uuid"]` for `cost_model` (read and write)
- **When** `KesselAccessProvider().get_access_for_user(user)` is called
- **Then** the dict contains `{"openshift.cluster": {"read": ["uuid-1", "uuid-2"]}, "aws.account": {"read": []}, "cost_model": {"read": ["cm-uuid"], "write": ["cm-uuid"]}, ...}`

**Acceptance Criteria:**
- Non-empty types have their IDs
- Empty types have `[]`
- `cost_model` has both `read` and `write` keys

---

### UT-KESSEL-AP-006: Factory returns correct provider based on AUTHORIZATION_BACKEND

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Backend selection must work correctly or all requests go to the wrong authorization service |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- Reset `_provider_instance` to `None` between test runs

**Steps:**
- **Given** `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- **When** `get_access_provider()` is called
- **Then** the returned instance is `KesselAccessProvider`
- **Given** `@override_settings(AUTHORIZATION_BACKEND="rbac")`
- **When** `get_access_provider()` is called (after reset)
- **Then** the returned instance is `RBACAccessProvider`

**Acceptance Criteria:**
- `isinstance(provider, KesselAccessProvider)` for rebac
- `isinstance(provider, RBACAccessProvider)` for rbac

---

### UT-KESSEL-CL-001: Client creates insecure channel when TLS disabled

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Development and non-TLS deployments must connect without certificate errors |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(KESSEL_RELATIONS_CONFIG={"host": "localhost", "port": 9000, "tls_enabled": False, "tls_cert_path": ""})`
- `@patch("grpc.insecure_channel")`

**Steps:**
- **Given** `KESSEL_RELATIONS_CONFIG` with `tls_enabled=False`
- **When** `KesselClient._get_relations_channel()` is called
- **Then** `grpc.insecure_channel("localhost:9000")` is invoked

**Acceptance Criteria:**
- `grpc.insecure_channel` called with correct target
- `grpc.secure_channel` NOT called

---

### UT-KESSEL-CL-002: Client creates secure channel when TLS enabled

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Production deployments must use TLS for gRPC connections |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(KESSEL_RELATIONS_CONFIG={"host": "kessel.example.com", "port": 443, "tls_enabled": True, "tls_cert_path": "/certs/ca.pem"})`
- `@patch("grpc.secure_channel")`
- `@patch("builtins.open", mock_open(read_data=b"cert-data"))`

**Steps:**
- **Given** `KESSEL_RELATIONS_CONFIG` with `tls_enabled=True` and a cert path
- **When** `KesselClient._get_relations_channel()` is called
- **Then** `grpc.secure_channel` is invoked with SSL credentials

**Acceptance Criteria:**
- `grpc.secure_channel` called with correct target and credentials
- Certificate file is read from the configured path

---

### UT-KESSEL-CL-003: Client singleton is thread-safe

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Concurrent requests must not create multiple client instances or race on channel setup |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- Reset `_client_instance` to `None`
- `@patch("kessel.client.KesselClient")`

**Steps:**
- **Given** `_client_instance` is `None`
- **When** `get_kessel_client()` is called from 10 concurrent threads
- **Then** `KesselClient()` is instantiated exactly once

**Acceptance Criteria:**
- Only one `KesselClient` instance created
- All threads receive the same instance

---

### UT-KESSEL-RR-001: Reporter no-ops for RBAC backend

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | RBAC deployments must not attempt Kessel connections or database writes for resource tracking |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`
- `@patch("kessel.resource_reporter.get_kessel_client")`
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects")`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rbac"`
- **When** `on_resource_created("openshift_cluster", "uuid-1", "org123")` is called
- **Then** no Kessel client methods are invoked and no database operations occur

**Acceptance Criteria:**
- `get_kessel_client` NOT called
- `KesselSyncedResource.objects.update_or_create` NOT called

---

### UT-KESSEL-RR-002: Reporter syncs resource for ReBAC backend

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | New resources must be reported to Kessel for authorization to work |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` with mock client
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, True)`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"`
- **When** `on_resource_created("openshift_cluster", "uuid-1", "org123")` is called
- **Then** `KesselSyncedResource.objects.update_or_create` is called with correct args AND `client.report_resource` is called

**Acceptance Criteria:**
- Tracking row upserted with `resource_type="openshift_cluster"`, `resource_id="uuid-1"`, `org_id="org123"`
- `client.report_resource("openshift_cluster", "uuid-1", "org123")` called
- On success, `kessel_synced=True` and `last_synced_at` is set

---

### UT-KESSEL-RR-003: Reporter handles Kessel sync failure gracefully

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Kessel unavailability must not block resource creation in Postgres |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` where `report_resource` raises `Exception`
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, True)`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and Kessel client raises an exception on `report_resource`
- **When** `on_resource_created("openshift_cluster", "uuid-1", "org123")` is called
- **Then** the function does NOT raise. The tracking row has `kessel_synced=False`

**Acceptance Criteria:**
- No exception propagated
- `kessel_synced` remains `False`
- Warning logged

---

### UT-KESSEL-RR-004: Reporter is idempotent on repeated calls

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Pipeline reruns must not create duplicate resources or fail |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` with mock client
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, False)` (existing row)

**Steps:**
- **Given** a resource that has already been synced (`update_or_create` returns `created=False`)
- **When** `on_resource_created("openshift_cluster", "uuid-1", "org123")` is called again
- **Then** `report_resource` is still called (idempotent) and `kessel_synced` is updated

**Acceptance Criteria:**
- `update_or_create` uses correct unique constraint fields
- No duplicate rows created

---

### UT-KESSEL-MDL-001: KesselSyncedResource unique constraint enforced

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Duplicate tracking rows would cause incorrect sync state |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class with database

**Steps:**
- **Given** a `KesselSyncedResource` row with `resource_type="openshift_cluster"`, `resource_id="uuid-1"`, `org_id="org123"`
- **When** a second row with the same `(resource_type, resource_id, org_id)` is inserted
- **Then** an `IntegrityError` is raised

**Acceptance Criteria:**
- `unique_together` constraint on `(resource_type, resource_id, org_id)` is enforced

---

### UT-KESSEL-SEED-001: kessel_seed_roles skips when backend is rbac

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Management commands must be safe to run in any environment without side effects |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rbac"`
- **When** `kessel_seed_roles` management command is executed
- **Then** the command prints a skip message and makes no Kessel calls

**Acceptance Criteria:**
- No Kessel client instantiated
- stdout contains "Skipping"

---

### UT-KESSEL-SEED-002: kessel_seed_roles creates standard roles

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Standard roles must be available for administrators to assign to users |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a mocked Kessel client
- **When** `kessel_seed_roles` management command is executed
- **Then** `client.create_role` is called for each standard role

**Acceptance Criteria:**
- All standard roles (viewer, editor, admin) are seeded
- Command is idempotent (can run twice without error)

---

### UT-KESSEL-SCHEMA-001: kessel_update_schema skips when already at target version

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Helm upgrade hooks must be safe to run repeatedly without applying redundant schema changes |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac", KESSEL_SCHEMA_VERSION="1")`
- `@patch` deployed version to return `"1"`

**Steps:**
- **Given** deployed schema version is `"1"` and target is `"1"`
- **When** `kessel_update_schema` management command is executed
- **Then** no schema migration is applied

**Acceptance Criteria:**
- stdout contains "already at version"
- No Kessel client calls

---

### UT-KESSEL-VIEW-001: Role listing returns roles from Kessel

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Administrators must be able to see available roles to assign |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` returning mock with role list

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and 3 seeded roles in mocked Kessel
- **When** `GET /api/cost-management/v1/access-management/roles/` is called
- **Then** response is HTTP 200 with a list of 3 roles

**Acceptance Criteria:**
- Response status 200
- Response body contains all 3 roles with names and permissions

---

### UT-KESSEL-VIEW-002: Role binding creation calls Kessel and invalidates cache

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Binding a role to a user must take effect immediately, not after cache TTL expiry |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- `@patch("django.core.cache.caches")` with mock cache

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a valid role binding payload
- **When** `POST /api/cost-management/v1/access-management/role-bindings/` is called
- **Then** `client.create_tuples` is called AND the target user's cache entry is deleted

**Acceptance Criteria:**
- `create_tuples` called with correct subject, role, and tenant
- `cache.delete(f"{target_user_id}_{org_id}")` called
- Response status 201

---

### UT-KESSEL-VIEW-003: Role binding deletion calls Kessel and invalidates cache

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Revoking access must take effect immediately |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- `@patch("django.core.cache.caches")` with mock cache

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and an existing role binding ID
- **When** `DELETE /api/cost-management/v1/access-management/role-bindings/{id}/` is called
- **Then** `client.delete_tuples` is called AND the target user's cache entry is deleted

**Acceptance Criteria:**
- `delete_tuples` called with correct tuple
- `cache.delete(f"{target_user_id}_{org_id}")` called
- Response status 204

---

## 3. Tier 2 -- Integration Tests (IT)

---

### IT-MW-AUTH-001: Middleware dispatches to KesselAccessProvider when rebac

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Middleware must use the correct backend based on configuration or all auth decisions are wrong |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` returning mock access dict
- Valid `x-rh-identity` header

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a valid identity header
- **When** a GET request is made to any cost management endpoint
- **Then** `KesselAccessProvider.get_access_for_user` is called (not `RbacService`)

**Acceptance Criteria:**
- `KesselAccessProvider.get_access_for_user` called once
- `RbacService.get_access_for_user` NOT called
- `request.user.access` is set to the mock access dict

---

### IT-MW-AUTH-002: Middleware uses kessel cache when rebac

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Using the wrong cache would cause cache pollution between backends |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` returning mock access
- Valid `x-rh-identity` header

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a valid identity header
- **When** a request is made (cache miss), then a second request is made
- **Then** the first request calls `KesselAccessProvider.get_access_for_user`; the second request returns cached value from `CacheEnum.kessel`

**Acceptance Criteria:**
- `KesselAccessProvider.get_access_for_user` called exactly once for two requests
- Cache key uses `CacheEnum.kessel` prefix, not `CacheEnum.rbac`

---

### IT-MW-AUTH-003: Middleware returns 424 on KesselConnectionError

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Kessel unavailability must return a clear error, not a 500 or hang |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` raising `KesselConnectionError`
- Valid `x-rh-identity` header

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and Kessel is unreachable
- **When** a request is made
- **Then** the response is HTTP 424 with `{"source": "Kessel", ...}`

**Acceptance Criteria:**
- Response status code is 424
- Response body contains `"source": "Kessel"`

---

### IT-MW-AUTH-004: ENHANCED_ORG_ADMIN bypasses Kessel for admin users

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Bootstrap scenario requires org admins to have access before role bindings exist |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac", ENHANCED_ORG_ADMIN=True)`
- Valid `x-rh-identity` header with `is_org_admin=True`

**Steps:**
- **Given** `ENHANCED_ORG_ADMIN=True` and user is org admin
- **When** a request is made
- **Then** `request.user.access` is `{}` (full access) and Kessel is NOT called

**Acceptance Criteria:**
- `KesselAccessProvider.get_access_for_user` NOT called
- `request.user.access == {}`

---

### IT-MW-AUTH-005: Settings sentinel created on new customer

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Settings sentinel must exist in Kessel for settings permissions to work |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Valid `x-rh-identity` header with new org_id

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a request from a never-seen org
- **When** `IdentityHeaderMiddleware.create_customer()` creates the customer
- **Then** `on_resource_created("settings", "settings-{org_id}", org_id)` is called

**Acceptance Criteria:**
- `on_resource_created` called with correct args
- Customer is created in Postgres normally

---

### IT-API-PB-001: ProviderBuilder reports cluster on creation

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | New OCP clusters must appear in Kessel for authorization queries |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- `baker.make(Sources)` for source setup

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a valid OCP source
- **When** `ProviderBuilder.create_provider_from_source()` is called
- **Then** `on_resource_created("openshift_cluster", provider.uuid, org_id)` is called after the provider is saved

**Acceptance Criteria:**
- `on_resource_created` called with provider UUID
- Provider is created in Postgres normally

---

### IT-MASU-SYNC-001: Pipeline reports nodes and projects to Kessel

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | OCP nodes and projects must be registered in Kessel for granular access control |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Test OCP report data with 2 nodes and 3 projects

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and OCP report data with nodes `["node-a", "node-b"]` and projects `["ns-1", "ns-2", "ns-3"]`
- **When** `populate_openshift_cluster_information_tables()` runs
- **Then** `on_resource_created` is called for each node and each project

**Acceptance Criteria:**
- `on_resource_created("openshift_node", ...)` called 2 times
- `on_resource_created("openshift_project", ...)` called 3 times
- Pipeline processing completes normally

---

### IT-COSTMODEL-CM-001: CostModelViewSet reports cost model on creation

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | New cost models must be accessible through Kessel authorization |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Valid cost model creation payload

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"` and a valid cost model creation request
- **When** `CostModelViewSet.perform_create()` executes
- **Then** `on_resource_created("cost_model", cost_model.uuid, org_id)` is called

**Acceptance Criteria:**
- `on_resource_created` called with cost model UUID
- Cost model is created in Postgres normally

---

### IT-API-URL-001: Kessel URLs registered when rebac backend active

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Access Management API must be reachable only when Kessel is the active backend |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rebac"`
- **When** a request is made to `/api/cost-management/v1/access-management/roles/`
- **Then** the response is NOT 404

**Acceptance Criteria:**
- Response status is 200 or 403 (not 404)
- URL pattern is registered

---

### IT-API-URL-002: Kessel URLs return 404 when rbac backend active

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Access Management API must not be reachable in RBAC deployments |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`

**Steps:**
- **Given** `AUTHORIZATION_BACKEND="rbac"`
- **When** a request is made to `/api/cost-management/v1/access-management/roles/`
- **Then** the response is HTTP 404

**Acceptance Criteria:**
- Response status is 404
- URL pattern is not registered

---

## 4. Tier 3 -- Contract Tests (CT)

---

### CT-KESSEL-AP-001: Both providers produce equivalent dict structure

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Query layer depends on identical dict shapes from both backends. Structural mismatch would cause runtime errors |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class
- `@patch` `RbacService.get_access_for_user` returning a known access dict (with `"*"` wildcards)
- `@patch` `KesselAccessProvider` mock returning equivalent access (explicit IDs instead of `"*"`)

**Steps:**
- **Given** RBAC returns `{"openshift.cluster": {"read": ["*"]}, "cost_model": {"read": ["*"], "write": ["*"]}, ...}` and Kessel returns `{"openshift.cluster": {"read": ["uuid-1"]}, "cost_model": {"read": ["cm-1"], "write": ["cm-1"]}, ...}`
- **When** both dicts are compared structurally
- **Then** they have identical keys at all nesting levels

**Acceptance Criteria:**
- `rbac_dict.keys() == kessel_dict.keys()`
- For each key, inner dict has same operation keys (`read`, `write`)
- Values are lists in both cases (content differs but type matches)

---

### CT-KESSEL-AP-002: Kessel resource IDs match query layer filter fields

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | If Kessel returns IDs that don't match what the query layer filters on, access control is broken |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class
- `baker.make(Provider, uuid="cluster-uuid-1")` and related test data

**Steps:**
- **Given** a `Provider` with `uuid="cluster-uuid-1"` exists in the database
- **When** `KesselAccessProvider` returns `{"openshift.cluster": {"read": ["cluster-uuid-1"]}}` (mocked)
- **Then** `QueryParameters._set_access()` can use `"cluster-uuid-1"` to filter and the provider is included in results

**Acceptance Criteria:**
- The resource ID from Kessel matches the DB field used in query filtering
- This holds for all 10 resource types in the mapping table

---

### CT-KESSEL-AP-003: Empty access from Kessel matches None from RBAC

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | A user with no permissions must be treated identically by both backends |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** RBAC returns `None` (no ACLs) and Kessel returns `None` (all lookups empty)
- **When** both values are passed to `IdentityHeaderMiddleware`
- **Then** the user receives the same experience (permission denied on protected endpoints)

**Acceptance Criteria:**
- Both backends return `None` for users with no access
- Permission classes deny access consistently

---

## 5. Tier 4 -- E2E Tests (E2E)

Requires full Kessel stack deployed on OCP: relations-api + inventory-api + SpiceDB + PostgreSQL + Kafka.

---

### E2E-KESSEL-FLOW-001: Complete auth flow -- seed, report, bind, query

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Validates the entire authorization chain against the real Kessel API surface |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- Fresh org with seeded roles

**Steps:**
- **Given** Kessel is deployed and roles are seeded via `kessel_seed_roles`
- **And** an OCP cluster is registered (resource reported to Kessel Inventory API)
- **And** a role binding is created for user `test-user` with `viewer` role on the tenant
- **When** `test-user` makes a GET request to `/api/cost-management/v1/reports/openshift/costs/`
- **Then** the response is HTTP 200 and includes data for the registered cluster

**Acceptance Criteria:**
- Role seeding completes without error
- Resource reporting writes to Kessel Inventory
- `LookupResources` returns the cluster UUID for `test-user`
- Cost report query returns data filtered to the authorized cluster

---

### E2E-KESSEL-FLOW-002: User without binding gets empty results

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Validates that authorization actually restricts access, not just grants it |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User `no-access-user` with NO role bindings

**Steps:**
- **Given** Kessel is deployed and an OCP cluster is registered
- **And** `no-access-user` has NO role bindings
- **When** `no-access-user` makes a GET request to `/api/cost-management/v1/reports/openshift/costs/`
- **Then** the response is HTTP 403 or HTTP 200 with empty data

**Acceptance Criteria:**
- `LookupResources` returns empty for `no-access-user`
- User sees no cost data

---

### E2E-KESSEL-FLOW-003: Role binding revocation takes effect immediately

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Revoking access must be immediate, not delayed by cache TTL |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User `test-user` with an active role binding

**Steps:**
- **Given** `test-user` has a role binding and can see cluster data
- **When** the role binding is deleted via `DELETE /api/cost-management/v1/access-management/role-bindings/{id}/`
- **And** `test-user` makes another GET request immediately
- **Then** the response no longer includes the previously authorized cluster data

**Acceptance Criteria:**
- Cache is invalidated on binding deletion
- Subsequent request reflects revoked access

---

### E2E-KESSEL-FLOW-004: Pipeline-driven sync registers nodes and projects

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Validates that the data pipeline correctly reports OCP resources to Kessel |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"` and an OCP source configured
- Test OCP data ingested through the pipeline

**Steps:**
- **Given** an OCP source is registered and data is ingested through the Koku pipeline
- **When** the pipeline runs and `populate_openshift_cluster_information_tables()` completes
- **Then** nodes and projects from the OCP data appear in Kessel Inventory
- **And** `LookupResources` for a user with tenant-level viewer role returns those nodes and projects

**Acceptance Criteria:**
- `KesselSyncedResource` rows created with `kessel_synced=True`
- `LookupResources` returns the reported node names and project namespaces
- User can query OCP data filtered by authorized nodes/projects

---

### E2E-KESSEL-FLOW-005: Cost model creation visible via Kessel authorization

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Cost models created via API must be queryable through Kessel-authorized endpoints |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User with cost model write permission (role binding)

**Steps:**
- **Given** a user with cost model write access creates a cost model via `POST /api/cost-management/v1/cost-models/`
- **When** the cost model is created successfully
- **Then** the cost model is reported to Kessel Inventory
- **And** the user can see the cost model via `GET /api/cost-management/v1/cost-models/`

**Acceptance Criteria:**
- Cost model creation succeeds (HTTP 201)
- `KesselSyncedResource` row created
- `LookupResources` for `cost_management/cost_model` returns the new cost model UUID
- GET request returns the cost model

---

### E2E-KESSEL-FLOW-006: ENHANCED_ORG_ADMIN bootstrap flow

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Validates the complete on-prem bootstrap path from zero to configured |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`, `ENHANCED_ORG_ADMIN=true`
- Fresh org with no role bindings

**Steps:**
- **Given** a fresh deployment with `ENHANCED_ORG_ADMIN=true` and roles seeded
- **When** an org admin logs in
- **Then** the admin has full access (bypass)
- **When** the admin creates a role binding for another user via Access Management API
- **And** `ENHANCED_ORG_ADMIN` is set to `false` and Koku is restarted
- **Then** the admin's access is now governed by Kessel role bindings
- **And** the other user has the assigned role's permissions

**Acceptance Criteria:**
- Admin has full access during bootstrap
- Role binding creation succeeds
- After disabling ENHANCED_ORG_ADMIN, both users' access is governed by Kessel

---

## 6. Coverage Summary

### 6.1 Scenario Count by Tier

| Tier | Count | P0 | P1 | P2 | P3 |
|------|-------|----|----|----|-----|
| UT   | 17    | 6  | 8  | 3  | 0   |
| IT   | 9     | 2  | 7  | 0  | 0   |
| CT   | 3     | 2  | 1  | 0  | 0   |
| E2E  | 6     | 2  | 4  | 0  | 0   |
| **Total** | **35** | **12** | **20** | **3** | **0** |

### 6.2 Phase Coverage

| Phase | UT | IT | CT | E2E | Total |
|-------|----|----|----|-----|-------|
| 1     | 14 | 7  | 0  | 0   | 21    |
| 1.5   | 3  | 2  | 0  | 0   | 5     |
| 2     | 0  | 0  | 3  | 6   | 9     |
| **Total** | **17** | **9** | **3** | **6** | **35** |

### 6.3 Module Coverage

| Module | UT | IT | CT | E2E | Total |
|--------|----|----|-----|-----|-------|
| KESSEL | 17 | 0  | 3   | 6   | 26    |
| MW     | 0  | 5  | 0   | 0   | 5     |
| API    | 0  | 3  | 0   | 0   | 3     |
| MASU   | 0  | 1  | 0   | 0   | 1     |
| COSTMODEL | 0 | 1 | 0  | 0   | 1     |
| SETTINGS | 0 | 0 | 0  | 0   | 0     |

### 6.4 Unit Test Coverage Target

Target: >80% on `koku/kessel/` module.

Covered by UT scenarios:
- `access_provider.py` -- UT-KESSEL-AP-001 through AP-006 (6 scenarios)
- `client.py` -- UT-KESSEL-CL-001 through CL-003 (3 scenarios)
- `resource_reporter.py` -- UT-KESSEL-RR-001 through RR-004 (4 scenarios)
- `models.py` -- UT-KESSEL-MDL-001 (1 scenario)
- `management/commands/kessel_seed_roles.py` -- UT-KESSEL-SEED-001, SEED-002 (2 scenarios)
- `management/commands/kessel_update_schema.py` -- UT-KESSEL-SCHEMA-001 (1 scenario)
- `views.py` -- UT-KESSEL-VIEW-001 through VIEW-003 (3 scenarios, uses IamTestCase but tests view logic)

Files not directly covered by UT (covered by IT/CT/E2E or trivial):
- `__init__.py` -- empty
- `apps.py` -- Django boilerplate
- `urls.py` -- declarative routing (covered by IT-API-URL-001/002)
- `serializers.py` -- covered by UT-KESSEL-VIEW-* indirectly
- `exceptions.py` -- single class definition, tested through AP-003

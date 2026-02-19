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

### UT-KESSEL-AP-001: Authorized user sees only their permitted OCP clusters

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | A user authorized for 2 specific clusters must see cost data for exactly those clusters and no others |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning mock where `lookup_resources` returns `["cluster-uuid-1", "cluster-uuid-2"]` for `cost_management/openshift_cluster`
- `@override_settings(AUTHORIZATION_BACKEND="rebac", KESSEL_CACHE_TTL=300)`

**Steps:**
- **Given** a user who has Kessel role bindings granting read access to 2 OCP clusters
- **When** the middleware resolves their access through `KesselAccessProvider`
- **Then** the user's access dict enables the query layer to filter OCP cost data to exactly `cluster-uuid-1` and `cluster-uuid-2`
- **And** the access dict is consumable by every resource type view and permission class without modification

**Acceptance Criteria:**
- The access dict produced by `KesselAccessProvider` is structurally identical to what `RbacService` would produce, ensuring the query layer works without changes
- The user's authorized cluster UUIDs are the exact values returned by Kessel, with no interpretation or transformation
- Every resource type defined in `RESOURCE_TYPES` has a corresponding entry in the access dict, even if the user has no access to that type

---

### UT-KESSEL-AP-002: User with no Kessel permissions is denied all access

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | A user with no role bindings in Kessel must be denied access to all cost management data |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning mock where `lookup_resources` returns `[]` for all resource types
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a user who has no Kessel role bindings for any cost management resource
- **When** the middleware resolves their access through `KesselAccessProvider`
- **Then** the user is denied access to all cost management endpoints, matching the behavior when RBAC returns no ACLs

**Acceptance Criteria:**
- The middleware receives a signal equivalent to "no permissions" that permission classes use to deny access
- This behavior is identical to how RBAC handles users with no cost-management roles

---

### UT-KESSEL-AP-003: Kessel outage blocks the request with a clear error

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | When Kessel is unavailable, users must receive an actionable error (HTTP 424) rather than a silent failure or incorrect access |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` where `lookup_resources` raises `grpc.RpcError`
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** Kessel's Relations API is unreachable
- **When** the middleware attempts to resolve a user's access
- **Then** a `KesselConnectionError` propagates to the middleware, which returns HTTP 424 (Failed Dependency) identifying Kessel as the failing service

**Acceptance Criteria:**
- The request fails fast rather than granting incorrect access (fail-closed behavior)
- The error identifies which resource type lookup failed, enabling operators to diagnose the issue

---

### UT-KESSEL-AP-004: Every cost management resource type is queryable through Kessel

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | If a resource type is missing from the Kessel mapping, users cannot be authorized for that resource type, silently breaking access control |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** Koku defines 10 resource types in `RESOURCE_TYPES` (aws.account, aws.organizational_unit, gcp.account, gcp.project, azure.subscription_guid, openshift.cluster, openshift.node, openshift.project, cost_model, settings)
- **When** the `KOKU_TO_KESSEL_TYPE_MAP` and `KOKU_TO_KESSEL_PERMISSION_MAP` constants are validated
- **Then** every Koku resource type maps to a Kessel resource type, and every Koku operation (read, write) maps to a Kessel permission

**Acceptance Criteria:**
- All 10 Koku resource types have Kessel type mappings (e.g., `openshift.cluster` -> `cost_management/openshift_cluster`)
- Both operations (`read` -> `read`, `write` -> `all`) are mapped
- No runtime `KeyError` is possible when iterating `RESOURCE_TYPES`

---

### UT-KESSEL-AP-005: User with partial access sees only authorized resources across types

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | A real-world user (e.g., OCP viewer with no cloud access) must see OCP cost data but not AWS/Azure/GCP data |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning: 2 clusters for `openshift_cluster`, nothing for `aws_account`, 1 cost model for `cost_model` (both read and write)
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a user authorized for 2 OCP clusters and 1 cost model, but no AWS accounts
- **When** the middleware resolves their access through `KesselAccessProvider`
- **Then** the user can view OCP cost reports filtered to their 2 clusters, can read and write their cost model, and is denied access to any AWS cost data

**Acceptance Criteria:**
- OCP cluster access contains exactly the 2 authorized cluster UUIDs
- AWS account access is empty, resulting in no AWS data visible to the user
- Cost model access includes the UUID for both read and write operations
- The access dict is directly usable by `QueryParameters._set_access()` and `CostModelViewSet.get_queryset()` without transformation

---

### UT-KESSEL-AP-006: Application uses the correct authorization backend based on deployment configuration

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | If the wrong backend is selected, all authorization decisions are incorrect -- RBAC users hit Kessel (which may not exist) or Kessel users hit RBAC (which doesn't exist on-prem) |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- Reset `_provider_instance` to `None` between test runs

**Steps:**
- **Given** a deployment configured with `AUTHORIZATION_BACKEND="rebac"`
- **When** the application initializes the authorization provider
- **Then** all authorization queries are routed to Kessel via `KesselAccessProvider`
- **Given** a deployment configured with `AUTHORIZATION_BACKEND="rbac"`
- **When** the application initializes the authorization provider
- **Then** all authorization queries are routed to the RBAC service via `RBACAccessProvider`

**Acceptance Criteria:**
- ReBAC configuration produces a provider that calls Kessel gRPC APIs
- RBAC configuration produces a provider that calls the RBAC HTTP API
- The provider is a singleton -- all concurrent requests use the same instance

---

### UT-KESSEL-CL-001: Development deployments connect to Kessel without TLS

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Development and non-TLS environments must be able to connect to Kessel without certificate configuration |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(KESSEL_RELATIONS_CONFIG={"host": "localhost", "port": 9000, "tls_enabled": False, "tls_cert_path": ""})`
- `@patch("grpc.insecure_channel")`

**Steps:**
- **Given** a development deployment with TLS disabled in Kessel configuration
- **When** the Kessel client establishes a connection to the Relations API
- **Then** the connection is made over an insecure (plaintext) gRPC channel to `localhost:9000`

**Acceptance Criteria:**
- The client connects successfully without requiring TLS certificates
- No TLS-related errors or certificate validation occurs
- The connection target matches the configured host and port

---

### UT-KESSEL-CL-002: Production deployments connect to Kessel with TLS encryption

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Production gRPC traffic must be encrypted; plaintext connections would expose authorization data |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(KESSEL_RELATIONS_CONFIG={"host": "kessel.example.com", "port": 443, "tls_enabled": True, "tls_cert_path": "/certs/ca.pem"})`
- `@patch("grpc.secure_channel")`
- `@patch("builtins.open", mock_open(read_data=b"cert-data"))`

**Steps:**
- **Given** a production deployment with TLS enabled and a CA certificate configured
- **When** the Kessel client establishes a connection to the Relations API
- **Then** the connection is made over a TLS-encrypted gRPC channel using the configured certificate

**Acceptance Criteria:**
- The client uses the CA certificate from the configured path to establish trust
- The connection targets the production host and port over a secure channel
- Plaintext connections are not attempted

---

### UT-KESSEL-CL-003: Concurrent requests share a single Kessel connection

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Creating a new gRPC connection per request would exhaust resources under load; all requests must share a single managed connection |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- Reset `_client_instance` to `None`
- `@patch("kessel.client.KesselClient")`

**Steps:**
- **Given** the Kessel client has not been initialized yet
- **When** 10 concurrent HTTP requests trigger authorization checks simultaneously
- **Then** all 10 requests share the same Kessel client and gRPC channel

**Acceptance Criteria:**
- Only one gRPC connection is established regardless of concurrency
- No race condition causes duplicate client initialization
- All threads receive authorization responses from the shared connection

---

### UT-KESSEL-RR-001: RBAC deployments are completely unaffected by Kessel resource tracking

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | SaaS deployments using RBAC must incur zero overhead from Kessel -- no gRPC connections, no database writes, no latency impact |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`
- `@patch("kessel.resource_reporter.get_kessel_client")`
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects")`

**Steps:**
- **Given** a SaaS deployment configured with RBAC authorization
- **When** a new OCP cluster is registered and the resource reporter is invoked
- **Then** no gRPC connections to Kessel are attempted and no resource tracking rows are written to the database

**Acceptance Criteria:**
- RBAC deployments experience no Kessel-related side effects on any resource creation path
- No network calls, no database writes, no log entries related to Kessel sync

---

### UT-KESSEL-RR-002: New resources become authorized through Kessel after reporting

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | When a new OCP cluster is registered, users with appropriate role bindings must be able to see its cost data -- this requires the resource to be reported to Kessel |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` with mock client
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, True)`

**Steps:**
- **Given** a ReBAC deployment where a new OCP cluster `uuid-1` is registered for org `org123`
- **When** the resource reporter processes this new cluster
- **Then** the cluster is reported to Kessel's Inventory API so that `LookupResources` will include it for authorized users
- **And** a tracking record is created to confirm successful synchronization

**Acceptance Criteria:**
- The cluster is reported to Kessel Inventory with the correct type, ID, and org association
- The tracking record reflects successful sync, enabling operators to audit Kessel state
- After reporting, `LookupResources` for authorized users would return this cluster UUID

---

### UT-KESSEL-RR-003: Resource creation succeeds even when Kessel is temporarily unavailable

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | A Kessel outage must not prevent clusters, nodes, or cost models from being created in Postgres -- cost data ingestion must continue |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` where `report_resource` raises `Exception`
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, True)`

**Steps:**
- **Given** a ReBAC deployment where Kessel's Inventory API is temporarily unreachable
- **When** a new OCP cluster is registered
- **Then** the cluster is created in Postgres successfully, and the tracking record marks it as pending sync for retry on the next pipeline cycle

**Acceptance Criteria:**
- The resource creation in Postgres is not blocked or rolled back
- The tracking record indicates the resource has not yet been synced to Kessel
- A warning is logged so operators can detect the sync backlog
- The next pipeline run will retry the sync (idempotent)

---

### UT-KESSEL-RR-004: Pipeline reruns do not create duplicate resources in Kessel

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | OCP data pipelines reprocess data regularly; duplicate resources in Kessel would cause incorrect authorization results |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.get_kessel_client")` with mock client
- `@patch("kessel.resource_reporter.KesselSyncedResource.objects.update_or_create")` returning `(mock_obj, False)` (existing row)

**Steps:**
- **Given** a cluster that was already reported to Kessel in a previous pipeline run
- **When** the pipeline reruns and the resource reporter is invoked for the same cluster
- **Then** the resource is re-reported to Kessel (idempotent) and the tracking record is refreshed, but no duplicate records are created

**Acceptance Criteria:**
- The same resource reported twice results in exactly one tracking record and one Kessel resource
- The sync timestamp is updated to reflect the latest successful sync
- No errors or duplicate key violations occur

---

### UT-KESSEL-MDL-001: Each resource is tracked exactly once per organization

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | If a resource could have multiple tracking rows, sync state becomes ambiguous and operators cannot reliably audit which resources are synchronized |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class with database

**Steps:**
- **Given** a tracking record exists for cluster `uuid-1` in org `org123`
- **When** a duplicate record with the same resource type, ID, and org is inserted directly (bypassing upsert)
- **Then** the database enforces uniqueness and rejects the duplicate

**Acceptance Criteria:**
- The database constraint ensures exactly one tracking row per (resource_type, resource_id, org_id) combination
- This is enforced at the database level, not just application logic, preventing race conditions

---

### UT-KESSEL-SEED-001: Role seeding command is safe to run in RBAC environments

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Helm charts run management commands unconditionally; the command must be harmless in SaaS RBAC deployments where Kessel does not exist |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`

**Steps:**
- **Given** a SaaS deployment configured with RBAC authorization (no Kessel available)
- **When** the `kessel_seed_roles` management command is executed (e.g., as a Helm post-install hook)
- **Then** the command completes successfully without attempting any Kessel connections or creating any roles

**Acceptance Criteria:**
- The command exits cleanly with a skip message
- No gRPC connections are attempted (Kessel may not even be deployed)
- The command can be run repeatedly in RBAC environments without side effects

---

### UT-KESSEL-SEED-002: All 5 SaaS production roles are created in Kessel

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Administrators must be able to assign the same 5 roles available in SaaS production. Missing roles means admins cannot grant the expected access levels |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client that records `create_tuples` calls

**Steps:**
- **Given** a ReBAC deployment during initial setup
- **When** the `kessel_seed_roles` command is executed with default (embedded) role definitions
- **Then** all 5 standard Cost Management roles from SaaS production are created in Kessel

**Acceptance Criteria:**
- Exactly 5 roles are seeded: Cost Administrator (`cost-administrator`), Cost OpenShift Viewer (`cost-openshift-viewer`), Cost Price List Administrator (`cost-price-list-administrator`), Cost Price List Viewer (`cost-price-list-viewer`), Cost Cloud Viewer (`cost-cloud-viewer`)
- Running the command a second time succeeds without errors (idempotent via upsert)
- The roles match the definitions in `RedHatInsights/rbac-config/configs/prod/roles/cost-management.json`

---

### UT-KESSEL-SEED-003: Cost Administrator role grants access to all cost management resource types

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | A Cost Administrator must have full access to every cost management resource type. If any permission is missing, admins silently lose access to that resource type |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client

**Steps:**
- **Given** a ReBAC deployment during role seeding
- **When** the `kessel_seed_roles` command creates the Cost Administrator role
- **Then** the role is granted all 23 cost_management permissions from the production ZED schema, covering every resource type (OCP clusters/nodes/projects, AWS accounts/OUs, Azure subscriptions, GCP accounts/projects, cost models, settings)

**Acceptance Criteria:**
- The Cost Administrator role has exactly 23 permission relations matching the production `rbac/role` schema
- The role covers all resource types: OCP (6 relations), AWS (4), Azure (2), GCP (4), cost model (3), settings (3), plus the global `all_all` (1)
- A user assigned this role can access cost data for every resource type through `LookupResources`

---

### UT-KESSEL-SEED-004: Cost OpenShift Viewer role grants only OCP cluster access

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | The OCP viewer role must be scoped to OCP clusters only; granting cloud or settings access would violate the principle of least privilege |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client

**Steps:**
- **Given** a ReBAC deployment during role seeding
- **When** the `kessel_seed_roles` command creates the Cost OpenShift Viewer role
- **Then** the role is granted only OCP cluster read and all permissions, and no permissions for cloud providers, cost models, or settings

**Acceptance Criteria:**
- The role has exactly 2 permission relations: `t_cost_management_openshift_cluster_all` and `t_cost_management_openshift_cluster_read`
- A user assigned this role can see OCP cluster cost data but cannot access AWS, Azure, GCP, cost model, or settings data

---

### UT-KESSEL-SEED-005: Every RBAC permission string from SaaS role definitions has a Kessel mapping

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | An unmapped RBAC permission means that role grants no Kessel access for the affected resource type, silently breaking authorization for users with that role |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** the SaaS production role definitions contain 11 unique RBAC permission strings across 5 roles
- **When** the permission mapping constant is validated against all role definitions
- **Then** every RBAC permission string resolves to at least one Kessel relation

**Acceptance Criteria:**
- All 11 RBAC permission patterns are mapped: `cost-management:*:*`, `cost-management:cost_model:*`, `cost-management:cost_model:read`, `cost-management:settings:*`, `cost-management:settings:read`, `cost-management:openshift.cluster:*`, `cost-management:aws.account:*`, `cost-management:aws.organizational_unit:*`, `cost-management:azure.subscription_guid:*`, `cost-management:gcp.account:*`, `cost-management:gcp.project:*`
- No RBAC permission string from any role causes a lookup failure during seeding

---

### UT-KESSEL-SEED-006: Air-gapped deployments can seed roles from a local file

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | On-prem environments without internet access must be able to seed roles from a file shipped with the deployment, rather than fetching from GitHub |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- Temporary JSON file with `cost-management.json` content

**Steps:**
- **Given** an air-gapped on-prem deployment with a local copy of the role definitions file
- **When** `kessel_seed_roles --roles-file /path/to/cost-management.json` is executed
- **Then** roles are loaded from the local file and seeded with the same permission mappings as the embedded defaults

**Acceptance Criteria:**
- The command reads role definitions from the specified file path
- The same 5 roles with identical permission mappings are created as with the embedded defaults
- No network requests are made to GitHub or any external service

---

### UT-KESSEL-SCHEMA-001: Helm upgrade hooks do not apply redundant schema changes

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Schema migrations are sensitive operations; running them unnecessarily risks data corruption or downtime |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac", KESSEL_SCHEMA_VERSION="1")`
- `@patch` deployed version to return `"1"`

**Steps:**
- **Given** the Kessel schema is already at the target version
- **When** the `kessel_update_schema` command runs (e.g., during a Helm upgrade)
- **Then** the command detects the schema is current and completes without applying any migrations

**Acceptance Criteria:**
- The command skips migration when the deployed version matches the target
- No schema modification calls are made to Kessel
- The command can be run repeatedly without side effects

---

### UT-KESSEL-VIEW-001: Administrators can see available roles for assignment

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Administrators must know which roles exist before they can assign them to users; without a role listing, role binding creation is a guessing game |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` returning mock with 5 seeded roles

**Steps:**
- **Given** a ReBAC deployment where the 5 standard Cost Management roles have been seeded
- **When** an administrator requests the list of available roles via the Access Management API
- **Then** all 5 roles are returned with their names and permission descriptions

**Acceptance Criteria:**
- The API response includes all 5 production roles (Cost Administrator, Cost OpenShift Viewer, Cost Price List Administrator, Cost Price List Viewer, Cost Cloud Viewer)
- Each role includes enough information for the administrator to make an informed assignment decision
- The response is HTTP 200

---

### UT-KESSEL-VIEW-002: Assigning a role to a user takes effect immediately

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | When an admin assigns a role to a user, that user must see the authorized data on their very next request -- not after a cache TTL expires |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- `@patch("django.core.cache.caches")` with mock cache

**Steps:**
- **Given** an administrator assigning the Cost OpenShift Viewer role to user `alice` in org `org123`
- **When** the role binding is created via the Access Management API
- **Then** the role binding is written to Kessel and alice's cached access is invalidated so her next request fetches fresh permissions

**Acceptance Criteria:**
- The role binding relationship is created in Kessel (subject=alice, role=cost-openshift-viewer, scope=org123)
- Alice's cached authorization data is purged, forcing a fresh `LookupResources` on her next request
- The API returns HTTP 201 confirming the binding was created

---

### UT-KESSEL-VIEW-003: Revoking a role from a user takes effect immediately

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | When an admin revokes access, the user must lose access on their very next request -- delayed revocation is a security risk |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- `@patch("django.core.cache.caches")` with mock cache

**Steps:**
- **Given** user `alice` has a Cost OpenShift Viewer role binding in org `org123`
- **When** an administrator revokes that role binding via the Access Management API
- **Then** the role binding is removed from Kessel and alice's cached access is invalidated so her next request reflects the revocation

**Acceptance Criteria:**
- The role binding relationship is deleted from Kessel
- Alice's cached authorization data is purged immediately
- Alice's next request results in a fresh `LookupResources` that no longer includes the revoked role's permissions
- The API returns HTTP 204 confirming the deletion

---

### UT-SETTINGS-CFG-001: On-prem deployment forces ReBAC authorization regardless of AUTHORIZATION_BACKEND value

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | On-prem deployments must always use Kessel authorization. Allowing an operator to accidentally set `AUTHORIZATION_BACKEND=rbac` would break the deployment since RBAC does not exist on-prem |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(KOKU_ONPREM_DEPLOYMENT=True, AUTHORIZATION_BACKEND="rbac")`

**Steps:**
- **Given** an on-prem deployment where the operator has mistakenly set `AUTHORIZATION_BACKEND=rbac`
- **When** the application resolves the effective authorization backend at startup
- **Then** the effective backend is `rebac` (forced), overriding the operator's misconfiguration

**Acceptance Criteria:**
- `KOKU_ONPREM_DEPLOYMENT=True` always forces `AUTHORIZATION_BACKEND` to `rebac`
- A warning is logged when the override occurs, alerting the operator to the misconfiguration
- SaaS deployments (`KOKU_ONPREM_DEPLOYMENT=False`) respect the configured value

---

### UT-SETTINGS-CFG-002: Default authorization backend is RBAC for SaaS deployments

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | SaaS deployments that have not explicitly opted into Kessel must continue using RBAC. An incorrect default would break all SaaS cost management authorization |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- No `AUTHORIZATION_BACKEND` environment variable set
- `KOKU_ONPREM_DEPLOYMENT=False`

**Steps:**
- **Given** a SaaS deployment with no explicit `AUTHORIZATION_BACKEND` configuration
- **When** the application reads the authorization backend setting
- **Then** the default is `rbac`, maintaining backward compatibility with the existing SaaS authorization flow

**Acceptance Criteria:**
- The default value is `"rbac"` when the environment variable is not set
- The RBAC service is used for authorization, and no Kessel connections are attempted

---

### UT-KESSEL-SEED-007: Role seeding command supports dry-run mode for safe validation

| Field | Value |
|-------|-------|
| Priority | P2 (Medium) |
| Business Value | Operators must be able to validate what roles will be seeded before committing to a live Kessel instance, especially in production environments |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client

**Steps:**
- **Given** a ReBAC deployment where the operator wants to preview the role seeding
- **When** `kessel_seed_roles --dry-run` is executed
- **Then** the command outputs the roles and permissions that would be created, but makes no Kessel API calls

**Acceptance Criteria:**
- The command output lists all 5 roles with their permission mappings
- No `create_tuples` calls are made to Kessel
- The operator can use the output to verify correct configuration before running for real

---

### UT-KESSEL-SCHEMA-002: Schema update command applies migrations when version is behind

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | When a new Kessel schema version is deployed, the update command must apply the migration. If it silently skips, the schema is out of date and authorization queries may fail |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac", KESSEL_SCHEMA_VERSION="2")`
- `@patch` deployed version to return `"1"`

**Steps:**
- **Given** the deployed schema is at version 1 and the target is version 2
- **When** the `kessel_update_schema` command runs
- **Then** the schema migration from version 1 to version 2 is applied to Kessel

**Acceptance Criteria:**
- The migration is applied and the deployed version is updated to 2
- The command logs the migration that was applied for audit purposes
- If the migration fails, the error is reported clearly (not swallowed)

---

### UT-KESSEL-VIEW-004: Administrators can list existing role bindings

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Administrators need to see who has what access to audit and manage permissions. Without a listing endpoint, they cannot verify or troubleshoot access issues |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client returning 3 role bindings

**Steps:**
- **Given** a ReBAC deployment with 3 existing role bindings (2 users with Cost OpenShift Viewer, 1 with Cost Administrator)
- **When** an administrator requests the list of role bindings via `GET /api/cost-management/v1/access-management/role-bindings/`
- **Then** all 3 bindings are returned with user, role, and scope information

**Acceptance Criteria:**
- The response includes the subject (user), role name, and scope for each binding
- The list is scoped to the administrator's organization
- The response is HTTP 200

---

### UT-KESSEL-AP-007: OCP inheritance replicates RBAC cascade -- cluster access grants node and project access

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | RBAC grants wildcard node and project access to users with cluster access. If Kessel does not replicate this cascade, users with cluster-level roles lose node and project visibility, breaking RBAC parity |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class
- `@patch("kessel.client.get_kessel_client")` returning `["cluster-1"]` for cluster lookup, `[]` for node and project lookups
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a user with a role binding that grants `openshift.cluster:read` for `cluster-1`, but no explicit node or project bindings
- **When** `KesselAccessProvider` resolves the user's access
- **Then** the user has access to cluster `cluster-1` AND wildcard access to all nodes and all projects within that cluster (replicating RBAC's cascade behavior)

**Acceptance Criteria:**
- Cluster access automatically implies node and project access (downward cascade)
- The cascade matches `rbac.py` `_update_access_obj()` logic: cluster -> wildcard node -> wildcard project
- Node access does NOT cascade upward to cluster access

---

### UT-KESSEL-RR-005: Resource type names use Kessel naming convention, not Koku RBAC convention

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Koku/RBAC uses dots in resource types (e.g., `openshift.cluster`) while Kessel uses underscores (e.g., `openshift_cluster`). If the reporter sends the wrong format, Kessel rejects or misroutes the resource |
| Phase | 1 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** Koku's `RESOURCE_TYPES` uses dots (e.g., `openshift.cluster`) and Kessel Inventory expects underscores (e.g., `cost_management/openshift_cluster`)
- **When** the resource reporter maps a Koku resource type to a Kessel type
- **Then** the mapping correctly translates dots to the Kessel naming convention

**Acceptance Criteria:**
- Every resource type in `KOKU_TO_KESSEL_TYPE_MAP` correctly maps from dot notation to underscore notation
- The reporter never sends dot-notation types to Kessel APIs

---

## 3. Tier 2 -- Integration Tests (IT)

---

### IT-MW-AUTH-006: Assigning a role to a group invalidates cache for all group members

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | When a role is bound to a group, all members must see updated access on their next request. If only the group principal's cache is cleared, individual members continue with stale permissions |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.client.get_kessel_client")` with mock client
- `@patch("django.core.cache.caches")` with mock cache
- 3 users in the target group

**Steps:**
- **Given** users Alice, Bob, and Carol are members of group `ocp-viewers`
- **When** an administrator binds the Cost OpenShift Viewer role to group `ocp-viewers`
- **Then** the cached access for Alice, Bob, and Carol is all invalidated

**Acceptance Criteria:**
- Cache entries for all 3 group members are purged
- Each member's next request triggers a fresh `LookupResources` reflecting the new role binding

---

### IT-MW-AUTH-001: ReBAC deployments authorize users through Kessel, not RBAC

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | On-prem deployments have no RBAC service; every request must be authorized through Kessel or users get errors instead of cost data |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` returning mock access dict with 2 clusters
- Valid `x-rh-identity` header

**Steps:**
- **Given** an on-prem deployment configured with ReBAC authorization
- **When** a user makes a request to a cost management endpoint
- **Then** the user's permissions are resolved through Kessel (not the RBAC HTTP service) and the user can access their authorized cost data

**Acceptance Criteria:**
- Authorization is resolved through the Kessel gRPC API
- The RBAC HTTP service is not contacted
- The user's request proceeds with the access permissions returned by Kessel

---

### IT-MW-AUTH-002: Kessel authorization results are cached to avoid repeated gRPC calls

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Without caching, every API request triggers up to 28 gRPC calls to Kessel; caching reduces this to zero for the TTL period |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` returning mock access
- Valid `x-rh-identity` header

**Steps:**
- **Given** a user making their first request (cache miss)
- **When** the user makes a second request within the cache TTL
- **Then** the second request is served from cache without contacting Kessel, and both requests receive identical authorization data

**Acceptance Criteria:**
- Kessel is contacted exactly once for two requests from the same user
- The cached authorization uses the dedicated Kessel cache (not the RBAC cache) to prevent cross-contamination between backends
- Cache entries are keyed by user and org, ensuring multi-tenant isolation

---

### IT-MW-AUTH-003: Kessel outage returns HTTP 424 identifying the failing service

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | When Kessel is down, users and operators need a clear, actionable error -- not a generic 500 that requires log diving |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.access_provider.KesselAccessProvider.get_access_for_user")` raising `KesselConnectionError`
- Valid `x-rh-identity` header

**Steps:**
- **Given** Kessel's Relations API is unreachable
- **When** a user makes any cost management API request
- **Then** the response is HTTP 424 (Failed Dependency) with a body identifying Kessel as the failing service

**Acceptance Criteria:**
- The response status is 424, not 500 or 503
- The response body identifies "Kessel" as the source of the failure
- No partial or incorrect authorization data is returned (fail-closed)

---

### IT-MW-AUTH-004: Org admins have full access during initial bootstrap before role bindings exist

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | On first deployment, no role bindings exist in Kessel yet. The org admin must be able to log in and set up role bindings for other users |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac", ENHANCED_ORG_ADMIN=True)`
- Valid `x-rh-identity` header with `is_org_admin=True`

**Steps:**
- **Given** a fresh on-prem deployment with `ENHANCED_ORG_ADMIN` enabled and no role bindings in Kessel
- **When** the org admin makes a request to any cost management endpoint
- **Then** the admin has full access to all resources without Kessel being contacted

**Acceptance Criteria:**
- The org admin can access all cost management data and APIs
- Kessel is not contacted (no gRPC calls), avoiding errors from empty role bindings
- Non-admin users in the same org are NOT bypassed -- only org admins get this treatment

---

### IT-MW-AUTH-005: New organizations get a settings resource in Kessel for settings-level permissions

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Settings permissions (e.g., currency configuration) require a settings resource to exist in Kessel; without it, `LookupResources` for settings returns nothing and settings access is broken |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Valid `x-rh-identity` header with new org_id

**Steps:**
- **Given** a request from a user in an organization that Koku has never seen before
- **When** the middleware creates the new customer record
- **Then** a settings sentinel resource is reported to Kessel for that organization, enabling settings-level permission checks

**Acceptance Criteria:**
- The settings resource is created with type `settings` and ID `settings-{org_id}`
- The customer record is created in Postgres before the Kessel reporting (Postgres is the source of truth)
- If Kessel is temporarily unavailable, the customer creation still succeeds (non-blocking)

---

### IT-API-PB-001: New OCP clusters become visible to authorized users after registration

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | When a new OCP cluster is connected through Sources, users with cluster-level role bindings must see its cost data -- if reporting fails, the cluster is invisible |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- `baker.make(Sources)` for source setup

**Steps:**
- **Given** a ReBAC deployment where a new OCP source is being registered
- **When** the `ProviderBuilder` creates the provider in Postgres
- **Then** the cluster is reported to Kessel Inventory so that `LookupResources` includes it for authorized users

**Acceptance Criteria:**
- The cluster resource is reported to Kessel with its UUID and organization
- The Postgres provider record is created regardless of Kessel reporting outcome
- Only OCP providers trigger cluster reporting (AWS/Azure/GCP do not)

---

### IT-MASU-SYNC-001: OCP nodes and projects become authorizable during data ingestion

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Fine-grained access control (e.g., "user can only see project X costs") requires each node and project to be a known resource in Kessel |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Test OCP report data with 2 nodes and 3 projects

**Steps:**
- **Given** an OCP cluster report containing nodes `["node-a", "node-b"]` and projects `["ns-1", "ns-2", "ns-3"]`
- **When** the data ingestion pipeline processes the cluster information
- **Then** all 5 resources (2 nodes + 3 projects) are reported to Kessel as individually authorizable resources

**Acceptance Criteria:**
- Each node and project is reported as a discrete Kessel resource with its correct type
- The pipeline completes successfully even if some Kessel reports fail
- Subsequent pipeline runs re-report the same resources without errors (idempotent)

---

### IT-COSTMODEL-CM-001: New cost models become authorized resources in Kessel

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Cost model read/write permissions require the model to exist in Kessel; without reporting, users with `cost_model:write` cannot discover or modify the model |
| Phase | 1 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`
- `@patch("kessel.resource_reporter.on_resource_created")`
- Valid cost model creation payload

**Steps:**
- **Given** a user with cost model write permissions creating a new cost model
- **When** the cost model is saved to Postgres
- **Then** the model is reported to Kessel Inventory so users with appropriate permissions can discover and modify it

**Acceptance Criteria:**
- The cost model resource is reported with its UUID and organization association
- The model persists in Postgres regardless of Kessel reporting outcome
- After reporting, users with cost model role bindings can find it via `LookupResources`

---

### IT-API-URL-001: Access Management API is available in ReBAC deployments

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Administrators in on-prem (ReBAC) deployments need the Access Management API to list roles and manage role bindings; without it, access control cannot be configured |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rebac")`

**Steps:**
- **Given** a ReBAC deployment
- **When** an administrator navigates to the Access Management API endpoints (roles, role-bindings)
- **Then** the endpoints are reachable and respond with valid data or appropriate authorization errors

**Acceptance Criteria:**
- `/api/cost-management/v1/access-management/roles/` returns a 200 response with role data
- The endpoints are not hidden behind a feature flag (always available when ReBAC is active)
- Unauthenticated requests are rejected with 401, not 404

---

### IT-API-URL-002: Access Management API is hidden in RBAC deployments

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | SaaS RBAC deployments manage roles through the RBAC service; exposing the Kessel Access Management API would confuse administrators and create a security surface |
| Phase | 1.5 |

**Fixtures:**
- `IamTestCase` base class
- `@override_settings(AUTHORIZATION_BACKEND="rbac")`

**Steps:**
- **Given** a SaaS deployment using RBAC authorization
- **When** a request is made to any Access Management API endpoint
- **Then** the endpoint does not exist (HTTP 404), as if it was never registered

**Acceptance Criteria:**
- The URL patterns for Access Management are not registered in the RBAC configuration
- Requesting any Access Management endpoint returns 404
- No Kessel-specific API surface is exposed in RBAC deployments

---

## 4. Tier 3 -- Contract Tests (CT)

---

### CT-KESSEL-AP-001: Query layer works identically with both RBAC and Kessel authorization

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | The entire query layer (reports, cost models, settings) was built for RBAC's access dict shape. Kessel must produce structurally identical output or every report endpoint breaks |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class
- `@patch` `RbacService.get_access_for_user` returning a known access dict (with `"*"` wildcards)
- `@patch` `KesselAccessProvider` mock returning equivalent access (explicit IDs instead of `"*"`)

**Steps:**
- **Given** an RBAC deployment where a user has wildcard access `{"openshift.cluster": {"read": ["*"]}, ...}` and a Kessel deployment where the same user has explicit access `{"openshift.cluster": {"read": ["uuid-1"]}, ...}`
- **When** both access dicts are fed to the same `QueryParameters._set_access()` method
- **Then** the query layer processes both without errors, filtering correctly in both cases

**Acceptance Criteria:**
- Both dicts have identical top-level keys (all 10 resource types)
- Both dicts have identical operation keys (`read`, `write`) under each resource type
- Both dicts produce list values (RBAC may have `["*"]`, Kessel always has explicit IDs or empty lists)
- No `KeyError`, `TypeError`, or structural mismatch occurs in the query layer

---

### CT-KESSEL-AP-002: Kessel resource IDs match the database fields that queries filter on

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | If Kessel returns resource IDs that don't match what the database stores (e.g., a name vs a UUID), the query filter will silently return no results for authorized users |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class
- `baker.make(Provider, uuid="cluster-uuid-1")` and related test data

**Steps:**
- **Given** an OCP cluster exists in Postgres with `uuid="cluster-uuid-1"`
- **When** Kessel's `LookupResources` returns `"cluster-uuid-1"` for that user
- **Then** the query layer uses that ID to filter and correctly includes the cluster's cost data in the report

**Acceptance Criteria:**
- For every resource type in the mapping, the ID format returned by Kessel matches the database field used for filtering
- This is validated for OCP clusters (UUID), OCP nodes (name), OCP projects (namespace), AWS accounts (account ID), Azure subscriptions (GUID), GCP projects (project ID), and cost models (UUID)

---

### CT-KESSEL-AP-003: Users with no permissions see the same denial regardless of backend

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | A user denied access must be denied consistently whether the deployment uses RBAC or Kessel -- inconsistent behavior would be a security risk |
| Phase | 2 |

**Fixtures:**
- `TestCase` base class

**Steps:**
- **Given** a user with no permissions -- RBAC returns `None` (no ACLs) and Kessel returns the equivalent (all resource lookups empty)
- **When** the user requests any cost management report
- **Then** both deployments deny the request identically

**Acceptance Criteria:**
- Both backends signal "no access" in a way that permission classes handle uniformly
- The user receives the same HTTP status and response body regardless of backend
- No edge case allows access when the other backend would deny it

---

## 5. Tier 4 -- E2E Tests (E2E)

Requires full Kessel stack deployed on OCP: relations-api + inventory-api + SpiceDB + PostgreSQL + Kafka.

---

### E2E-KESSEL-FLOW-001: Authorized user can view cost data through the full Kessel authorization chain

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | This validates the complete production path: roles seeded, resources reported, role binding created, and the user can see exactly the cost data they are authorized for -- proving the entire Kessel integration works end-to-end |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP (relations-api + inventory-api + SpiceDB + PostgreSQL + Kafka)
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- Fresh org with seeded roles

**Steps:**
- **Given** an on-prem deployment where roles have been seeded via `kessel_seed_roles`
- **And** an OCP cluster is registered and reported to Kessel Inventory
- **And** the administrator has created a role binding granting `cost-openshift-viewer` to user `test-user`
- **When** `test-user` requests the OCP cost report
- **Then** the response includes cost data for the authorized cluster and no other clusters

**Acceptance Criteria:**
- The entire authorization chain works: seed -> report -> bind -> query
- The user sees cost data only for the cluster their role binding grants access to
- The response matches what a user with equivalent RBAC permissions would see in SaaS

---

### E2E-KESSEL-FLOW-002: Unauthorized user is denied access to cost data

| Field | Value |
|-------|-------|
| Priority | P0 (Critical) |
| Business Value | Authorization must restrict access, not just grant it. A user with no role bindings seeing any cost data is a security failure |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User `no-access-user` with NO role bindings

**Steps:**
- **Given** an OCP cluster is registered and has cost data
- **And** `no-access-user` has no role bindings in Kessel
- **When** `no-access-user` requests the OCP cost report
- **Then** the user is denied access and sees no cost data

**Acceptance Criteria:**
- The user cannot see any cost data from any cluster
- The denial is the same behavior as an RBAC user with no cost-management roles
- The response does not leak cluster names, IDs, or any metadata about resources the user is not authorized to see

---

### E2E-KESSEL-FLOW-003: Revoking a role binding removes access on the user's next request

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Access revocation must take effect immediately -- delayed revocation means a fired employee or reassigned user retains access beyond the admin's intent |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User `test-user` with an active role binding that grants OCP cluster access

**Steps:**
- **Given** `test-user` can see cost data for their authorized cluster
- **When** the administrator revokes the role binding via the Access Management API
- **And** `test-user` makes another request immediately after revocation
- **Then** the user can no longer see the cluster's cost data

**Acceptance Criteria:**
- The user's access is revoked within one request cycle (cache invalidated on binding deletion)
- The user's subsequent response matches that of a user with no role bindings
- No stale cached access is served after revocation

---

### E2E-KESSEL-FLOW-004: Data pipeline automatically makes OCP nodes and projects authorizable

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | Fine-grained authorization (e.g., "user can see only project X") requires nodes and projects to be discovered and reported to Kessel automatically during data ingestion -- without operator intervention |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"` and an OCP source configured
- Test OCP data ingested through the pipeline

**Steps:**
- **Given** an OCP source is registered and cost data is ingested through the pipeline
- **When** the pipeline completes processing and reports resources to Kessel
- **Then** the OCP nodes and projects from the data are available as authorizable resources in Kessel
- **And** a user with a role binding that includes node-level or project-level access can see cost data filtered to those specific resources

**Acceptance Criteria:**
- Nodes and projects are automatically discovered during data ingestion (no manual registration)
- Each resource is trackable via `KesselSyncedResource` with successful sync status
- A user with project-level access sees costs only for their authorized projects

---

### E2E-KESSEL-FLOW-005: Cost model created via API is immediately queryable by authorized users

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | When an admin creates a cost model, users with cost model read access must see it immediately -- delayed visibility means incorrect cost calculations |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`
- User with cost model write permission (role binding)

**Steps:**
- **Given** a user with `cost-price-list-administrator` role binding
- **When** the user creates a new cost model via the API
- **Then** the cost model is reported to Kessel and immediately visible in the cost model listing for any user with cost model read access

**Acceptance Criteria:**
- The cost model is created in Postgres and reported to Kessel in the same request
- A different user with `cost_model:read` permission can see the new cost model on their next request
- The cost model resource in Kessel matches the UUID stored in Postgres

---

### E2E-KESSEL-FLOW-006: Complete on-prem bootstrap from zero to fully configured

| Field | Value |
|-------|-------|
| Priority | P1 (High) |
| Business Value | This validates the day-one operator experience: starting from a blank deployment, seeding roles, using the org admin bootstrap to create initial role bindings, then transitioning to fully Kessel-governed authorization |
| Phase | 2 |

**Fixtures:**
- Full Kessel stack on OCP
- Koku deployed with `AUTHORIZATION_BACKEND="rebac"`, `ENHANCED_ORG_ADMIN=true`
- Fresh org with no role bindings

**Steps:**
- **Given** a brand-new on-prem deployment with `ENHANCED_ORG_ADMIN=true` and roles seeded
- **When** the org admin logs in for the first time
- **Then** the admin has full access to all cost management data (bootstrap bypass)
- **When** the admin creates role bindings for team members via the Access Management API
- **And** `ENHANCED_ORG_ADMIN` is set to `false` and Koku is restarted
- **Then** the org admin's access is now governed by their own Kessel role bindings (not the bootstrap bypass)
- **And** team members have access matching the roles assigned to them

**Acceptance Criteria:**
- Bootstrap phase: org admin has unrestricted access, other users have no access
- Transition phase: admin can create role bindings using the Access Management API
- Post-bootstrap phase: all users (including the admin) are governed solely by their Kessel role bindings
- The transition is seamless with no data loss or access gaps

---

## 6. Coverage Summary

### 6.1 Scenario Count by Tier

| Tier | Count | P0 | P1 | P2 | P3 |
|------|-------|----|----|----|-----|
| UT   | 31    | 13 | 13 | 5  | 0   |
| IT   | 11    | 2  | 9  | 0  | 0   |
| CT   | 3     | 2  | 1  | 0  | 0   |
| E2E  | 6     | 2  | 4  | 0  | 0   |
| **Total** | **51** | **19** | **27** | **5** | **0** |

### 6.2 Phase Coverage

| Phase | UT | IT | CT | E2E | Total |
|-------|----|----|----|-----|-------|
| 1     | 27 | 8  | 0  | 0   | 35    |
| 1.5   | 4  | 3  | 0  | 0   | 7     |
| 2     | 0  | 0  | 3  | 6   | 9     |
| **Total** | **31** | **11** | **3** | **6** | **51** |

### 6.3 Module Coverage

| Module | UT | IT | CT | E2E | Total |
|--------|----|----|-----|-----|-------|
| KESSEL | 29 | 0  | 3   | 6   | 38    |
| SETTINGS | 2 | 0 | 0  | 0   | 2     |
| MW     | 0  | 6  | 0   | 0   | 6     |
| API    | 0  | 3  | 0   | 0   | 3     |
| MASU   | 0  | 1  | 0   | 0   | 1     |
| COSTMODEL | 0 | 1 | 0  | 0   | 1     |

### 6.4 Unit Test Coverage Target

Target: >80% on `koku/kessel/` module + configuration in `koku/koku/settings.py`.

Covered by UT scenarios:
- `access_provider.py` -- UT-KESSEL-AP-001 through AP-007 (7 scenarios, including OCP inheritance cascade)
- `client.py` -- UT-KESSEL-CL-001 through CL-003 (3 scenarios)
- `resource_reporter.py` -- UT-KESSEL-RR-001 through RR-005 (5 scenarios, including naming convention validation)
- `models.py` -- UT-KESSEL-MDL-001 (1 scenario)
- `management/commands/kessel_seed_roles.py` -- UT-KESSEL-SEED-001 through SEED-007 (7 scenarios, including dry-run and all role permission mappings)
- `management/commands/kessel_update_schema.py` -- UT-KESSEL-SCHEMA-001 through SCHEMA-002 (2 scenarios)
- `views.py` -- UT-KESSEL-VIEW-001 through VIEW-004 (4 scenarios, including role binding listing)
- `settings.py` configuration -- UT-SETTINGS-CFG-001 through CFG-002 (2 scenarios, KOKU_ONPREM_DEPLOYMENT derivation and defaults)

Files not directly covered by UT (covered by IT/CT/E2E or trivial):
- `__init__.py` -- empty
- `apps.py` -- Django boilerplate
- `urls.py` -- declarative routing (covered by IT-API-URL-001/002)
- `serializers.py` -- covered by UT-KESSEL-VIEW-* indirectly
- `exceptions.py` -- single class definition, tested through UT-KESSEL-AP-003

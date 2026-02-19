# Kessel/ReBAC Integration -- Handover Document

| Field | Value |
|---|---|
| Jira | [FLPATH-3294](https://issues.redhat.com/browse/FLPATH-3294) (Kessel ReBAC integration - Detailed Design and Implementation) |
| Parent story | [FLPATH-2690](https://issues.redhat.com/browse/FLPATH-2690) (Use ACM and Kessel for ReBAC) |
| Epic | [FLPATH-2799](https://issues.redhat.com/browse/FLPATH-2799) |
| Author | Jordi Gil |
| Date | 2026-02-13 |
| Purpose | Complete handover of the Kessel/ReBAC integration to the incoming team |

---

## 1. What is This Project?

Cost Management (Koku) currently uses Red Hat's RBAC service for authorization in SaaS. For on-premise deployments, RBAC is not available. This project integrates **Kessel** (Red Hat's Relationship-Based Access Control platform, built on SpiceDB) as an alternative authorization backend.

The goal is to build **deployment-agnostic authorization** in Koku: the same codebase supports both RBAC (SaaS default) and ReBAC/Kessel (on-prem mandatory, SaaS future option), selected at startup time via a single environment variable.

### What Kessel Is

- [Project Kessel GitHub](https://github.com/project-kessel)
- Built on [SpiceDB](https://authzed.com/spicedb) (Google Zanzibar-inspired authorization database)
- Uses gRPC APIs: **Relations API** (authorization checks, tuple management) and **Inventory API** (resource reporting)
- Authorization model: define relationships between subjects and resources, then query "which resources can user X access?"
- Schema language: **ZED** (defines types, relations, permissions)

### Key Kessel API Call

`LookupResources(resource_type, subject, permission)` -- returns all resource IDs of a given type that the subject has a specific permission on. This is the primary API call replacing RBAC's HTTP-based access check.

---

## 2. Current State of Work

### Branches

| Branch | Purpose | Base | Status |
|---|---|---|---|
| `kessel-integration-docs` | HLD (High-Level Design) + supporting docs | `main` | PR [#5887](https://github.com/project-koku/koku/pull/5887) open in project-koku/koku, under review |
| `FLPATH-3294/kessel-rebac-detailed-design` | DD (Detailed Design) + Test Plan | `main` | 2 commits, not pushed to upstream yet |

### Documents Created

| Document | Branch | Description |
|---|---|---|
| `docs/architecture/kessel-integration/kessel-ocp-integration.md` | `kessel-integration-docs` | High-Level Design -- architecture diagrams, sequence diagrams, phase breakdown, gap analysis |
| `docs/architecture/kessel-integration/kessel-only-role-provisioning.md` | `kessel-integration-docs` | Role provisioning details, permission mapping, management command design |
| `docs/architecture/kessel-integration/kessel-ocp-implementation-guide.md` | `kessel-integration-docs` | Implementation guidance, code-level patterns |
| `docs/architecture/kessel-integration/kessel-ocp-detailed-design.md` | `FLPATH-3294/...` | **Detailed Design** -- the primary implementation spec (12 sections, ~1180 lines) |
| `docs/architecture/kessel-integration/kessel-ocp-test-plan.md` | `FLPATH-3294/...` | **Test Plan** -- 43 test scenarios across 4 tiers, IEEE 829-inspired format |

### What Has NOT Been Built Yet

**No implementation code exists.** All work so far is documentation:
- No Python code written
- No dependencies added to Pipfile
- No Django app created
- No tests written

The project is ready to begin TDD implementation from scratch.

### Open PR Feedback

PR #5887 (HLD) is open in project-koku/koku and has review comments. The incoming team should review those comments and address any outstanding feedback before proceeding with implementation.

---

## 3. Architecture Summary

### How It Works (30-second version)

1. At startup, `AUTHORIZATION_BACKEND` is set to `"rbac"` or `"rebac"` based on `KOKU_ONPREM_DEPLOYMENT`
2. An `AccessProvider` factory returns either `RBACAccessProvider` or `KesselAccessProvider`
3. On every request, middleware calls `provider.get_access_for_user(user)` which returns a dict of resource IDs the user can access
4. Koku's existing query layer filters data by those IDs -- **zero changes needed**
5. Resources are reported to Kessel as they're created (clusters, nodes, projects, cost models)

### Authorization Flow

```
HTTP request
  -> IdentityHeaderMiddleware
    -> get_access_provider() returns RBAC or Kessel provider
    -> provider.get_access_for_user(user)
      -> [RBAC path]: HTTP call to RBAC service
      -> [Kessel path]: gRPC LookupResources() for each resource type
    -> user.access = {resource_type: {operation: [id_list]}}
  -> DRF permission classes check access
  -> Query layer filters by IDs
  -> Response
```

### Key Design Principle

`KesselAccessProvider` returns the **exact same dict shape** as `RbacService.get_access_for_user()`. The difference is RBAC may return `["*"]` (wildcard), while Kessel always returns explicit resource IDs. The query layer already handles both.

### Phases

| Phase | Scope | Checkpoint |
|---|---|---|
| 1 | AccessProvider abstraction, middleware integration, resource reporting, pipeline sync hooks, management commands | All UT + IT pass |
| 1.5 | Access Management REST API (role listing, role binding CRUD) -- Kessel-only endpoints | View tests pass |
| 2 | Contract tests (RBAC/Kessel equivalence), E2E test stubs | All 43 scenarios pass |

All three phases ship in **one PR**.

---

## 4. Key Codebase Files to Understand

Before starting implementation, familiarize yourself with these files:

### Authorization (current RBAC)

| File | What to look at |
|---|---|
| `koku/koku/rbac.py` | `RESOURCE_TYPES` dict (10 resource types), `_apply_access()` (builds the access dict), `RbacService.get_access_for_user()`, OCP inheritance cascade (lines 109-115) |
| `koku/koku/middleware.py` | `IdentityHeaderMiddleware` -- how RBAC is called, cache key format (`{user.uuid}_{org_id}`), `ENHANCED_ORG_ADMIN` bypass, `create_customer()` method |
| `koku/koku/settings.py` | `KOKU_ONPREM_DEPLOYMENT` (line 137, NOT `ONPREM`), `CacheEnum` (line 232), `CACHES` dict, `INSTALLED_APPS`, `SHARED_APPS` |

### Query Layer (unchanged, but must understand the contract)

| File | What to look at |
|---|---|
| `koku/api/query_params.py` | `_set_access()` -- checks for wildcard, applies `QueryFilter` with specific IDs |
| `koku/cost_models/view.py` | `get_queryset()` -- filters `uuid__in=read_access_list` |
| `koku/api/common/permissions/` | Permission classes that gate endpoint access |

### Resource Lifecycle (where hooks go)

| File | Method | Resource |
|---|---|---|
| `koku/api/provider/provider_builder.py` | `create_provider_from_source()` (line 116) | OCP clusters |
| `koku/masu/database/ocp_report_db_accessor.py` | `populate_openshift_cluster_information_tables()` (line 920) | Nodes, projects |
| `koku/cost_models/view.py` | `create()` (line 151) -- no `perform_create()` override exists, needs one | Cost models |

### Conventions

| Pattern | Where to look |
|---|---|
| Django app structure | `koku/api/apps.py`, `koku/cost_models/apps.py` |
| Test organization | `koku/cost_models/test/`, `koku/api/report/test/` -- always `test/` subdir, `test_*.py` files |
| Management commands | `koku/masu/management/commands/listener.py` |
| Pipfile format | `Pipfile` -- uses `>=`, `~=`, `==`, `*` for versions, Python 3.11 |
| Logging | `log_json()` utility for structured logging |

---

## 5. Critical Findings and Decisions

### Decisions Made

| Decision | Rationale |
|---|---|
| `AUTHORIZATION_BACKEND` values are `"rbac"` and `"rebac"` | Kessel is an implementation; the setting names the paradigm |
| `KOKU_ONPREM_DEPLOYMENT=true` forces `rebac` regardless of `AUTHORIZATION_BACKEND` | On-prem never runs RBAC |
| `KesselAccessProvider` returns explicit IDs, never `"*"` | Transparent pass-through; Kessel has no concept of wildcards |
| Resources are never deleted from Kessel | Preserves access to historical cost data; mirrors RBAC behavior |
| Org removal does NOT clean up Kessel | Explicit decision, documented for future revisiting |
| No Kessel workspaces in current scope | Resources link directly to tenant (org). Workspaces can be added later |
| OCP inheritance (cluster->node->project) replicated in Python code | Matches current RBAC behavior; Kessel-native containment model deferred |
| Role definitions sourced from SaaS production `rbac-config` repo | Ensures alignment with real production roles |
| Full Kessel stack for E2E testing (not just SpiceDB) | Validates real API surface; avoids invalid endpoint risk |
| TDD approach (Red-Green-Refactor) | All 43 test scenarios drive the implementation |

### Blocking External Dependency

The production ZED schema in [`rbac-config`](https://github.com/RedHatInsights/rbac-config) defines 23 `cost_management` permissions on `rbac/role` but does **NOT** wire them through `rbac/role_binding` or `rbac/tenant`. This means `LookupResources()` cannot evaluate cost management permissions even with correct role bindings.

**Action needed**: Submit a PR to `rbac-config` adding `cost_management_*` permission propagation through `rbac/role_binding` and `rbac/tenant`. See DD Section 11.4 for the exact ZED schema changes required. Unit and integration tests (which mock gRPC) are unaffected. This blocks only E2E testing.

### Confirmed: Fine-Grained Access Is RBAC Parity (Resolved)

The product manager confirmed that the requirement is **feature parity with RBAC**, not new ABAC capabilities. The example scenario:

> User A in group G has access to project P in all clusters that have that project, when the AWS account is W.

This is already possible in RBAC by creating a custom role with specific resource IDs (e.g., `openshift.project: ["project-P"]`, `aws.account: ["account-W"]`). The same works in ReBAC: role bindings scope to specific resources, and `LookupResources` returns exactly those IDs. **No architecture changes needed** -- our current DD design supports this out of the box.

The OCP inheritance cascade (cluster access auto-grants wildcard node/project access) is only relevant when cluster access is explicitly granted. If a user has only project-level or account-level access, the cascade does not fire, and the user sees only the resources they were granted.

---

## 6. Dependencies

### Python Packages to Add

| Package | PyPI name | Version | Import namespace |
|---|---|---|---|
| Relations API client | `relations-grpc-clients-python-kessel-project` | >= 0.3.11 | `kessel.relations` |
| Inventory API SDK | `kessel-sdk` | >= 2.1.0 | `kessel.inventory` |
| gRPC runtime | `grpcio` | `*` | `grpc` |

### External Services (for E2E)

Full Kessel stack: relations-api + inventory-api + SpiceDB + PostgreSQL + Kafka. Deployed on OCP for E2E tests.

### External Schema Changes

PR to `rbac-config` repo to wire `cost_management_*` permissions (see Section 5 above).

---

## 7. Implementation Plan

The TDD implementation plan is at `.cursor/plans/kessel_tdd_implementation_fe322940.plan.md` (Cursor-local) and is summarized here.

### Step Order (dependency-driven)

| Step | What | Test scenarios | Files created/modified |
|---|---|---|---|
| Prerequisites | Pipfile deps, Django app skeleton, settings | -- | `Pipfile`, `koku/koku/settings.py`, `koku/kessel/__init__.py`, `apps.py`, `exceptions.py` |
| 1. Models | `KesselSyncedResource` | UT-KESSEL-MDL-001 | `koku/kessel/models.py` |
| 2. Client | gRPC client wrapper | UT-KESSEL-CL-001..003 | `koku/kessel/client.py` |
| 3. AccessProvider | Protocol + RBAC/Kessel providers + factory | UT-KESSEL-AP-001..006 | `koku/kessel/access_provider.py` |
| 4. Resource Reporter | Transparent resource reporting | UT-KESSEL-RR-001..004 | `koku/kessel/resource_reporter.py` |
| 5. Management Commands | Role seeding + schema updates | UT-KESSEL-SEED-001..006, SCHEMA-001 | `koku/kessel/management/commands/kessel_seed_roles.py`, `kessel_update_schema.py` |
| 6. Middleware | Dual-backend dispatch | IT-MW-AUTH-001..005 | `koku/koku/middleware.py` (modify) |
| 7. Hook Points | Resource creation hooks | IT-API-PB-001, IT-MASU-SYNC-001, IT-COSTMODEL-CM-001, IT-API-URL-001..002 | `provider_builder.py`, `ocp_report_db_accessor.py`, `cost_models/view.py` (modify) |
| 8. Access Mgmt API | REST endpoints for role binding CRUD | UT-KESSEL-VIEW-001..003 | `koku/kessel/urls.py`, `views.py`, `serializers.py`, `koku/koku/urls.py` (modify) |
| 9. Contract Tests | RBAC/Kessel equivalence | CT-KESSEL-AP-001..003 | `koku/kessel/test/test_contract.py` |
| 10. E2E Stubs | IQE test stubs | E2E-KESSEL-FLOW-001..006 | IQE plugin files |

### TDD Workflow for Each Step

1. **Red**: Write failing tests first (from the test plan scenarios)
2. **Green**: Write minimal implementation to make tests pass
3. **Refactor**: Clean up, add edge cases, verify no regressions

### Running Tests

```bash
pipenv run tox -- koku.kessel.test
pipenv run tox -- koku.koku.test.test_middleware_kessel
```

---

## 8. Test Plan Summary

43 test scenarios across 4 tiers:

| Tier | Count | Description |
|---|---|---|
| UT (Unit) | 24 | Mock gRPC, `@override_settings`, `@patch`. CI-runnable |
| IT (Integration) | 10 | Middleware + hook integration, `@override_settings`. CI-runnable |
| CT (Contract) | 3 | Verify RBAC/Kessel output equivalence. CI-runnable |
| E2E | 6 | Full Kessel stack on OCP. Not CI-runnable |

Scenario ID format: `{TIER}-{MODULE}-{FEATURE}-{NNN}` (e.g., `UT-KESSEL-AP-001`)

Each scenario includes: Priority, Business Value, Fixtures, BDD Steps (Given/When/Then), Acceptance Criteria.

Full test plan: `docs/architecture/kessel-integration/kessel-ocp-test-plan.md`

---

## 9. Files to Create and Modify

### New Files (all in `koku/kessel/` Django app)

```
koku/kessel/
    __init__.py
    apps.py
    models.py                          -- KesselSyncedResource
    access_provider.py                 -- Protocol, RBACAccessProvider, KesselAccessProvider, factory
    resource_reporter.py               -- on_resource_created()
    client.py                          -- KesselClient gRPC wrapper
    exceptions.py                      -- KesselConnectionError
    urls.py                            -- Access Management API routes
    views.py                           -- DRF views
    serializers.py                     -- DRF serializers
    management/
        __init__.py
        commands/
            __init__.py
            kessel_seed_roles.py       -- Seed roles from production definitions
            kessel_update_schema.py    -- Version-checked schema updates
    test/
        __init__.py
        test_access_provider.py
        test_client.py
        test_resource_reporter.py
        test_models.py
        test_kessel_seed_roles.py
        test_kessel_update_schema.py
        test_views.py
        test_contract.py
```

### Modified Files

| File | Changes |
|---|---|
| `Pipfile` | Add 3 packages |
| `koku/koku/settings.py` | `AUTHORIZATION_BACKEND`, `KESSEL_*_CONFIG`, `CacheEnum.kessel`, cache entry, app registration |
| `koku/koku/middleware.py` | Replace `RbacService` with `get_access_provider()`, dual cache key, `KesselConnectionError` handling, settings sentinel hook |
| `koku/koku/urls.py` | Conditional Kessel URL registration |
| `koku/api/provider/provider_builder.py` | `on_resource_created()` call after provider save |
| `koku/masu/database/ocp_report_db_accessor.py` | `on_resource_created()` calls for nodes and projects |
| `koku/cost_models/view.py` | Override `perform_create()`, call `on_resource_created()` |

### Unchanged Files (important to know)

| File | Why unchanged |
|---|---|
| `koku/koku/rbac.py` | Wrapped by `RBACAccessProvider`, not modified |
| `koku/api/query_params.py` | Already handles both wildcard and ID lists |
| `koku/api/common/permissions/*.py` | Already handles both patterns |

---

## 10. Known Gotchas

| Gotcha | Details |
|---|---|
| `KOKU_ONPREM_DEPLOYMENT` not `ONPREM` | The DD says `ONPREM` but `settings.py` line 137 uses `KOKU_ONPREM_DEPLOYMENT`. The implementation must use the correct variable name |
| `CostModelViewSet` has no `perform_create()` | The view uses the default `CreateModelMixin`. An override must be added |
| `.git/info/exclude` blocks `*-plan.md` files | Force-add with `git add -f` if needed |
| OCP inheritance cascade | `rbac.py` lines 109-115: cluster access auto-grants wildcard node/project access. Must replicate in `KesselAccessProvider` |
| Kessel SDK namespace collision | Both `relations-grpc-clients-python-kessel-project` and `kessel-sdk` import as `kessel.*` -- they coexist via different submodules (`kessel.relations` vs `kessel.inventory`) |
| `RbacService.cache_ttl` | Default 30s (from `RBAC_CACHE_TTL` env var). Kessel cache uses `KESSEL_CACHE_TTL` default 300s |

---

## 11. Repositories and Links

| Resource | URL |
|---|---|
| Koku (upstream) | https://github.com/project-koku/koku |
| Koku (on-prem fork) | https://github.com/insights-onprem/koku |
| Koku (personal fork) | https://github.com/jordigilh/koku |
| Kessel Relations Python Client | https://github.com/project-kessel/relations-client-python |
| Kessel Inventory Python SDK | https://github.com/project-kessel/kessel-sdk-py |
| Kessel Project (all repos) | https://github.com/project-kessel |
| RBAC Config (roles + ZED schema) | https://github.com/RedHatInsights/rbac-config |
| Production roles JSON | https://github.com/RedHatInsights/rbac-config/blob/master/configs/prod/roles/cost-management.json |
| Production ZED schema | https://github.com/RedHatInsights/rbac-config/blob/master/configs/prod/schemas/schema.zed |
| HLD PR | https://github.com/project-koku/koku/pull/5887 |
| Jira subtask | https://issues.redhat.com/browse/FLPATH-3294 |
| Jira parent story | https://issues.redhat.com/browse/FLPATH-2690 |

---

## 12. Getting Started Checklist

1. Read the **Detailed Design** (`kessel-ocp-detailed-design.md`) end-to-end -- this is the implementation spec
2. Read the **Test Plan** (`kessel-ocp-test-plan.md`) -- this drives the TDD implementation
3. Read the **HLD** on branch `kessel-integration-docs` (`kessel-ocp-integration.md`) for architecture context
4. Review PR #5887 comments for any outstanding feedback
5. Familiarize yourself with the key codebase files listed in Section 4
6. Check out branch `FLPATH-3294/kessel-rebac-detailed-design`
7. Follow the TDD implementation plan (Section 7) starting with Prerequisites
8. Track the `rbac-config` schema PR (blocking dependency for E2E) -- see Section 5
9. Follow up with PM on fine-grained sub-cluster access control scenarios -- see Section 5

---

## 13. Contacts

| Role | Person | Context |
|---|---|---|
| Previous lead | Jordi Gil | Architecture decisions, DD/test plan author, PM relationship |
| Product manager | (ask Jordi) | Requirement for fine-grained sub-cluster access |
| Kessel team | (see project-kessel GitHub) | Schema changes, SDK questions |

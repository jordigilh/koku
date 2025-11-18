# Implementation Plan Corrections

**Date**: November 11, 2025
**Document**: `TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md`

---

## 🔍 Issues Identified and Fixed

### **1. IQE Image Not Accessible** ❌ → ✅

**Issue**: Referenced `quay.io/cloudservices/iqe-cost-management:latest` which is not accessible in on-prem environments.

**Locations**:
- Line 2819: Day 22 - IQE test pod deployment
- Line 3175: Day 27 - Blue-green deployment IQE tests

**Fix Applied**:
- ✅ Removed IQE-specific image references
- ✅ Replaced with Django management command approach
- ✅ Created `test_data_loader.py` for standalone test data loading
- ✅ Created `load_test_data` Django management command
- ✅ Updated all test execution commands to use Django's built-in test framework
- ✅ Added notes clarifying IQE is Red Hat internal and optional

**New Approach**:
```bash
# Instead of IQE pod with external image
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test \
        api.test \
        --verbosity=2 \
        --parallel=4
```

---

### **2. IQE Configuration Files** ❌ → ✅

**Issue**: Referenced IQE-specific configuration files that don't exist in standard Koku deployment.

**Locations**:
- Line 2679: `iqe_cost_management/conf.yaml`
- Line 2720: `iqe_cost_management/utils/test_data_loader.py`

**Fix Applied**:
- ✅ Replaced with Koku-native test data loader
- ✅ Created `koku/masu/database/test_data_loader.py`
- ✅ Created `koku/masu/management/commands/load_test_data.py`
- ✅ Updated all references to use Django management commands

**New Files**:
1. `koku/masu/database/test_data_loader.py` - Standalone test data loader
2. `koku/masu/management/commands/load_test_data.py` - Django management command

---

### **3. Test Count References** ⚠️ → ✅

**Issue**: Multiple references to "85 IQE tests" which may not be applicable for on-prem deployments without IQE access.

**Locations**:
- Line 64: Success criteria
- Line 2880: Day 22 deliverable
- Line 3127: Week 5 summary
- Line 3166: Production readiness checklist
- Line 3588: Final summary

**Fix Applied**:
- ✅ Changed "85 IQE tests" to "Core test suite (Django tests or IQE if available)"
- ✅ Added clarifying notes about IQE being Red Hat internal
- ✅ Emphasized Django test framework as primary approach for on-prem
- ✅ Maintained test coverage expectations without specific tool dependency

**Updated Language**:
- Before: "85 IQE tests passing (100%)"
- After: "Core test suite passing (Django tests or IQE if available)"

---

### **4. Service Name Consistency** ✅

**Status**: No issues found

**Verified**:
- ✅ Service names are consistent throughout document
- ✅ Namespace references are correct (`cost-mgmt`, `cost-mgmt-prod`, `cost-mgmt-green`)
- ✅ Service DNS names follow OpenShift conventions

**Examples**:
- `koku-api-reads.cost-mgmt-prod.svc.cluster.local:8000` ✅
- `cost-mgmt-cost-management-onprem-koku-db` ✅ (Helm release name pattern)

---

### **5. Image References** ✅

**Status**: Verified correct

**Images Used**:
1. ✅ `quay.io/jordigilh/koku:unleash-disabled` - User-provided, accessible
2. ✅ `registry.redhat.io/rhel10/postgresql-16@sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1` - Red Hat official
3. ❌ `quay.io/cloudservices/iqe-cost-management:latest` - **REMOVED** (not accessible)

---

### **6. RBAC References** ✅

**Status**: Correctly documented

**Verified**:
- ✅ RBAC bypass documented for on-prem (`DEVELOPMENT: "True"`)
- ✅ Production readiness checklist includes "RBAC configured (or bypassed for on-prem)"
- ✅ No assumptions about RBAC service availability

---

### **7. External Service Dependencies** ✅

**Status**: All dependencies documented correctly

**Verified**:
- ✅ No assumptions about external services (RBAC, Unleash, etc.)
- ✅ Unleash explicitly disabled for on-prem
- ✅ All services are self-contained within the deployment

---

## 📋 Summary of Changes

### **Files Modified**
1. `TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md` (3,575 lines)
   - Day 21: Test environment setup
   - Day 22: Test execution
   - Day 27: Blue-green deployment
   - Week 5 summary
   - Production readiness checklist
   - Final summary

### **New Approach**
- **Before**: Relied on IQE (Red Hat internal tool)
- **After**: Uses Django's built-in test framework with custom test data loader

### **Key Improvements**
1. ✅ **Standalone Testing**: No dependency on external testing frameworks
2. ✅ **On-Prem Friendly**: All components accessible in on-prem environments
3. ✅ **Flexible**: Supports both IQE (if available) and Django tests
4. ✅ **Self-Contained**: Test data loader integrated into Koku codebase

---

## 🎯 Testing Strategy (Updated)

### **Primary Approach (On-Prem)**
```bash
# 1. Load test data
python manage.py load_test_data \
    --tenant-schema=org1234567 \
    --test-data-dir=/tmp/test-data

# 2. Run Django tests
python manage.py test \
    masu.database.test \
    api.test \
    --verbosity=2 \
    --parallel=4
```

### **Alternative Approach (Red Hat Internal)**
```bash
# If you have IQE access
iqe tests plugin cost_management -v -s
```

---

## ✅ Verification Checklist

- [x] All IQE image references removed or made optional
- [x] Test data loader created as Django management command
- [x] Test execution updated to use Django test framework
- [x] All test count references updated to be tool-agnostic
- [x] Service names verified for consistency
- [x] Image references verified for accessibility
- [x] RBAC bypass documented correctly
- [x] No external service dependencies assumed

---

## 📚 Related Documents

- **Main Implementation Plan**: `TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md`
- **Summary**: `IMPLEMENTATION-PLAN-SUMMARY.md`
- **Quick Start**: `QUICK-START-GUIDE.md`

---

## 🚀 Impact Assessment

### **Impact Level**: Low
- Changes are primarily documentation and testing approach
- No impact on core migration logic or SQL files
- No impact on PostgreSQL infrastructure or custom functions
- No impact on production deployment procedures

### **Benefits**
1. ✅ **More Accessible**: Works in any environment, not just Red Hat internal
2. ✅ **More Maintainable**: Uses standard Django testing patterns
3. ✅ **More Flexible**: Supports multiple testing approaches
4. ✅ **More Realistic**: Reflects actual on-prem deployment constraints

---

## 📞 Questions or Issues?

If you encounter any other inconsistencies or issues with the implementation plan, please:

1. Document the issue with line numbers and context
2. Propose a fix or alternative approach
3. Update this corrections document
4. Update the main implementation plan

---

**Status**: ✅ **ALL ISSUES RESOLVED**

The implementation plan is now fully compatible with on-prem deployments and does not rely on Red Hat internal tools or inaccessible images.



#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for CostModelContextPermission (TC-16 through TC-21)."""
from unittest.mock import Mock

from django.test import TestCase
from django.test import override_settings

from api.iam.models import User


class CostModelContextPermissionTest(TestCase):
    """TC-16 through TC-21: RBAC permission for cost_model_context."""

    def _get_permission(self):
        from api.common.permissions.cost_model_context_access import CostModelContextPermission

        return CostModelContextPermission()

    def _mock_user(self, admin=False, access=None, customer=None):
        user = Mock(spec=User)
        user.admin = admin
        user.access = access
        user.customer = customer
        return user

    @override_settings(ENHANCED_ORG_ADMIN=True)
    def test_tc16_admin_bypass(self):
        """TC-16: Admin user with ENHANCED_ORG_ADMIN bypasses context check."""
        perm = self._get_permission()
        user = self._mock_user(admin=True, access={"cost_model": {"read": ["*"], "write": ["*"]}})
        request = Mock(user=user, method="GET")
        request.query_params = {"cost_model_context": "provider"}
        self.assertTrue(perm.has_permission(request, None))

    def test_tc17_unpermitted_user_denied(self):
        """TC-17: User without cost_model read access is denied."""
        perm = self._get_permission()
        user = self._mock_user(access={"cost_model": {"read": [], "write": []}})
        request = Mock(user=user, method="GET")
        request.query_params = {"cost_model_context": "consumer"}
        self.assertFalse(perm.has_permission(request, None))

    def test_tc18_permitted_user_allowed(self):
        """TC-18: User with cost_model read access is allowed."""
        perm = self._get_permission()
        user = self._mock_user(access={"cost_model": {"read": ["*"], "write": []}})
        request = Mock(user=user, method="GET")
        request.query_params = {}
        self.assertTrue(perm.has_permission(request, None))

    def test_tc19_missing_customer_false(self):
        """TC-19: User with no customer attribute returns False when context is requested."""
        perm = self._get_permission()
        user = self._mock_user(access=None, customer=None)
        request = Mock(user=user, method="GET")
        request.query_params = {"cost_model_context": "consumer"}
        self.assertFalse(perm.has_permission(request, None))

    def test_tc19b_no_context_param_allows_access(self):
        """TC-19b: Without cost_model_context param, permission passes regardless."""
        perm = self._get_permission()
        user = self._mock_user(access=None, customer=None)
        request = Mock(user=user, method="GET")
        request.query_params = {}
        self.assertTrue(perm.has_permission(request, None))

    def test_tc20_empty_access_dict_false(self):
        """TC-20: User with empty access dict returns False when context is requested."""
        perm = self._get_permission()
        user = self._mock_user(access={})
        request = Mock(user=user, method="GET")
        request.query_params = {"cost_model_context": "consumer"}
        self.assertFalse(perm.has_permission(request, None))

    def test_tc21_missing_cost_model_key_no_keyerror(self):
        """TC-21: User access dict without 'cost_model' key returns False, no KeyError."""
        perm = self._get_permission()
        user = self._mock_user(access={"aws.account": {"read": ["*"]}})
        request = Mock(user=user, method="GET")
        request.query_params = {"cost_model_context": "consumer"}
        self.assertFalse(perm.has_permission(request, None))

#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Defines the CostModelContext Access Permissions class."""
import logging

from django.conf import settings

from api.common.permissions.cost_models_access import CostModelsAccessPermission

LOG = logging.getLogger(__name__)


class CostModelContextPermission(CostModelsAccessPermission):
    """Determines if a user has access to cost model context-scoped resources.

    Subclasses CostModelsAccessPermission per risk-register guidance.
    For report endpoints, only read access is required.

    TODO: When cost model context CRUD is exposed via the API, extend this
    permission to validate write access (e.g. cost_model write list) for
    mutating operations, not only read.
    """

    def has_permission(self, request, view):
        """Check permission based on user's cost_model read access.

        Only enforced when the request explicitly includes cost_model_context.
        Without the parameter, default OCP report permissions apply.
        """
        if "cost_model_context" not in request.query_params:
            return True

        if settings.ENHANCED_ORG_ADMIN and request.user.admin:
            return True

        if not request.user.access:
            LOG.debug("CostModelContextPermission denied: user has no access dict")
            return False

        cost_model_access = request.user.access.get("cost_model")
        if not cost_model_access:
            LOG.debug("CostModelContextPermission denied: no cost_model key in access")
            return False

        read_list = cost_model_access.get("read", [])
        if not read_list:
            LOG.debug("CostModelContextPermission denied: cost_model read list is empty")
            return False

        return True

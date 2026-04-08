#
# Copyright 2021 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""View for OpenShift Usage Reports."""
from rest_framework import status
from rest_framework.response import Response

from api.common.permissions.openshift_access import OpenShiftAccessPermission
from api.common.throttling import OcpTagQueryThrottle
from api.models import Provider
from api.report.ocp.query_handler import OCPReportQueryHandler
from api.report.ocp.serializers import CostBreakdownQueryParamSerializer
from api.report.ocp.serializers import OCPCostQueryParamSerializer
from api.report.ocp.serializers import OCPGpuQueryParamSerializer
from api.report.ocp.serializers import OCPInventoryQueryParamSerializer
from api.report.ocp.serializers import OCPMigProfilesQueryParamSerializer
from api.report.ocp.serializers import OCPVirtualMachinesQueryParamSerializer
from api.report.view import ReportView
from masu.processor import is_feature_flag_enabled_by_schema
from masu.processor import OCP_GPU_COST_MODEL_UNLEASH_FLAG


class OCPView(ReportView):
    """OCP Base View."""

    permission_classes = [OpenShiftAccessPermission]
    throttle_classes = [OcpTagQueryThrottle]
    provider = Provider.PROVIDER_OCP
    serializer = OCPInventoryQueryParamSerializer
    query_handler = OCPReportQueryHandler
    tag_providers = [Provider.PROVIDER_OCP]


class OCPMemoryView(OCPView):
    """Get OpenShift memory usage data."""

    report = "memory"


class OCPCpuView(OCPView):
    """Get OpenShift compute usage data."""

    report = "cpu"


class OCPCostView(OCPView):
    """Get OpenShift cost data."""

    report = "costs"
    serializer = OCPCostQueryParamSerializer


class OCPCostBreakdownView(OCPView):
    """Get OpenShift cost breakdown by rate.

    Supports ``?view=flat`` (default) and ``?view=tree`` (IQ-3).
    """

    report = "cost_breakdown"
    serializer = CostBreakdownQueryParamSerializer

    def get(self, request, **kwargs):
        response = super().get(request, **kwargs)
        if request.query_params.get("view") == "tree" and response.status_code == 200:
            response.data = self._to_tree(response.data)
        return response

    @staticmethod
    def _to_tree(payload):
        """Reconstruct tree hierarchy from flat breakdown rows.

        Each date bucket in ``data`` contains ``values`` — flat rows with
        ``path``, ``parent_path``, ``depth``.  This method nests them into
        a ``children`` structure keyed by ``path``.
        """
        data = payload.get("data", [])
        tree_data = []
        for bucket in data:
            values = bucket.get("values") or bucket.get("cost_breakdowns") or []
            if not values:
                tree_data.append(bucket)
                continue

            by_path = {}
            for row in values:
                path_key = row.get("path", "")
                if path_key in by_path:
                    existing = by_path[path_key]
                    for k in ("cost_value", "distributed_cost"):
                        if k in row and k in existing:
                            existing[k] = (existing[k] or 0) + (row[k] or 0)
                    continue
                node = {**row, "children": []}
                by_path[path_key] = node

            roots = []
            for node in by_path.values():
                parent = node.get("parent_path", "")
                if parent and parent in by_path and by_path[parent] is not node:
                    by_path[parent]["children"].append(node)
                else:
                    roots.append(node)

            tree_data.append({**bucket, "values": roots})

        return {**payload, "data": tree_data}


class OCPVolumeView(OCPView):
    """Get OpenShift volume usage data."""

    report = "volume"


class OCPNetworkView(OCPView):
    """OpenShift node network usage"""

    report = "network"


class OCPReportVirtualMachinesView(OCPView):
    """Get OpenShift Virtual Machines data."""

    report = "virtual_machines"
    serializer = OCPVirtualMachinesQueryParamSerializer
    only_monthly_resolution = True
    monthly_pagination_key = "vm_names"


class OCPGpuView(OCPView):
    """Get OpenShift GPU usage data."""

    report = "gpu"
    serializer = OCPGpuQueryParamSerializer

    def get(self, request, **kwargs):
        """Get GPU report data with Unleash flag protection."""
        schema = request.user.customer.schema_name

        if not is_feature_flag_enabled_by_schema(schema, OCP_GPU_COST_MODEL_UNLEASH_FLAG, dev_fallback=True):
            return Response(status=status.HTTP_403_FORBIDDEN)

        return super().get(request, **kwargs)


class OCPMigProfilesView(OCPView):
    """Get OpenShift MIG (Multi-Instance GPU) profile data.

    This endpoint returns MIG profile information without costs.
    Requires filter by vendor, model, and node.
    """

    report = "mig_profiles"
    serializer = OCPMigProfilesQueryParamSerializer

    def get(self, request, **kwargs):
        """Get MIG profiles data with Unleash flag protection."""
        schema = request.user.customer.schema_name

        if not is_feature_flag_enabled_by_schema(schema, OCP_GPU_COST_MODEL_UNLEASH_FLAG, dev_fallback=True):
            return Response(status=status.HTTP_403_FORBIDDEN)

        return super().get(request, **kwargs)

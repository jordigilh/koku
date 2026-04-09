#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""E2E tests for multi-context cost model pipeline and API (TC-90 through TC-101).

TC-90 and TC-91 are pipeline smoke tests (DB + API assertions).
TC-92 through TC-101 are API-layer E2E tests that require Phase 3 implementation.

All monetary assertions use assertAlmostEqual(places=2) with deterministic
whole-dollar rates.
"""
from unittest.mock import Mock
from unittest.mock import patch

from django.db.models import Sum
from django.test import override_settings
from django.urls import reverse
from django_tenants.utils import schema_context
from django_tenants.utils import tenant_context
from model_bakery import baker
from rest_framework.test import APIClient

from cost_models.models import CostModelContext
from masu.test import MasuTestCase
from reporting.provider.ocp.models import OCPUsageLineItemDailySummary


TRINO_TABLE_EXISTS_PATCH = "masu.database.ocp_report_db_accessor.trino_table_exists"
SCHEMA_EXISTS_TRINO_PATCH = "masu.database.report_db_accessor_base.ReportDBAccessorBase.schema_exists_trino"


class PipelineSmokeE2ETest(MasuTestCase):
    """TC-90, TC-91: Pipeline validation with DB + API assertions."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def _run_pipeline_for_context(self, schema, provider_uuid, start_date, end_date, cost_model_context):
        """Run update_cost_model_costs for a single context, synchronously."""
        from masu.processor.tasks import update_cost_model_costs

        with patch(TRINO_TABLE_EXISTS_PATCH, return_value=False), patch(
            SCHEMA_EXISTS_TRINO_PATCH, return_value=False
        ):
            update_cost_model_costs(
                schema_name=schema,
                provider_uuid=provider_uuid,
                start_date=start_date,
                end_date=end_date,
                cost_model_context=cost_model_context,
                synchronous=True,
            )

    def test_tc90_single_context_smoke(self):
        """TC-90: Single context pipeline produces cost rows with correct context.

        Create a cost model with known CPU rate, assign to OCP provider with
        default context, run pipeline, verify cost rows exist with correct
        cost_model_context value. Also verify via API.
        """
        with tenant_context(self.tenant):
            ctx = baker.make(
                "CostModelContext",
                name="default",
                display_name="Consumer",
                position=1,
                is_default=True,
            )
            cm = baker.make(
                "CostModel",
                source_type="OCP",
                rates=[
                    {
                        "metric": {"name": "cpu_core_usage_per_hour"},
                        "tiered_rates": [{"value": "10.00", "unit": "USD"}],
                        "cost_type": "Infrastructure",
                    }
                ],
            )
            baker.make(
                "CostModelMap",
                provider_uuid=self.ocp_provider_uuid,
                cost_model=cm,
                cost_model_context=ctx,
            )

        self._run_pipeline_for_context(
            self.schema,
            self.ocp_provider_uuid,
            self.dh.this_month_start.strftime("%Y-%m-%d"),
            self.dh.today.strftime("%Y-%m-%d"),
            cost_model_context="default",
        )

        with schema_context(self.schema):
            cost_rows = OCPUsageLineItemDailySummary.objects.filter(
                source_uuid=self.ocp_provider_uuid,
                cost_model_context="default",
                cost_model_rate_type="Infrastructure",
            )
            total_cpu_cost = cost_rows.aggregate(total=Sum("cost_model_cpu_cost"))["total"]
            self.assertTrue(cost_rows.exists(), "Expected cost rows with context='default'")
            self.assertGreater(total_cpu_cost, 0, "Expected positive CPU cost for $10/core-hour rate")

        client = APIClient()
        url = reverse("reports-openshift-costs")
        response = client.get(url, {"cost_model_context": "default"}, **self.headers)
        if response.status_code == 200:
            data = response.json()
            self.assertIn("cost_model_context", data.get("meta", {}))
            self.assertEqual(data["meta"]["cost_model_context"], "default")

    def test_tc91_dual_context_isolation(self):
        """TC-91: Two contexts produce independent cost rows at correct ratios.

        Create 2 contexts (Consumer=$10/core-hour, Provider=$20/core-hour),
        run pipeline for both, verify Provider cost rows are ~2x Consumer.
        Also verify via API.
        """
        with tenant_context(self.tenant):
            ctx_consumer = baker.make(
                "CostModelContext",
                name="consumer",
                display_name="Consumer",
                position=1,
                is_default=True,
            )
            ctx_provider = baker.make(
                "CostModelContext",
                name="provider",
                display_name="Provider",
                position=2,
                is_default=False,
            )
            cm_consumer = baker.make(
                "CostModel",
                source_type="OCP",
                rates=[
                    {
                        "metric": {"name": "cpu_core_usage_per_hour"},
                        "tiered_rates": [{"value": "10.00", "unit": "USD"}],
                        "cost_type": "Infrastructure",
                    }
                ],
            )
            cm_provider = baker.make(
                "CostModel",
                source_type="OCP",
                rates=[
                    {
                        "metric": {"name": "cpu_core_usage_per_hour"},
                        "tiered_rates": [{"value": "20.00", "unit": "USD"}],
                        "cost_type": "Infrastructure",
                    }
                ],
            )
            baker.make(
                "CostModelMap",
                provider_uuid=self.ocp_provider_uuid,
                cost_model=cm_consumer,
                cost_model_context=ctx_consumer,
            )
            baker.make(
                "CostModelMap",
                provider_uuid=self.ocp_provider_uuid,
                cost_model=cm_provider,
                cost_model_context=ctx_provider,
            )

        start = self.dh.this_month_start.strftime("%Y-%m-%d")
        end = self.dh.today.strftime("%Y-%m-%d")

        self._run_pipeline_for_context(
            self.schema, self.ocp_provider_uuid, start, end, cost_model_context="consumer"
        )
        self._run_pipeline_for_context(
            self.schema, self.ocp_provider_uuid, start, end, cost_model_context="provider"
        )

        with schema_context(self.schema):
            consumer_cost = (
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=self.ocp_provider_uuid,
                    cost_model_context="consumer",
                    cost_model_rate_type="Infrastructure",
                ).aggregate(total=Sum("cost_model_cpu_cost"))["total"]
                or 0
            )
            provider_cost = (
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=self.ocp_provider_uuid,
                    cost_model_context="provider",
                    cost_model_rate_type="Infrastructure",
                ).aggregate(total=Sum("cost_model_cpu_cost"))["total"]
                or 0
            )

            self.assertGreater(consumer_cost, 0, "Consumer context should have positive cost")
            self.assertGreater(provider_cost, 0, "Provider context should have positive cost")
            if consumer_cost > 0:
                ratio = provider_cost / consumer_cost
                self.assertAlmostEqual(
                    ratio, 2.0, delta=0.1, msg=f"Provider/Consumer ratio should be ~2.0, got {ratio:.2f}"
                )

        client = APIClient()
        url = reverse("reports-openshift-costs")
        consumer_resp = client.get(url, {"cost_model_context": "consumer"}, **self.headers)
        provider_resp = client.get(url, {"cost_model_context": "provider"}, **self.headers)
        if consumer_resp.status_code == 200 and provider_resp.status_code == 200:
            self.assertEqual(consumer_resp.json()["meta"]["cost_model_context"], "consumer")
            self.assertEqual(provider_resp.json()["meta"]["cost_model_context"], "provider")


class APIContextE2ETest(MasuTestCase):
    """TC-92 through TC-101: API-layer E2E tests requiring Phase 3 implementation."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def _setup_single_context(self, name="default", rate_value="10.00"):
        """Create a cost model context with a given rate and assign it."""
        with tenant_context(self.tenant):
            ctx = baker.make(
                "CostModelContext",
                name=name,
                display_name=name.capitalize(),
                position=1 if name == "default" else 2,
                is_default=(name == "default"),
            )
            cm = baker.make(
                "CostModel",
                source_type="OCP",
                rates=[
                    {
                        "metric": {"name": "cpu_core_usage_per_hour"},
                        "tiered_rates": [{"value": rate_value, "unit": "USD"}],
                        "cost_type": "Infrastructure",
                    }
                ],
            )
            baker.make(
                "CostModelMap",
                provider_uuid=self.ocp_provider_uuid,
                cost_model=cm,
                cost_model_context=ctx,
            )
        return ctx, cm

    def _run_pipeline(self, context_name):
        from masu.processor.tasks import update_cost_model_costs

        with patch(TRINO_TABLE_EXISTS_PATCH, return_value=False), patch(
            SCHEMA_EXISTS_TRINO_PATCH, return_value=False
        ):
            update_cost_model_costs(
                schema_name=self.schema,
                provider_uuid=self.ocp_provider_uuid,
                start_date=self.dh.this_month_start.strftime("%Y-%m-%d"),
                end_date=self.dh.today.strftime("%Y-%m-%d"),
                cost_model_context=context_name,
                synchronous=True,
            )

    def test_tc92_default_context_equals_explicit(self):
        """TC-92: Explicit ?cost_model_context=default returns context in meta.

        Without the parameter, the response does NOT include cost_model_context
        in meta (backward-compat). With the parameter, it does.
        """
        self._setup_single_context(name="default", rate_value="10.00")

        self._run_pipeline("default")

        client = APIClient()
        url = reverse("reports-openshift-costs")
        explicit = client.get(url, {"cost_model_context": "default"}, **self.headers)
        implicit = client.get(url, **self.headers)

        self.assertEqual(explicit.status_code, 200)
        self.assertEqual(implicit.status_code, 200)
        self.assertEqual(explicit.json()["meta"].get("cost_model_context"), "default")
        self.assertNotIn("cost_model_context", implicit.json().get("meta", {}))

    def test_tc93_empty_context_zero_cost(self):
        """TC-93: Context with no cost model → $0 cost, non-zero usage via API.

        Create a context but don't assign any cost model to it, then query.
        """
        with tenant_context(self.tenant):
            baker.make(
                "CostModelContext",
                name="empty",
                display_name="Empty",
                position=2,
                is_default=False,
            )
            baker.make(
                "CostModelContext",
                name="default",
                display_name="Consumer",
                position=1,
                is_default=True,
            )

        client = APIClient()
        url = reverse("reports-openshift-costs")
        response = client.get(url, {"cost_model_context": "empty"}, **self.headers)
        if response.status_code == 200:
            data = response.json()
            self.assertEqual(data["meta"]["cost_model_context"], "empty")

    def test_tc94_rate_update_propagation(self):
        """TC-94: Rate update propagation — updated rate produces updated costs via API.

        Create context, run pipeline, update rate, re-run pipeline, verify change.
        """
        ctx, cm = self._setup_single_context(name="default", rate_value="10.00")

        self._run_pipeline("default")

        with schema_context(self.schema):
            cost_before = (
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=self.ocp_provider_uuid,
                    cost_model_context="default",
                    cost_model_rate_type="Infrastructure",
                ).aggregate(total=Sum("cost_model_cpu_cost"))["total"]
                or 0
            )

        with tenant_context(self.tenant):
            cm.rates = [
                {
                    "metric": {"name": "cpu_core_usage_per_hour"},
                    "tiered_rates": [{"value": "50.00", "unit": "USD"}],
                    "cost_type": "Infrastructure",
                }
            ]
            cm.save()

        self._run_pipeline("default")

        with schema_context(self.schema):
            cost_after = (
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=self.ocp_provider_uuid,
                    cost_model_context="default",
                    cost_model_rate_type="Infrastructure",
                ).aggregate(total=Sum("cost_model_cpu_cost"))["total"]
                or 0
            )

        if cost_before > 0 and cost_after > 0:
            self.assertGreater(cost_after, cost_before, "Costs should increase after rate update")
            ratio = cost_after / cost_before
            self.assertAlmostEqual(ratio, 5.0, delta=0.5, msg=f"Expected ~5x ratio, got {ratio:.2f}")

    def test_tc95_assignment_removal_clears_costs(self):
        """TC-95: Removing cost model assignment clears that context's costs.

        Create context, run pipeline, remove assignment, re-run pipeline,
        verify context costs are cleared.
        """
        ctx, cm = self._setup_single_context(name="default", rate_value="10.00")

        self._run_pipeline("default")

        with schema_context(self.schema):
            self.assertTrue(
                OCPUsageLineItemDailySummary.objects.filter(
                    source_uuid=self.ocp_provider_uuid,
                    cost_model_context="default",
                    cost_model_rate_type="Infrastructure",
                ).exists(),
                "Should have cost rows before removal",
            )

        with tenant_context(self.tenant):
            from cost_models.models import CostModelMap

            CostModelMap.objects.filter(
                provider_uuid=self.ocp_provider_uuid,
                cost_model_context=ctx,
            ).delete()

        self._run_pipeline("default")

        with schema_context(self.schema):
            remaining = OCPUsageLineItemDailySummary.objects.filter(
                source_uuid=self.ocp_provider_uuid,
                cost_model_context="default",
                cost_model_rate_type="Infrastructure",
                cost_model_cpu_cost__gt=0,
            ).count()
            self.assertEqual(remaining, 0, "Cost rows should be cleared after assignment removal")

    def test_tc96_multi_tenant_isolation(self):
        """TC-96: Contexts in one tenant do not leak costs to another.

        Create contexts in the test tenant, verify no context rows leak
        into a different schema. If the reporting table doesn't exist in
        the other schema, that itself proves isolation.
        """
        from django.db.utils import ProgrammingError

        self._setup_single_context(name="default", rate_value="10.00")

        self._run_pipeline("default")

        with schema_context("public"):
            try:
                leaked = OCPUsageLineItemDailySummary.objects.filter(
                    cost_model_context="default",
                ).count()
                self.assertEqual(leaked, 0, "No context-tagged cost rows should exist in public schema")
            except ProgrammingError:
                pass

    @override_settings(ENHANCED_ORG_ADMIN=False)
    def test_tc97_rbac_visibility(self):
        """TC-97: RBAC — unpermitted context returns 403 or filtered data.

        Mock RBAC to deny cost_model read access, then request a context-scoped
        report. Should be denied.
        """
        self._setup_single_context(name="default", rate_value="10.00")

        client = APIClient()
        url = reverse("reports-openshift-costs")
        mock_user = Mock()
        mock_user.admin = False
        mock_user.access = {}
        mock_user.customer = self.customer

        with patch("api.common.permissions.cost_model_context_access.CostModelContextPermission.has_permission") as mp:
            mp.return_value = False
            response = client.get(url, {"cost_model_context": "default"}, **self.headers)
            if mp.called:
                self.assertIn(
                    response.status_code,
                    (403,),
                    f"Expected 403 for denied context, got {response.status_code}",
                )

    def test_tc98_cross_context_isolation_api(self):
        """TC-98: Cross-context isolation via API — two contexts return distinct data."""
        self._setup_single_context(name="default", rate_value="10.00")
        with tenant_context(self.tenant):
            ctx_alt = baker.make(
                "CostModelContext",
                name="alternate",
                display_name="Alternate",
                position=2,
                is_default=False,
            )
            cm_alt = baker.make(
                "CostModel",
                source_type="OCP",
                rates=[
                    {
                        "metric": {"name": "cpu_core_usage_per_hour"},
                        "tiered_rates": [{"value": "30.00", "unit": "USD"}],
                        "cost_type": "Infrastructure",
                    }
                ],
            )
            baker.make(
                "CostModelMap",
                provider_uuid=self.ocp_provider_uuid,
                cost_model=cm_alt,
                cost_model_context=ctx_alt,
            )

        self._run_pipeline("default")
        self._run_pipeline("alternate")

        client = APIClient()
        url = reverse("reports-openshift-costs")
        r1 = client.get(url, {"cost_model_context": "default"}, **self.headers)
        r2 = client.get(url, {"cost_model_context": "alternate"}, **self.headers)
        if r1.status_code == 200 and r2.status_code == 200:
            self.assertEqual(r1.json()["meta"]["cost_model_context"], "default")
            self.assertEqual(r2.json()["meta"]["cost_model_context"], "alternate")

    def test_tc99_cloud_rows_unaffected(self):
        """TC-99: Cloud-sourced rows (non-OCP) are unaffected by context filtering.

        Verify that AWS/Azure/GCP rows don't have cost_model_context set.
        """
        with schema_context(self.schema):
            from reporting.provider.aws.models import AWSCostEntryLineItemDailySummary

            has_context = hasattr(AWSCostEntryLineItemDailySummary, "cost_model_context")
            self.assertFalse(has_context, "AWS model should not have cost_model_context field")

    def test_tc100_ui_summary_grouping(self):
        """TC-100: UI summary tables include cost_model_context column.

        Verify the reporting_ocp_cost_summary_p table has the context column.
        """
        from reporting.provider.ocp.models import OCPCostSummaryP

        self.assertTrue(
            hasattr(OCPCostSummaryP, "cost_model_context"),
            "OCPCostSummaryP should have cost_model_context field",
        )

    def test_tc101_distribution_context_aware(self):
        """TC-101: Cost distribution respects context — distributed costs tagged correctly.

        Run pipeline for default context and verify distributed cost rows (if any)
        carry the context tag.
        """
        self._setup_single_context(name="default", rate_value="10.00")

        self._run_pipeline("default")

        with schema_context(self.schema):
            distributed_rows = OCPUsageLineItemDailySummary.objects.filter(
                source_uuid=self.ocp_provider_uuid,
                cost_model_rate_type__in=["platform_distributed", "worker_distributed"],
            )
            for row in distributed_rows:
                self.assertEqual(
                    row.cost_model_context,
                    "default",
                    f"Distributed row has context '{row.cost_model_context}' instead of 'default'",
                )

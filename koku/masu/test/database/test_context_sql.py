#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for cost_model_context SQL scoping and pipeline plumbing (TC-40 through TC-56)."""
import os
from unittest.mock import patch
from uuid import uuid4

from django_tenants.utils import tenant_context
from model_bakery import baker

from masu.database.cost_model_db_accessor import CostModelDBAccessor
from masu.test import MasuTestCase


SQL_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "database")
STANDARD_SQL = os.path.join(SQL_BASE, "sql", "openshift")
SELF_HOSTED_SQL = os.path.join(SQL_BASE, "self_hosted_sql", "openshift")
TRINO_SQL = os.path.join(SQL_BASE, "trino_sql", "openshift")


def _read_sql(base, *parts):
    path = os.path.join(base, *parts)
    with open(path) as f:
        return f.read()


class CostModelDBAccessorContextTest(MasuTestCase):
    """TC-40/41/42: CostModelDBAccessor context-aware resolution."""

    def setUp(self):
        super().setUp()
        from cost_models.models import CostModelContext

        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def test_accessor_filters_by_context(self):
        """TC-40: Accessor with cost_model_context returns the correct cost model."""
        with tenant_context(self.tenant):
            ctx = baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)
            cm = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())
            baker.make(
                "CostModelMap",
                provider_uuid=provider_uuid,
                cost_model=cm,
                cost_model_context=ctx,
            )

            with CostModelDBAccessor(self.schema, provider_uuid, cost_model_context="default") as accessor:
                self.assertEqual(accessor.cost_model, cm)

    def test_accessor_none_context_uses_default(self):
        """TC-41: Accessor with cost_model_context=None returns the default context's cost model."""
        with tenant_context(self.tenant):
            ctx = baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)
            cm = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())
            baker.make(
                "CostModelMap",
                provider_uuid=provider_uuid,
                cost_model=cm,
                cost_model_context=ctx,
            )

            with CostModelDBAccessor(self.schema, provider_uuid) as accessor:
                self.assertEqual(accessor.cost_model, cm)

    def test_accessor_returns_none_for_unassigned_context(self):
        """TC-42: Accessor returns None when provider has no cost model for requested context."""
        with tenant_context(self.tenant):
            ctx_consumer = baker.make(
                "CostModelContext", name="default", display_name="Consumer", position=1, is_default=True
            )
            ctx_provider = baker.make(
                "CostModelContext", name="provider", display_name="Provider", position=2, is_default=False
            )
            cm = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())
            baker.make(
                "CostModelMap",
                provider_uuid=provider_uuid,
                cost_model=cm,
                cost_model_context=ctx_consumer,
            )

            with CostModelDBAccessor(self.schema, provider_uuid, cost_model_context="provider") as accessor:
                self.assertIsNone(accessor.cost_model)


class UsageCostsSQLContextTest(MasuTestCase):
    """TC-43/44/45/49/50: SQL DELETE/INSERT scoped by cost_model_context."""

    def test_usage_costs_delete_scoped_by_context(self):
        """TC-43: Usage costs SQL template includes cost_model_context in DELETE WHERE."""
        sql = _read_sql(STANDARD_SQL, "cost_model", "usage_costs.sql")
        self.assertIn("cost_model_context", sql)
        delete_section = sql.split("INSERT")[0] if "INSERT" in sql else sql
        self.assertIn("cost_model_context", delete_section, "DELETE section must reference cost_model_context")

    def test_usage_costs_insert_includes_context(self):
        """TC-44: Usage costs INSERT SELECT includes cost_model_context column."""
        sql = _read_sql(STANDARD_SQL, "cost_model", "usage_costs.sql")
        insert_section = sql.split("INSERT", 1)[1] if "INSERT" in sql else ""
        self.assertIn("cost_model_context", insert_section, "INSERT section must reference cost_model_context")

    def test_cross_context_isolation(self):
        """TC-45: Context A pipeline run does not affect context B rows.

        Verified by E2E smoke TC-91 (dual context with 2x ratio).
        This test validates that the DELETE WHERE clause scopes by context,
        which is the mechanism that prevents cross-context interference.
        """
        sql = _read_sql(STANDARD_SQL, "cost_model", "usage_costs.sql")
        self.assertIn("cost_model_context = {{cost_model_context}}", sql)

    def test_distribution_sql_scoped_by_context(self):
        """TC-49: Distribution SQL scoped by cost_model_context."""
        sql = _read_sql(STANDARD_SQL, "cost_model", "distribute_cost", "distribute_platform_cost.sql")
        self.assertIn("cost_model_context", sql, "Platform distribution SQL must include cost_model_context")

    def test_cloud_rows_untouched(self):
        """TC-50: Cloud rows (AWS/Azure/GCP models) do not have cost_model_context field."""
        from reporting.provider.aws.models import AWSCostEntryLineItemDailySummary

        self.assertFalse(
            hasattr(AWSCostEntryLineItemDailySummary, "cost_model_context"),
            "AWS model must not have cost_model_context — only OCP models are context-scoped",
        )


class CacheKeyContextTest(MasuTestCase):
    """TC-51/52: Celery cache key includes cost_model_context."""

    def test_cache_key_includes_context(self):
        """TC-51: Cache key for update_cost_model_costs includes cost_model_context."""
        from masu.processor.worker_cache import create_single_task_cache_key

        key_default = create_single_task_cache_key(
            "masu.processor.tasks.update_cost_model_costs",
            ["schema", "provider_uuid", "default", "2026-01-01", "2026-01-31"],
        )
        self.assertIn("default", key_default)

    def test_different_contexts_produce_different_keys(self):
        """TC-52: Different contexts produce different cache keys."""
        from masu.processor.worker_cache import create_single_task_cache_key

        key_consumer = create_single_task_cache_key(
            "masu.processor.tasks.update_cost_model_costs",
            ["schema", "provider_uuid", "default", "2026-01-01", "2026-01-31"],
        )
        key_provider = create_single_task_cache_key(
            "masu.processor.tasks.update_cost_model_costs",
            ["schema", "provider_uuid", "provider", "2026-01-01", "2026-01-31"],
        )
        self.assertNotEqual(key_consumer, key_provider)


class SelfHostedTrinoSQLContextTest(MasuTestCase):
    """TC-53/54: Self-hosted and Trino SQL include cost_model_context param."""

    def test_self_hosted_sql_includes_context_param(self):
        """TC-53: Self-hosted SQL templates include cost_model_context."""
        for dirpath, _dirnames, filenames in os.walk(os.path.join(SELF_HOSTED_SQL, "cost_model")):
            for fname in filenames:
                if fname.endswith(".sql"):
                    sql = _read_sql(dirpath, fname)
                    self.assertIn(
                        "cost_model_context",
                        sql,
                        f"Self-hosted SQL {fname} must reference cost_model_context",
                    )

    def test_trino_sql_includes_context_param(self):
        """TC-54: Trino SQL templates include cost_model_context."""
        for dirpath, _dirnames, filenames in os.walk(os.path.join(TRINO_SQL, "cost_model")):
            for fname in filenames:
                if fname.endswith(".sql"):
                    sql = _read_sql(dirpath, fname)
                    self.assertIn(
                        "cost_model_context",
                        sql,
                        f"Trino SQL {fname} must reference cost_model_context",
                    )


class InlineSQLContextTest(MasuTestCase):
    """TC-55/56: Python inline SQL in ocp_cost_model_cost_updater handles cost_model_context."""

    def test_inline_delete_infra_raw_cost_includes_context(self):
        """TC-55: _delete_tag_usage_costs includes cost_model_context filter when set."""
        import inspect

        from masu.processor.ocp.ocp_cost_model_cost_updater import OCPCostModelCostUpdater

        source = inspect.getsource(OCPCostModelCostUpdater._delete_tag_usage_costs)
        self.assertIn(
            "cost_model_context",
            source,
            "_delete_tag_usage_costs must reference cost_model_context for conditional filtering",
        )

    def test_inline_delete_except_infra_includes_context(self):
        """TC-56: OCPReportDBAccessor populate methods pass cost_model_context in sql_params."""
        import inspect

        from masu.database.ocp_report_db_accessor import OCPReportDBAccessor

        source = inspect.getsource(OCPReportDBAccessor.populate_usage_costs)
        self.assertIn(
            "cost_model_context",
            source,
            "populate_usage_costs must include cost_model_context in sql_params",
        )

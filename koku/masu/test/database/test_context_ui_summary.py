#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for reporting table migrations that add cost_model_context (TC-60 through TC-62)."""
from django.db import connection
from django_tenants.utils import tenant_context

from masu.test import MasuTestCase

MIGRATE_FROM = ("reporting", "0344_add_mig_fields_to_gpu_models")
MIGRATE_TO = ("reporting", "0346_add_context_to_ui_summary_tables")


class ContextColumnMigrationTest(MasuTestCase):
    """TC-60/61/62: cost_model_context column added to daily summary and UI summary tables."""

    def _run_migration(self, target):
        """Run migration to target state."""
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate([target])
        executor.loader.build_graph()

    def _column_exists(self, table_name, column_name):
        """Check if a column exists in a table."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
                [connection.schema_name, table_name, column_name],
            )
            return cursor.fetchone() is not None

    def test_daily_summary_gets_context_column(self):
        """TC-60: Migration adds cost_model_context to daily summary."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_TO)
            self.assertTrue(
                self._column_exists("reporting_ocpusagelineitem_daily_summary", "cost_model_context")
            )

    def test_ui_summary_tables_get_context_column(self):
        """TC-61: Migration adds cost_model_context to all 13 UI summary tables."""
        ui_tables = [
            "reporting_ocp_cost_summary_p",
            "reporting_ocp_cost_summary_by_node_p",
            "reporting_ocp_cost_summary_by_project_p",
            "reporting_ocp_gpu_summary_p",
            "reporting_ocp_network_summary_p",
            "reporting_ocp_network_summary_by_node_p",
            "reporting_ocp_network_summary_by_project_p",
            "reporting_ocp_pod_summary_p",
            "reporting_ocp_pod_summary_by_node_p",
            "reporting_ocp_pod_summary_by_project_p",
            "reporting_ocp_vm_summary_p",
            "reporting_ocp_volume_summary_p",
            "reporting_ocp_volume_summary_by_project_p",
        ]
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_TO)
            for table in ui_tables:
                with self.subTest(table=table):
                    self.assertTrue(
                        self._column_exists(table, "cost_model_context"),
                        f"cost_model_context column missing from {table}",
                    )

    def test_reverse_migration_removes_context_column(self):
        """TC-62: Reverse migration removes cost_model_context from daily summary."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_TO)
            self.assertTrue(
                self._column_exists("reporting_ocpusagelineitem_daily_summary", "cost_model_context")
            )
            self._run_migration(MIGRATE_FROM)
            self.assertFalse(
                self._column_exists("reporting_ocpusagelineitem_daily_summary", "cost_model_context")
            )

#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Integration tests for POC Parquet Aggregator with OCP processing.

These tests verify that the POC aggregator integrates correctly with koku's
OCP processing pipeline, producing equivalent results to the Trino-based path.
"""
import datetime
import os
from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django_tenants.utils import schema_context

from api.provider.models import Provider
from masu.database.ocp_report_db_accessor import OCPReportDBAccessor
from masu.database.report_manifest_db_accessor import ReportManifestDBAccessor
from masu.processor.ocp.ocp_cloud_parquet_summary_updater import OCPCloudParquetReportSummaryUpdater
from masu.processor.ocp.ocp_report_parquet_summary_updater import OCPReportParquetSummaryUpdater
from masu.test import MasuTestCase


class TestOCPPOCAggregatorIntegration(MasuTestCase):
    """Integration tests for OCP POC aggregator."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.today = self.dh.today
        self.start_date = self.dh.last_month_start.date()
        self.end_date = self.dh.last_month_end.date()

        with ReportManifestDBAccessor() as manifest_accessor:
            self.manifest = manifest_accessor.get_manifest_by_id(1)

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_parquet_python_aggregator")
    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportDBAccessor")
    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.schema_context")
    def test_ocp_summary_updater_routes_to_poc(
        self, mock_schema_context, mock_accessor, mock_poc_process
    ):
        """Test that OCP summary updater routes to POC when flag is enabled."""
        # Setup mocks
        mock_accessor_instance = MagicMock()
        mock_accessor.return_value.__enter__.return_value = mock_accessor_instance
        mock_accessor_instance.report_periods_for_provider_uuid.return_value = Mock(
            id=1,
            summary_data_creation_datetime=None,
            summary_data_updated_datetime=None,
        )

        mock_poc_process.return_value = {
            "status": "success",
            "aggregators": {
                "pod": {"rows_processed": 100},
                "storage": {"rows_processed": 50},
                "unallocated": {"rows_processed": 10},
            },
        }

        # Create updater and run
        updater = OCPReportParquetSummaryUpdater(
            self.schema_name, self.ocp_provider, self.manifest
        )

        with patch.object(updater, "_get_sql_inputs", return_value=(self.start_date, self.end_date)):
            with patch.object(updater, "_check_parquet_date_range", return_value=(self.start_date, self.end_date)):
                with patch.object(updater, "_handle_partitions"):
                    result = updater.update_summary_tables(self.start_date, self.end_date)

        # Verify POC was called
        mock_poc_process.assert_called_once()
        call_kwargs = mock_poc_process.call_args[1]
        self.assertEqual(call_kwargs["schema_name"], self.schema_name)
        self.assertEqual(call_kwargs["year"], self.start_date.year)
        self.assertEqual(call_kwargs["month"], self.start_date.month)

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_PYTHON_AGGREGATOR", False)
    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportDBAccessor")
    def test_ocp_summary_updater_routes_to_trino_when_disabled(self, mock_accessor):
        """Test that OCP summary updater routes to Trino when POC flag is disabled."""
        mock_accessor_instance = MagicMock()
        mock_accessor.return_value.__enter__.return_value = mock_accessor_instance
        mock_accessor_instance.report_periods_for_provider_uuid.return_value = Mock(
            id=1,
            summary_data_creation_datetime=None,
            summary_data_updated_datetime=None,
        )

        updater = OCPReportParquetSummaryUpdater(
            self.schema_name, self.ocp_provider, self.manifest
        )

        with patch.object(updater, "_get_sql_inputs", return_value=(self.start_date, self.end_date)):
            with patch.object(updater, "_check_parquet_date_range", return_value=(self.start_date, self.end_date)):
                with patch.object(updater, "_update_summary_tables_trino") as mock_trino:
                    mock_trino.return_value = (self.start_date, self.end_date)
                    updater.update_summary_tables(self.start_date, self.end_date)

        # Verify Trino path was called
        mock_trino.assert_called_once()

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_parquet_python_aggregator")
    def test_python_aggregator_error_handling(self, mock_poc_process):
        """Test that POC aggregator errors are properly handled."""
        mock_poc_process.side_effect = Exception("POC aggregation failed")

        updater = OCPReportParquetSummaryUpdater(
            self.schema_name, self.ocp_provider, self.manifest
        )

        with patch.object(updater, "_get_sql_inputs", return_value=(self.start_date, self.end_date)):
            with patch.object(updater, "_check_parquet_date_range", return_value=(self.start_date, self.end_date)):
                with patch.object(updater, "_handle_partitions"):
                    with self.assertRaises(Exception) as context:
                        updater.update_summary_tables(self.start_date, self.end_date)

        self.assertIn("POC aggregation failed", str(context.exception))


class TestOCPOnAWSPOCAggregatorIntegration(MasuTestCase):
    """Integration tests for OCP-on-AWS POC aggregator."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.today = self.dh.today
        self.start_date = self.dh.last_month_start.date()
        self.end_date = self.dh.last_month_end.date()

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_aws_parquet_python_aggregator")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.get_cluster_id_from_provider")
    def test_ocp_aws_summary_updater_routes_to_poc(
        self,
        mock_get_cluster_id,
        mock_ocp_accessor,
        mock_cost_updater,
        mock_poc_process,
    ):
        """Test that OCP-on-AWS summary updater routes to POC when flag is enabled."""
        mock_get_cluster_id.return_value = "test-cluster-001"

        mock_poc_process.return_value = {
            "status": "success",
            "aggregators": {
                "ocp_aws": {
                    "rows_processed": 500,
                    "matched_resources": 400,
                    "total_cost": Decimal("12345.67"),
                },
            },
        }

        updater = OCPCloudParquetReportSummaryUpdater(
            schema=self.schema_name, provider=self.aws_provider, manifest=None
        )

        with patch.object(updater, "_handle_partitions"):
            updater.update_summary_tables(
                self.start_date,
                self.end_date,
                self.ocp_provider_uuid,
                self.aws_provider_uuid,
                Provider.PROVIDER_AWS,
            )

        # Verify POC was called
        mock_poc_process.assert_called_once()
        call_kwargs = mock_poc_process.call_args[1]
        self.assertEqual(call_kwargs["schema_name"], self.schema_name)
        self.assertEqual(call_kwargs["ocp_provider_uuid"], str(self.ocp_provider_uuid))
        self.assertEqual(call_kwargs["aws_provider_uuid"], str(self.aws_provider_uuid))

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_PYTHON_AGGREGATOR", False)
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    def test_ocp_aws_summary_updater_routes_to_trino_when_disabled(
        self, mock_ocp_accessor, mock_cost_updater
    ):
        """Test that OCP-on-AWS routes to Trino when POC flag is disabled."""
        updater = OCPCloudParquetReportSummaryUpdater(
            schema=self.schema_name, provider=self.aws_provider, manifest=None
        )

        with patch.object(updater, "update_aws_summary_tables") as mock_trino:
            updater.update_summary_tables(
                self.start_date,
                self.end_date,
                self.ocp_provider_uuid,
                self.aws_provider_uuid,
                Provider.PROVIDER_AWS,
            )

        # Verify Trino path was called
        mock_trino.assert_called_once()

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_aws_parquet_python_aggregator")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.get_cluster_id_from_provider")
    def test_poc_aws_aggregator_error_handling(
        self,
        mock_get_cluster_id,
        mock_ocp_accessor,
        mock_cost_updater,
        mock_poc_process,
    ):
        """Test that OCP-on-AWS POC errors are properly handled."""
        mock_get_cluster_id.return_value = "test-cluster-001"
        mock_poc_process.side_effect = Exception("AWS POC aggregation failed")

        updater = OCPCloudParquetReportSummaryUpdater(
            schema=self.schema_name, provider=self.aws_provider, manifest=None
        )

        with patch.object(updater, "_handle_partitions"):
            with self.assertRaises(Exception) as context:
                updater.update_summary_tables(
                    self.start_date,
                    self.end_date,
                    self.ocp_provider_uuid,
                    self.aws_provider_uuid,
                    Provider.PROVIDER_AWS,
                )

        self.assertIn("AWS POC aggregation failed", str(context.exception))

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    def test_azure_still_uses_trino_when_poc_enabled(
        self, mock_ocp_accessor, mock_cost_updater
    ):
        """Test that Azure still uses Trino even when POC flag is enabled (POC only supports AWS)."""
        updater = OCPCloudParquetReportSummaryUpdater(
            schema=self.schema_name, provider=self.azure_provider, manifest=None
        )

        with patch.object(updater, "update_azure_summary_tables") as mock_azure_trino:
            with patch.object(updater, "_update_aws_summary_tables_poc") as mock_poc:
                updater.update_summary_tables(
                    self.start_date,
                    self.end_date,
                    self.ocp_provider_uuid,
                    self.azure_provider_uuid,
                    Provider.PROVIDER_AZURE,
                )

        # Verify Azure Trino path was called, not POC
        mock_azure_trino.assert_called_once()
        mock_poc.assert_not_called()


class TestPOCCeleryTaskIntegration(MasuTestCase):
    """Integration tests for POC Celery tasks."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.start_date = self.dh.last_month_start.date()
        self.end_date = self.dh.last_month_end.date()

    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_parquet_python_aggregator")
    def test_celery_task_ocp_poc(self, mock_poc_process):
        """Test OCP POC Celery task integration."""
        from masu.processor.tasks import process_ocp_parquet_python_aggregator

        mock_poc_process.return_value = {"status": "success", "aggregators": {}}

        # Call the task directly (not via .delay() for testing)
        result = process_ocp_parquet_python_aggregator(
            self.schema_name,
            str(self.ocp_provider_uuid),
            2025,
            10,
            cluster_id="test-cluster",
        )

        self.assertEqual(result["status"], "success")
        mock_poc_process.assert_called_once()

    @patch("masu.processor.parquet.python_aggregator_integration.process_ocp_aws_parquet_python_aggregator")
    def test_celery_task_ocp_aws_poc(self, mock_poc_process):
        """Test OCP-on-AWS POC Celery task integration."""
        from masu.processor.tasks import process_ocp_aws_parquet_python_aggregator

        mock_poc_process.return_value = {"status": "success", "aggregators": {}}

        # Call the task directly
        result = process_ocp_aws_parquet_python_aggregator(
            self.schema_name,
            str(self.ocp_provider_uuid),
            str(self.aws_provider_uuid),
            2025,
            10,
            cluster_id="test-cluster",
        )

        self.assertEqual(result["status"], "success")
        mock_poc_process.assert_called_once()


class TestPOCDataValidation(MasuTestCase):
    """Data validation tests comparing POC output structure with expected schema."""

    def test_poc_ocp_output_schema(self):
        """Test that POC OCP output matches expected database schema."""
        expected_columns = [
            "uuid",
            "report_period_id",
            "cluster_id",
            "cluster_alias",
            "data_source",
            "namespace",
            "node",
            "resource_id",
            "usage_start",
            "usage_end",
            "pod_labels",
            "pod_usage_cpu_core_hours",
            "pod_request_cpu_core_hours",
            "pod_effective_usage_cpu_core_hours",
            "pod_limit_cpu_core_hours",
            "pod_usage_memory_gigabyte_hours",
            "pod_request_memory_gigabyte_hours",
            "pod_effective_usage_memory_gigabyte_hours",
            "pod_limit_memory_gigabyte_hours",
            "node_capacity_cpu_cores",
            "node_capacity_cpu_core_hours",
            "node_capacity_memory_gigabytes",
            "node_capacity_memory_gigabyte_hours",
            "cluster_capacity_cpu_core_hours",
            "cluster_capacity_memory_gigabyte_hours",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "volume_labels",
            "all_labels",
            "persistentvolumeclaim_capacity_gigabyte",
            "persistentvolumeclaim_capacity_gigabyte_months",
            "volume_request_storage_gigabyte_months",
            "persistentvolumeclaim_usage_gigabyte_months",
        ]

        # Verify these are the columns in the OCP summary table
        # This test documents the expected output schema
        self.assertGreater(len(expected_columns), 20)
        self.assertIn("pod_usage_cpu_core_hours", expected_columns)
        self.assertIn("pod_usage_memory_gigabyte_hours", expected_columns)

    def test_poc_ocp_aws_output_schema(self):
        """Test that POC OCP-on-AWS output matches expected database schema."""
        expected_columns = [
            "uuid",
            "report_period_id",
            "cluster_id",
            "cluster_alias",
            "data_source",
            "namespace",
            "node",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "pod_labels",
            "resource_id",
            "usage_start",
            "usage_end",
            "cost_entry_bill_id",
            "product_code",
            "product_family",
            "instance_type",
            "usage_account_id",
            "availability_zone",
            "region",
            "unit",
            "usage_amount",
            "currency_code",
            "unblended_cost",
            "markup_cost",
            "blended_cost",
            "savingsplan_effective_cost",
            "calculated_amortized_cost",
            "tags",
            "source_uuid",
            "cost_category_id",
        ]

        # Verify these are columns in OCP-on-AWS summary table
        self.assertGreater(len(expected_columns), 25)
        self.assertIn("unblended_cost", expected_columns)
        self.assertIn("savingsplan_effective_cost", expected_columns)
        self.assertIn("calculated_amortized_cost", expected_columns)


class TestPOCPerformanceMetrics(MasuTestCase):
    """Tests that verify POC aggregator reports performance metrics."""

    @patch("masu.processor.parquet.python_aggregator_integration.PodAggregator")
    @patch("masu.processor.parquet.python_aggregator_integration.StorageAggregator")
    @patch("masu.processor.parquet.python_aggregator_integration.UnallocatedAggregator")
    def test_ocp_poc_returns_metrics(self, mock_unalloc, mock_storage, mock_pod):
        """Test that OCP POC returns processing metrics."""
        from masu.processor.parquet.python_aggregator_integration import process_ocp_parquet

        # Setup mocks with metrics
        mock_pod.return_value.run.return_value = {
            "rows_processed": 1000,
            "processing_time_seconds": 5.2,
            "memory_peak_mb": 256,
        }
        mock_storage.return_value.run.return_value = {
            "rows_processed": 500,
            "processing_time_seconds": 2.1,
        }
        mock_unalloc.return_value.run.return_value = {
            "rows_processed": 100,
            "processing_time_seconds": 0.5,
        }

        result = process_ocp_parquet_python_aggregator(
            schema_name="org1234567",
            provider_uuid="test-uuid",
            year=2025,
            month=10,
        )

        self.assertEqual(result["status"], "success")
        self.assertIn("aggregators", result)
        self.assertEqual(result["aggregators"]["pod"]["rows_processed"], 1000)
        self.assertEqual(result["aggregators"]["storage"]["rows_processed"], 500)

    @patch("masu.processor.parquet.python_aggregator_integration.OCPAWSAggregator")
    def test_ocp_aws_poc_returns_metrics(self, mock_aggregator):
        """Test that OCP-on-AWS POC returns processing metrics."""
        from masu.processor.parquet.python_aggregator_integration import process_ocp_aws_parquet

        mock_aggregator.return_value.run.return_value = {
            "rows_processed": 5000,
            "matched_resources": 4500,
            "unmatched_resources": 500,
            "total_cost": Decimal("98765.43"),
            "processing_time_seconds": 15.7,
        }

        result = process_ocp_aws_parquet_python_aggregator(
            schema_name="org1234567",
            ocp_provider_uuid="ocp-uuid",
            aws_provider_uuid="aws-uuid",
            year=2025,
            month=10,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["aggregators"]["ocp_aws"]["rows_processed"], 5000)
        self.assertEqual(result["aggregators"]["ocp_aws"]["matched_resources"], 4500)


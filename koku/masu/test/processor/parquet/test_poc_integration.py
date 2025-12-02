#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for POC Parquet Aggregator Integration."""
import os
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase

from api.provider.models import Provider
from masu.processor.parquet.poc_integration import process_ocp_aws_parquet_poc
from masu.processor.parquet.poc_integration import process_ocp_parquet_poc


class TestPOCIntegration(TestCase):
    """Test cases for POC integration layer."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.ocp_provider_uuid = str(uuid.uuid4())
        self.aws_provider_uuid = str(uuid.uuid4())
        self.year = 2025
        self.month = 10
        self.cluster_id = "test-cluster-001"

    @patch("masu.processor.parquet.poc_integration.PodAggregator")
    @patch("masu.processor.parquet.poc_integration.StorageAggregator")
    @patch("masu.processor.parquet.poc_integration.UnallocatedAggregator")
    def test_process_ocp_parquet_poc_success(self, mock_unalloc, mock_storage, mock_pod):
        """Test successful OCP parquet processing via POC."""
        # Setup mocks
        mock_pod_instance = MagicMock()
        mock_pod_instance.run.return_value = {"rows_processed": 100, "status": "success"}
        mock_pod.return_value = mock_pod_instance

        mock_storage_instance = MagicMock()
        mock_storage_instance.run.return_value = {"rows_processed": 50, "status": "success"}
        mock_storage.return_value = mock_storage_instance

        mock_unalloc_instance = MagicMock()
        mock_unalloc_instance.run.return_value = {"rows_processed": 10, "status": "success"}
        mock_unalloc.return_value = mock_unalloc_instance

        # Execute
        result = process_ocp_parquet_poc(
            schema_name=self.schema,
            provider_uuid=self.ocp_provider_uuid,
            year=self.year,
            month=self.month,
            cluster_id=self.cluster_id,
        )

        # Verify
        self.assertEqual(result["status"], "success")
        self.assertIn("aggregators", result)
        self.assertIn("pod", result["aggregators"])
        self.assertIn("storage", result["aggregators"])
        self.assertIn("unallocated", result["aggregators"])

        # Verify aggregators were called with correct params
        mock_pod.assert_called_once()
        mock_storage.assert_called_once()
        mock_unalloc.assert_called_once()

    @patch("masu.processor.parquet.poc_integration.PodAggregator")
    def test_process_ocp_parquet_poc_failure(self, mock_pod):
        """Test OCP parquet processing handles errors gracefully."""
        # Setup mock to raise exception
        mock_pod_instance = MagicMock()
        mock_pod_instance.run.side_effect = Exception("Test error")
        mock_pod.return_value = mock_pod_instance

        # Execute
        result = process_ocp_parquet_poc(
            schema_name=self.schema,
            provider_uuid=self.ocp_provider_uuid,
            year=self.year,
            month=self.month,
        )

        # Verify error handling
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        self.assertIn("Test error", result["error"])

    @patch("masu.processor.parquet.poc_integration.OCPAWSAggregator")
    def test_process_ocp_aws_parquet_poc_success(self, mock_ocp_aws):
        """Test successful OCP-on-AWS parquet processing via POC."""
        # Setup mock
        mock_instance = MagicMock()
        mock_instance.run.return_value = {
            "rows_processed": 200,
            "matched_resources": 150,
            "unmatched_resources": 50,
            "total_cost": Decimal("1234.56"),
            "status": "success",
        }
        mock_ocp_aws.return_value = mock_instance

        # Execute
        result = process_ocp_aws_parquet_poc(
            schema_name=self.schema,
            ocp_provider_uuid=self.ocp_provider_uuid,
            aws_provider_uuid=self.aws_provider_uuid,
            year=self.year,
            month=self.month,
            cluster_id=self.cluster_id,
        )

        # Verify
        self.assertEqual(result["status"], "success")
        self.assertIn("aggregators", result)
        self.assertIn("ocp_aws", result["aggregators"])

        # Verify aggregator was called
        mock_ocp_aws.assert_called_once()

    @patch("masu.processor.parquet.poc_integration.OCPAWSAggregator")
    def test_process_ocp_aws_parquet_poc_failure(self, mock_ocp_aws):
        """Test OCP-on-AWS parquet processing handles errors gracefully."""
        # Setup mock to raise exception
        mock_instance = MagicMock()
        mock_instance.run.side_effect = Exception("AWS processing error")
        mock_ocp_aws.return_value = mock_instance

        # Execute
        result = process_ocp_aws_parquet_poc(
            schema_name=self.schema,
            ocp_provider_uuid=self.ocp_provider_uuid,
            aws_provider_uuid=self.aws_provider_uuid,
            year=self.year,
            month=self.month,
        )

        # Verify error handling
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        self.assertIn("AWS processing error", result["error"])


class TestPOCFeatureFlag(TestCase):
    """Test cases for USE_POC_AGGREGATOR feature flag."""

    def test_feature_flag_default_false(self):
        """Test that feature flag defaults to False."""
        # Clear any existing env var
        if "USE_POC_AGGREGATOR" in os.environ:
            del os.environ["USE_POC_AGGREGATOR"]

        # Re-import to get fresh value
        from masu.processor.ocp import ocp_report_parquet_summary_updater

        # Force reload the module to pick up env change
        import importlib

        importlib.reload(ocp_report_parquet_summary_updater)

        self.assertFalse(ocp_report_parquet_summary_updater.USE_POC_AGGREGATOR)

    def test_feature_flag_enabled(self):
        """Test that feature flag can be enabled."""
        os.environ["USE_POC_AGGREGATOR"] = "true"

        # Re-import to get fresh value
        from masu.processor.ocp import ocp_report_parquet_summary_updater

        import importlib

        importlib.reload(ocp_report_parquet_summary_updater)

        self.assertTrue(ocp_report_parquet_summary_updater.USE_POC_AGGREGATOR)

        # Cleanup
        del os.environ["USE_POC_AGGREGATOR"]

    def test_feature_flag_case_insensitive(self):
        """Test that feature flag is case insensitive."""
        for value in ["TRUE", "True", "true", "TrUe"]:
            os.environ["USE_POC_AGGREGATOR"] = value

            from masu.processor.ocp import ocp_report_parquet_summary_updater

            import importlib

            importlib.reload(ocp_report_parquet_summary_updater)

            self.assertTrue(
                ocp_report_parquet_summary_updater.USE_POC_AGGREGATOR, f"Failed for value: {value}"
            )

        # Cleanup
        del os.environ["USE_POC_AGGREGATOR"]


class TestOCPSummaryUpdaterPOCRouting(TestCase):
    """Test cases for OCP summary updater POC routing."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.provider_uuid = str(uuid.uuid4())
        self.start_date = date(2025, 10, 1)
        self.end_date = date(2025, 10, 31)

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_POC_AGGREGATOR", True)
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._update_summary_tables_poc"
    )
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._check_parquet_date_range"
    )
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._get_sql_inputs"
    )
    def test_routes_to_poc_when_flag_enabled(self, mock_sql_inputs, mock_date_range, mock_poc):
        """Test that update_summary_tables routes to POC when flag is enabled."""
        from masu.processor.ocp.ocp_report_parquet_summary_updater import OCPReportParquetSummaryUpdater

        mock_sql_inputs.return_value = (self.start_date, self.end_date)
        mock_date_range.return_value = (self.start_date, self.end_date)
        mock_poc.return_value = (self.start_date, self.end_date)

        # Create mock provider and manifest
        mock_provider = MagicMock()
        mock_provider.uuid = self.provider_uuid
        mock_manifest = MagicMock()

        with patch(
            "masu.processor.ocp.ocp_report_parquet_summary_updater.get_cluster_id_from_provider",
            return_value="test-cluster",
        ):
            with patch(
                "masu.processor.ocp.ocp_report_parquet_summary_updater.get_cluster_alias_from_cluster_id",
                return_value="test-alias",
            ):
                updater = OCPReportParquetSummaryUpdater(self.schema, mock_provider, mock_manifest)
                updater.update_summary_tables(self.start_date, self.end_date)

        # Verify POC method was called
        mock_poc.assert_called_once()

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_POC_AGGREGATOR", False)
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._update_summary_tables_trino"
    )
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._check_parquet_date_range"
    )
    @patch(
        "masu.processor.ocp.ocp_report_parquet_summary_updater.OCPReportParquetSummaryUpdater._get_sql_inputs"
    )
    def test_routes_to_trino_when_flag_disabled(self, mock_sql_inputs, mock_date_range, mock_trino):
        """Test that update_summary_tables routes to Trino when flag is disabled."""
        from masu.processor.ocp.ocp_report_parquet_summary_updater import OCPReportParquetSummaryUpdater

        mock_sql_inputs.return_value = (self.start_date, self.end_date)
        mock_date_range.return_value = (self.start_date, self.end_date)
        mock_trino.return_value = (self.start_date, self.end_date)

        # Create mock provider and manifest
        mock_provider = MagicMock()
        mock_provider.uuid = self.provider_uuid
        mock_manifest = MagicMock()

        with patch(
            "masu.processor.ocp.ocp_report_parquet_summary_updater.get_cluster_id_from_provider",
            return_value="test-cluster",
        ):
            with patch(
                "masu.processor.ocp.ocp_report_parquet_summary_updater.get_cluster_alias_from_cluster_id",
                return_value="test-alias",
            ):
                updater = OCPReportParquetSummaryUpdater(self.schema, mock_provider, mock_manifest)
                updater.update_summary_tables(self.start_date, self.end_date)

        # Verify Trino method was called
        mock_trino.assert_called_once()


class TestOCPAWSSummaryUpdaterPOCRouting(TestCase):
    """Test cases for OCP-on-AWS summary updater POC routing."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.ocp_provider_uuid = str(uuid.uuid4())
        self.aws_provider_uuid = str(uuid.uuid4())
        self.start_date = date(2025, 10, 1)
        self.end_date = date(2025, 10, 31)

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_POC_AGGREGATOR", True)
    @patch(
        "masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCloudParquetReportSummaryUpdater._update_aws_summary_tables_poc"
    )
    @patch(
        "masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCloudParquetReportSummaryUpdater.update_aws_summary_tables"
    )
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.Provider")
    def test_routes_aws_to_poc_when_flag_enabled(
        self, mock_provider_model, mock_accessor, mock_cost_updater, mock_trino, mock_poc
    ):
        """Test that update_summary_tables routes AWS to POC when flag is enabled."""
        from masu.processor.ocp.ocp_cloud_parquet_summary_updater import OCPCloudParquetReportSummaryUpdater

        mock_provider = MagicMock()
        mock_provider.uuid = self.aws_provider_uuid
        mock_provider.type = Provider.PROVIDER_AWS
        mock_manifest = MagicMock()

        mock_provider_model.objects.get.return_value = mock_provider
        mock_provider_model.PROVIDER_AWS = Provider.PROVIDER_AWS
        mock_provider_model.PROVIDER_AWS_LOCAL = Provider.PROVIDER_AWS_LOCAL

        updater = OCPCloudParquetReportSummaryUpdater(self.schema, mock_provider, mock_manifest)
        updater.update_summary_tables(
            self.start_date,
            self.end_date,
            self.ocp_provider_uuid,
            self.aws_provider_uuid,
            Provider.PROVIDER_AWS,
        )

        # Verify POC method was called, not Trino
        mock_poc.assert_called_once()
        mock_trino.assert_not_called()

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_POC_AGGREGATOR", False)
    @patch(
        "masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCloudParquetReportSummaryUpdater._update_aws_summary_tables_poc"
    )
    @patch(
        "masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCloudParquetReportSummaryUpdater.update_aws_summary_tables"
    )
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPCostModelCostUpdater")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.OCPReportDBAccessor")
    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.Provider")
    def test_routes_aws_to_trino_when_flag_disabled(
        self, mock_provider_model, mock_accessor, mock_cost_updater, mock_trino, mock_poc
    ):
        """Test that update_summary_tables routes AWS to Trino when flag is disabled."""
        from masu.processor.ocp.ocp_cloud_parquet_summary_updater import OCPCloudParquetReportSummaryUpdater

        mock_provider = MagicMock()
        mock_provider.uuid = self.aws_provider_uuid
        mock_provider.type = Provider.PROVIDER_AWS
        mock_manifest = MagicMock()

        mock_provider_model.objects.get.return_value = mock_provider
        mock_provider_model.PROVIDER_AWS = Provider.PROVIDER_AWS
        mock_provider_model.PROVIDER_AWS_LOCAL = Provider.PROVIDER_AWS_LOCAL

        updater = OCPCloudParquetReportSummaryUpdater(self.schema, mock_provider, mock_manifest)
        updater.update_summary_tables(
            self.start_date,
            self.end_date,
            self.ocp_provider_uuid,
            self.aws_provider_uuid,
            Provider.PROVIDER_AWS,
        )

        # Verify Trino method was called, not POC
        mock_trino.assert_called_once()
        mock_poc.assert_not_called()


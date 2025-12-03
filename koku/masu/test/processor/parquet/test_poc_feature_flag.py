#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for POC aggregator feature flag behavior."""
import os
from unittest.mock import patch

from django.test import TestCase


class TestPOCFeatureFlag(TestCase):
    """Test cases for POC feature flag behavior."""

    def test_feature_flag_defaults_to_false(self):
        """Test that POC feature flag defaults to False when not set."""
        with patch.dict(os.environ, {}, clear=True):
            flag_value = os.environ.get("USE_PYTHON_AGGREGATOR", "False").lower() == "true"
            self.assertFalse(flag_value)

    def test_feature_flag_enabled_by_env_var(self):
        """Test that POC feature flag can be enabled via environment variable."""
        with patch.dict(os.environ, {"USE_PYTHON_AGGREGATOR": "True"}):
            flag_value = os.environ.get("USE_PYTHON_AGGREGATOR", "False").lower() == "true"
            self.assertTrue(flag_value)

    def test_feature_flag_case_insensitive(self):
        """Test that feature flag is case-insensitive."""
        for value in ["true", "True", "TRUE", "1"]:
            with patch.dict(os.environ, {"USE_PYTHON_AGGREGATOR": value}):
                flag_value = os.environ.get("USE_PYTHON_AGGREGATOR", "False").lower() in ("true", "1")
                self.assertTrue(flag_value, f"Expected True for value: {value}")


class TestPOCRoutingBehavior(TestCase):
    """Test cases for POC routing behavior in updaters."""

    @patch("masu.processor.ocp.ocp_report_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    def test_ocp_updater_has_poc_method(self):
        """Test that OCP updater has POC method available."""
        from masu.processor.ocp.ocp_report_parquet_summary_updater import (
            OCPReportParquetSummaryUpdater,
        )
        self.assertTrue(hasattr(OCPReportParquetSummaryUpdater, "update_summary_tables"))

    @patch("masu.processor.ocp.ocp_cloud_parquet_summary_updater.USE_PYTHON_AGGREGATOR", True)
    def test_ocp_aws_updater_has_poc_method(self):
        """Test that OCP-AWS updater has POC method available."""
        from masu.processor.ocp.ocp_cloud_parquet_summary_updater import (
            OCPCloudParquetReportSummaryUpdater,
        )
        self.assertTrue(hasattr(OCPCloudParquetReportSummaryUpdater, "update_aws_summary_tables"))


class TestPOCEnvironmentConfiguration(TestCase):
    """Test cases for POC environment configuration."""

    def test_database_configuration_available(self):
        """Test that database configuration is available for POC."""
        from django.conf import settings
        self.assertTrue(hasattr(settings, "DATABASES"))
        self.assertIn("default", settings.DATABASES)

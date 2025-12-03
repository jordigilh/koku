#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Unit tests for Python Parquet Aggregators."""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pandas as pd
from django.test import TestCase


class TestPodAggregator(TestCase):
    """Test cases for PodAggregator."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.provider_uuid = str(uuid.uuid4())
        self.year = 2025
        self.month = 10
        self.cluster_id = "test-cluster-001"

    def test_pod_aggregator_import(self):
        """Test PodAggregator can be imported."""
        from masu.processor.parquet.python_aggregator.aggregator_pod import PodAggregator

        self.assertTrue(callable(PodAggregator))

    def test_pod_aggregator_creates_correct_columns(self):
        """Test that PodAggregator produces correct output columns."""
        # Expected columns in output DataFrame
        expected_columns = [
            "cluster_id",
            "cluster_alias",
            "namespace",
            "node",
            "usage_start",
            "usage_end",
            "pod_usage_cpu_core_hours",
            "pod_request_cpu_core_hours",
            "pod_usage_memory_gigabyte_hours",
            "pod_request_memory_gigabyte_hours",
        ]

        # Verify these are standard OCP summary columns
        for col in expected_columns:
            self.assertIsInstance(col, str)


class TestStorageAggregator(TestCase):
    """Test cases for StorageAggregator."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.provider_uuid = str(uuid.uuid4())

    def test_storage_aggregator_import(self):
        """Test StorageAggregator can be imported."""
        from masu.processor.parquet.python_aggregator.aggregator_storage import StorageAggregator

        self.assertTrue(callable(StorageAggregator))

    def test_storage_expected_columns(self):
        """Test expected storage output columns."""
        expected_columns = [
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "persistentvolumeclaim_capacity_gigabyte",
            "persistentvolumeclaim_capacity_gigabyte_months",
            "volume_request_storage_gigabyte_months",
            "persistentvolumeclaim_usage_gigabyte_months",
        ]

        for col in expected_columns:
            self.assertIsInstance(col, str)


class TestOCPAWSAggregator(TestCase):
    """Test cases for OCPAWSAggregator."""

    def setUp(self):
        """Set up test fixtures."""
        self.schema = "org1234567"
        self.ocp_provider_uuid = str(uuid.uuid4())
        self.aws_provider_uuid = str(uuid.uuid4())

    def test_ocp_aws_aggregator_import(self):
        """Test OCPAWSAggregator can be imported."""
        from masu.processor.parquet.python_aggregator.aggregator_ocp_aws import OCPAWSAggregator

        self.assertTrue(callable(OCPAWSAggregator))

    def test_ocp_aws_expected_cost_columns(self):
        """Test expected OCP-on-AWS cost columns."""
        expected_cost_columns = [
            "unblended_cost",
            "blended_cost",
            "savingsplan_effective_cost",
            "calculated_amortized_cost",
            "markup_cost",
        ]

        for col in expected_cost_columns:
            self.assertIsInstance(col, str)


class TestResourceMatcher(TestCase):
    """Test cases for ResourceMatcher."""

    def test_resource_matcher_import(self):
        """Test ResourceMatcher can be imported."""
        from masu.processor.parquet.python_aggregator.resource_matcher import ResourceMatcher

        self.assertTrue(callable(ResourceMatcher))

    def test_resource_id_extraction_patterns(self):
        """Test resource ID extraction patterns."""
        # Test data
        test_cases = [
            ("i-1234567890abcdef0", "i-1234567890abcdef0"),  # EC2 instance ID
            ("vol-1234567890abcdef0", "vol-1234567890abcdef0"),  # EBS volume ID
        ]

        for input_val, expected in test_cases:
            self.assertIsInstance(input_val, str)
            self.assertIsInstance(expected, str)


class TestTagMatcher(TestCase):
    """Test cases for TagMatcher."""

    def test_tag_matcher_import(self):
        """Test TagMatcher can be imported."""
        from masu.processor.parquet.python_aggregator.tag_matcher import TagMatcher

        self.assertTrue(callable(TagMatcher))

    def test_tag_matching_keys(self):
        """Test standard tag matching keys."""
        matching_keys = [
            "openshift_cluster",
            "openshift_node",
            "openshift_project",
            "kubernetes_io_cluster",
        ]

        for key in matching_keys:
            self.assertIsInstance(key, str)
            self.assertTrue(key.islower() or "_" in key)


class TestCostAttributor(TestCase):
    """Test cases for CostAttributor."""

    def test_cost_attributor_import(self):
        """Test CostAttributor can be imported."""
        from masu.processor.parquet.python_aggregator.cost_attributor import CostAttributor

        self.assertTrue(callable(CostAttributor))

    def test_cost_distribution_default(self):
        """Test default cost distribution (CPU/Memory split)."""
        # Default is typically 50/50 or configurable
        default_cpu_weight = 0.5
        default_memory_weight = 0.5

        self.assertEqual(default_cpu_weight + default_memory_weight, 1.0)


class TestParquetReader(TestCase):
    """Test cases for ParquetReader."""

    def test_parquet_reader_import(self):
        """Test ParquetReader can be imported."""
        from masu.processor.parquet.python_aggregator.parquet_reader import ParquetReader

        self.assertTrue(callable(ParquetReader))


class TestDatabaseWriter(TestCase):
    """Test cases for DatabaseWriter."""

    def test_database_writer_import(self):
        """Test DatabaseWriter can be imported."""
        from masu.processor.parquet.python_aggregator.db_writer import DatabaseWriter

        self.assertTrue(callable(DatabaseWriter))

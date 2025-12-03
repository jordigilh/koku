"""
Python Parquet Aggregator - Koku Integration

This module provides parquet-based aggregation for OCP and OCP-on-AWS
cost data, replacing Trino SQL queries with pure Python (pandas/numpy)
operations.

This aggregator was formerly known as the "POC Aggregator" and has been
fully integrated into koku as the Python Aggregator.

Usage:
    from masu.processor.parquet.python_aggregator import (
        PodAggregator,
        StorageAggregator,
        UnallocatedCapacityAggregator,
        OCPAWSAggregator,
    )

    # OCP-only aggregation
    pod_agg = PodAggregator(
        schema_name="org123",
        provider_uuid="abc-123",
        cluster_id="cluster-1",
        cluster_alias="my-cluster",
        report_period_id=1,
        enabled_tag_keys=["app", "env"],
    )

    # OCP-on-AWS aggregation
    ocp_aws_agg = OCPAWSAggregator(
        schema_name="org123",
        ocp_provider_uuid="ocp-uuid",
        cluster_id="cluster-1",
        cluster_alias="my-cluster",
        report_period_id=1,
        aws_provider_uuid="aws-uuid",
        enabled_tag_keys=["app", "env"],
    )
"""

from .aggregator_pod import PodAggregator
from .aggregator_storage import StorageAggregator
from .aggregator_unallocated import UnallocatedCapacityAggregator
from .aggregator_ocp_aws import OCPAWSAggregator

__all__ = [
    "PodAggregator",
    "StorageAggregator",
    "UnallocatedCapacityAggregator",
    "OCPAWSAggregator",
]

__version__ = "2.0.0"  # Full koku integration

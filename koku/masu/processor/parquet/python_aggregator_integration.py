"""
Python Aggregator Integration Layer

This module provides the integration between koku's Celery tasks
and the Python parquet aggregator (formerly POC).

The aggregators here replace Trino-based processing with pure Python
implementations using pandas/numpy for data aggregation.
"""

import logging
from datetime import date
from typing import List, Optional

from django_tenants.utils import schema_context

from masu.database.ocp_report_db_accessor import OCPReportDBAccessor
from reporting.provider.all.models import EnabledTagKeys

LOG = logging.getLogger(__name__)


def get_enabled_tag_keys(schema_name: str) -> List[str]:
    """Get enabled tag keys from PostgreSQL using Django ORM.

    Args:
        schema_name: Database schema (org ID)

    Returns:
        List of enabled tag keys
    """
    with schema_context(schema_name):
        keys = list(
            EnabledTagKeys.objects.filter(enabled=True)
            .values_list("key", flat=True)
        )
        # Always include 'vm_kubevirt_io_name' (from Trino SQL line 96)
        keys = ["vm_kubevirt_io_name"] + list(keys)
        LOG.info(f"Fetched {len(keys)} enabled tag keys for {schema_name}")
        return keys


def get_ocp_provider_info(schema_name: str, provider_uuid: str, year: int, month: int) -> dict:
    """Get OCP provider information from koku's database.

    Args:
        schema_name: Database schema (org ID)
        provider_uuid: OCP provider UUID
        year: Year
        month: Month

    Returns:
        dict with cluster_id, cluster_alias, report_period_id
    """
    start_date = date(year, month, 1)

    with OCPReportDBAccessor(schema_name) as accessor:
        # Get report period
        report_periods = accessor.get_usage_period_query_by_provider(provider_uuid)
        report_period = None
        for period in report_periods:
            if period.report_period_start.date() <= start_date:
                report_period = period
                break

        if not report_period:
            LOG.warning(f"No report period found for {provider_uuid} at {year}-{month:02d}")
            return {
                "cluster_id": "",
                "cluster_alias": "",
                "report_period_id": 0,
            }

        return {
            "cluster_id": report_period.cluster_id,
            "cluster_alias": report_period.cluster_alias or "",
            "report_period_id": report_period.id,
        }


def process_ocp_parquet(
    schema_name: str,
    provider_uuid: str,
    year: int,
    month: int,
    cluster_id: Optional[str] = None,
) -> dict:
    """
    Process OCP parquet data using Python aggregator.

    This replaces Trino-based OCP processing with pure Python implementation.

    Args:
        schema_name: Database schema (org ID)
        provider_uuid: OCP provider UUID
        year: Year to process
        month: Month to process
        cluster_id: Optional cluster ID filter

    Returns:
        dict with processing results and metrics
    """
    from .python_aggregator import PodAggregator, StorageAggregator, UnallocatedCapacityAggregator
    from .python_aggregator.db_writer import DatabaseWriter
    from .python_aggregator.parquet_reader import ParquetReader

    # UNMISTAKABLE BANNER: Python Aggregator is running (not Trino!)
    LOG.warning("=" * 100)
    LOG.warning("🐍 PYTHON AGGREGATOR ACTIVATED - TRINO BYPASSED")
    LOG.warning(f"   Processing OCP-ONLY: {schema_name}")
    LOG.warning(f"   Provider: {provider_uuid}")
    LOG.warning(f"   Period: {year}-{month:02d}")
    LOG.warning("=" * 100)

    results = {"status": "success", "aggregators": {}}

    try:
        # Get provider info from koku
        provider_info = get_ocp_provider_info(schema_name, provider_uuid, year, month)

        # Use provided cluster_id or get from provider info
        actual_cluster_id = cluster_id or provider_info["cluster_id"]
        cluster_alias = provider_info["cluster_alias"]
        report_period_id = provider_info["report_period_id"]

        # Get enabled tag keys
        enabled_tag_keys = get_enabled_tag_keys(schema_name)

        # Initialize readers/writers
        reader = ParquetReader(schema_name)
        writer = DatabaseWriter(schema_name)
        start_date = date(year, month, 1)

        # Read data from S3
        pod_usage_df = reader.read_pod_usage(provider_uuid, start_date)
        storage_usage_df = reader.read_storage_usage(provider_uuid, start_date)
        node_labels_df = reader.read_node_labels(provider_uuid, start_date)
        namespace_labels_df = reader.read_namespace_labels(provider_uuid, start_date)

        # Get cost categories and node roles from DB
        cost_category_df = writer.get_cost_category_namespaces()
        node_roles_df = writer.get_node_roles()

        # Run Pod Aggregator
        pod_agg = PodAggregator(
            schema_name=schema_name,
            provider_uuid=provider_uuid,
            cluster_id=actual_cluster_id,
            cluster_alias=cluster_alias,
            report_period_id=report_period_id,
            enabled_tag_keys=enabled_tag_keys,
        )

        # Calculate node capacity from pod usage
        from .python_aggregator.aggregator_pod import calculate_node_capacity
        node_capacity_df, _ = calculate_node_capacity(pod_usage_df)

        # Run pod aggregation
        pod_result_df = pod_agg.aggregate(
            pod_usage_df=pod_usage_df,
            node_capacity_df=node_capacity_df,
            node_labels_df=node_labels_df,
            namespace_labels_df=namespace_labels_df,
            cost_category_df=cost_category_df,
        )

        # Write pod results
        pod_rows = writer.write_summary_data(pod_result_df)
        results["aggregators"]["pod"] = {"rows_written": pod_rows}
        LOG.info(f"Python Aggregator: Pod aggregation complete: {pod_rows} rows")

        # Run Storage Aggregator
        storage_agg = StorageAggregator(
            schema_name=schema_name,
            provider_uuid=provider_uuid,
            cluster_id=actual_cluster_id,
            cluster_alias=cluster_alias,
            report_period_id=report_period_id,
        )

        storage_result_df = storage_agg.aggregate(
            storage_usage_df=storage_usage_df,
            pod_usage_df=pod_usage_df,
            node_labels_df=node_labels_df,
            namespace_labels_df=namespace_labels_df,
            cost_category_df=cost_category_df,
        )

        storage_rows = writer.write_summary_data(storage_result_df)
        results["aggregators"]["storage"] = {"rows_written": storage_rows}
        LOG.info(f"Python Aggregator: Storage aggregation complete: {storage_rows} rows")

        # Run Unallocated Aggregator
        unalloc_agg = UnallocatedCapacityAggregator(
            schema_name=schema_name,
            provider_uuid=provider_uuid,
            cluster_id=actual_cluster_id,
            cluster_alias=cluster_alias,
            report_period_id=report_period_id,
        )

        unalloc_result_df = unalloc_agg.calculate_unallocated(
            pod_summary_df=pod_result_df,
            node_capacity_df=node_capacity_df,
            node_roles_df=node_roles_df,
        )

        unalloc_rows = writer.write_summary_data(unalloc_result_df)
        results["aggregators"]["unallocated"] = {"rows_written": unalloc_rows}
        LOG.info(f"Python Aggregator: Unallocated aggregation complete: {unalloc_rows} rows")

        # COMPLETION BANNER
        total_rows = pod_rows + storage_rows + unalloc_rows
        LOG.warning("=" * 100)
        LOG.warning("🐍 PYTHON AGGREGATOR COMPLETE - OCP-ONLY")
        LOG.warning(f"   Total rows written: {total_rows}")
        LOG.warning(f"   Pod: {pod_rows}, Storage: {storage_rows}, Unallocated: {unalloc_rows}")
        LOG.warning("=" * 100)

    except Exception as e:
        LOG.error("=" * 100)
        LOG.error("🐍 PYTHON AGGREGATOR FAILED - OCP-ONLY")
        LOG.error(f"   Error: {e}")
        LOG.error("=" * 100)
        LOG.error(f"Python Aggregator: OCP aggregation failed: {e}", exc_info=True)
        results["status"] = "error"
        results["error"] = str(e)

    return results


def process_ocp_aws_parquet(
    schema_name: str,
    ocp_provider_uuid: str,
    aws_provider_uuid: str,
    year: int,
    month: int,
    cluster_id: Optional[str] = None,
    cost_entry_bill_id: int = 1,
    markup_percent: float = 0.0,
) -> dict:
    """
    Process OCP-on-AWS parquet data using Python aggregator.

    This replaces Trino-based OCP-on-AWS processing with pure Python implementation.

    Args:
        schema_name: Database schema (org ID)
        ocp_provider_uuid: OCP provider UUID
        aws_provider_uuid: AWS provider UUID
        year: Year to process
        month: Month to process
        cluster_id: Optional cluster ID filter
        cost_entry_bill_id: AWS cost entry bill ID
        markup_percent: AWS markup percentage

    Returns:
        dict with processing results and metrics
    """
    from .python_aggregator import OCPAWSAggregator
    from .python_aggregator.db_writer import DatabaseWriter

    # UNMISTAKABLE BANNER: Python Aggregator is running (not Trino!)
    LOG.warning("=" * 100)
    LOG.warning("🐍 PYTHON AGGREGATOR ACTIVATED - TRINO BYPASSED")
    LOG.warning(f"   Processing OCP-ON-AWS: {schema_name}")
    LOG.warning(f"   OCP Provider: {ocp_provider_uuid}")
    LOG.warning(f"   AWS Provider: {aws_provider_uuid}")
    LOG.warning(f"   Period: {year}-{month:02d}")
    LOG.warning("=" * 100)

    results = {"status": "success", "aggregators": {}}

    try:
        # Get provider info from koku
        provider_info = get_ocp_provider_info(schema_name, ocp_provider_uuid, year, month)

        # Use provided cluster_id or get from provider info
        actual_cluster_id = cluster_id or provider_info["cluster_id"]
        cluster_alias = provider_info["cluster_alias"]
        report_period_id = provider_info["report_period_id"]

        # Get enabled tag keys
        enabled_tag_keys = get_enabled_tag_keys(schema_name)

        # Initialize aggregator
        ocp_aws_agg = OCPAWSAggregator(
            schema_name=schema_name,
            ocp_provider_uuid=ocp_provider_uuid,
            cluster_id=actual_cluster_id,
            cluster_alias=cluster_alias,
            report_period_id=report_period_id,
            aws_provider_uuid=aws_provider_uuid,
            enabled_tag_keys=enabled_tag_keys,
            cost_entry_bill_id=cost_entry_bill_id,
            markup_percent=markup_percent,
        )

        # Run aggregation
        result_df = ocp_aws_agg.aggregate(year=year, month=month)

        # Write results
        writer = DatabaseWriter(schema_name)
        rows = writer.write_ocp_aws_summary_data(result_df)

        results["aggregators"]["ocp_aws"] = {"rows_written": rows}

        # COMPLETION BANNER
        LOG.warning("=" * 100)
        LOG.warning("🐍 PYTHON AGGREGATOR COMPLETE - OCP-ON-AWS")
        LOG.warning(f"   Total rows written: {rows}")
        LOG.warning(f"   Schema: {schema_name}")
        LOG.warning("=" * 100)

    except Exception as e:
        LOG.error("=" * 100)
        LOG.error("🐍 PYTHON AGGREGATOR FAILED - OCP-ON-AWS")
        LOG.error(f"   Error: {e}")
        LOG.error("=" * 100)
        LOG.error(f"Python Aggregator: OCP-on-AWS aggregation failed: {e}", exc_info=True)
        results["status"] = "error"
        results["error"] = str(e)

    return results

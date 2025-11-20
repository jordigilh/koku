"""Main entry point for OCP Parquet Aggregator POC."""

import argparse
import sys
from datetime import datetime

from .config_loader import get_config
from .utils import setup_logging, get_logger, PerformanceTimer, format_duration
from .parquet_reader import ParquetReader
from .aggregator_pod import PodAggregator, calculate_node_capacity
from .db_writer import DatabaseWriter


def run_poc(args):
    """Run the POC aggregation pipeline.

    Args:
        args: Command-line arguments
    """
    # Load configuration
    config = get_config(args.config)

    # Setup logging
    setup_logging(
        level=config.get('logging', {}).get('level', 'INFO'),
        log_format=config.get('logging', {}).get('format', 'console')
    )

    logger = get_logger("main")

    logger.info("=" * 80)
    logger.info("OCP Parquet Aggregator POC - Starting")
    logger.info("=" * 80)

    # Print configuration
    ocp_config = config['ocp']
    logger.info(
        "Configuration",
        provider_uuid=ocp_config['provider_uuid'],
        cluster_id=ocp_config['cluster_id'],
        year=ocp_config['year'],
        month=ocp_config['month'],
        start_date=ocp_config['start_date'],
        end_date=ocp_config['end_date']
    )

    # Total pipeline timer
    pipeline_start = datetime.now()

    try:
        # ====================================================================
        # Phase 1: Initialize components
        # ====================================================================
        logger.info("Phase 1: Initializing components...")

        parquet_reader = ParquetReader(config)
        db_writer = DatabaseWriter(config)

        # Test connectivity
        with db_writer:
            if not db_writer.test_connectivity():
                logger.error("Database connectivity test failed")
                return 1

        if not parquet_reader.test_connectivity():
            logger.error("S3 connectivity test failed")
            return 1

        logger.info("✓ Connectivity tests passed")

        # ====================================================================
        # Phase 2: Fetch enabled tag keys from PostgreSQL
        # ====================================================================
        logger.info("Phase 2: Fetching enabled tag keys...")

        with db_writer:
            enabled_tag_keys = db_writer.get_enabled_tag_keys()
            cost_category_df = db_writer.get_cost_category_namespaces()

        logger.info(f"✓ Fetched {len(enabled_tag_keys)} enabled tag keys")

        # ====================================================================
        # Phase 3: Read Parquet files from S3
        # ====================================================================
        logger.info("Phase 3: Reading Parquet files from S3...")

        provider_uuid = ocp_config['provider_uuid']
        year = ocp_config['year']
        month = ocp_config['month']

        # Read pod usage
        pod_usage_df = parquet_reader.read_pod_usage_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            streaming=False  # For POC, load entire file
        )

        if pod_usage_df.empty:
            logger.error("No pod usage data found")
            return 1

        logger.info(f"✓ Loaded pod usage data: {len(pod_usage_df)} rows")

        # Read node labels (optional)
        node_labels_df = parquet_reader.read_node_labels_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month
        )
        logger.info(f"✓ Loaded node labels: {len(node_labels_df)} rows")

        # Read namespace labels (optional)
        namespace_labels_df = parquet_reader.read_namespace_labels_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month
        )
        logger.info(f"✓ Loaded namespace labels: {len(namespace_labels_df)} rows")

        # ====================================================================
        # Phase 4: Calculate node and cluster capacity
        # ====================================================================
        logger.info("Phase 4: Calculating node and cluster capacity...")

        node_capacity_df, cluster_capacity_df = calculate_node_capacity(pod_usage_df)

        logger.info(
            f"✓ Calculated capacity for {len(node_capacity_df)} node-days, "
            f"{len(cluster_capacity_df)} cluster-days"
        )

        # ====================================================================
        # Phase 5: Aggregate pod usage
        # ====================================================================
        logger.info("Phase 5: Aggregating pod usage...")

        aggregator = PodAggregator(config, enabled_tag_keys)

        aggregated_df = aggregator.aggregate(
            pod_usage_df=pod_usage_df,
            node_capacity_df=node_capacity_df,
            node_labels_df=node_labels_df,
            namespace_labels_df=namespace_labels_df,
            cost_category_df=cost_category_df
        )

        logger.info(f"✓ Generated {len(aggregated_df)} summary rows")

        # ====================================================================
        # Phase 6: Write to PostgreSQL
        # ====================================================================
        logger.info("Phase 6: Writing to PostgreSQL...")

        with db_writer:
            rows_inserted = db_writer.write_summary_data(
                df=aggregated_df,
                batch_size=config.get('performance', {}).get('db_batch_size', 1000),
                truncate=args.truncate
            )

        logger.info(f"✓ Inserted {rows_inserted} rows")

        # ====================================================================
        # Phase 7: Validate results
        # ====================================================================
        logger.info("Phase 7: Validating results...")

        with db_writer:
            validation_result = db_writer.validate_summary_data(
                provider_uuid=provider_uuid,
                year=year,
                month=month
            )

        logger.info("✓ Validation complete")
        logger.info("Validation Results:")
        for key, value in validation_result.items():
            logger.info(f"  {key}: {value}")

        # ====================================================================
        # Phase 8: Validate against expected results (if requested)
        # ====================================================================
        if args.validate_expected:
            logger.info("Phase 8: Validating against expected results...")

            from .expected_results import ExpectedResultsCalculator, compare_results

            calculator = ExpectedResultsCalculator(args.validate_expected)
            expected_df = calculator.calculate_expected_aggregations()

            logger.info(f"Calculated {len(expected_df)} expected result rows")
            calculator.print_summary(expected_df)

            # Compare with aggregated results
            comparison_result = compare_results(expected_df, aggregated_df)

            if comparison_result['all_match']:
                logger.info("=" * 80)
                logger.info("✅ VALIDATION SUCCESS: ALL RESULTS MATCH EXPECTED VALUES!")
                logger.info("=" * 80)
                logger.info(f"Matched {comparison_result['match_count']}/{comparison_result['total_comparisons']} comparisons")
            else:
                logger.error("=" * 80)
                logger.error("❌ VALIDATION FAILED: DISCREPANCIES FOUND")
                logger.error("=" * 80)
                logger.error(f"Matched {comparison_result['match_count']}/{comparison_result['total_comparisons']} comparisons")
                logger.error(f"Missing in actual: {comparison_result['missing_in_actual_count']}")
                logger.error(f"Extra in actual: {comparison_result['extra_in_actual_count']}")
                logger.error(f"Issues found: {len(comparison_result['issues'])}")

                # Exit with error if validation fails
                return 1

        # ====================================================================
        # Summary
        # ====================================================================
        pipeline_end = datetime.now()
        total_duration = (pipeline_end - pipeline_start).total_seconds()

        logger.info("=" * 80)
        logger.info("POC COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info(f"Total duration: {format_duration(total_duration)}")
        logger.info(f"Input rows: {len(pod_usage_df):,}")
        logger.info(f"Output rows: {rows_inserted:,}")
        logger.info(f"Compression ratio: {len(pod_usage_df) / rows_inserted:.1f}x")
        logger.info(f"Processing rate: {len(pod_usage_df) / total_duration:.0f} rows/sec")
        logger.info("=" * 80)

        return 0

    except Exception as e:
        logger.error("POC failed with error", error=str(e), exc_info=True)
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="OCP Parquet Aggregator POC - Validate Trino + Hive replacement"
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.yaml (default: poc-parquet-aggregator/config/config.yaml)'
    )

    parser.add_argument(
        '--truncate',
        action='store_true',
        help='Truncate summary table before inserting (for testing)'
    )

    parser.add_argument(
        '--validate',
        action='store_true',
        help='Run validation against Trino results (not implemented yet)'
    )

    parser.add_argument(
        '--validate-expected',
        type=str,
        metavar='YAML_FILE',
        help='Validate against expected results from nise static YAML'
    )

    args = parser.parse_args()

    if args.validate:
        print("ERROR: Validation against Trino not yet implemented")
        print("This will be added in Phase 2 of the POC")
        return 1

    # Run POC
    exit_code = run_poc(args)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()


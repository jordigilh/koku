"""PostgreSQL database writer for aggregated OCP data - Koku native implementation."""

import io
import json
import logging
from typing import Dict, List, Optional

import pandas as pd
from django.db import connection
from django_tenants.utils import schema_context
from psycopg2.extras import execute_values

from reporting.provider.all.models import EnabledTagKeys

LOG = logging.getLogger(__name__)


class DatabaseWriter:
    """Write aggregated OCP data to PostgreSQL using Django's connection."""

    def __init__(self, schema_name: str):
        """Initialize database writer with koku's Django connection.

        Args:
            schema_name: Database schema (org ID, e.g., "org1234567")
        """
        self.schema = schema_name
        LOG.info(f"Initialized DatabaseWriter for schema={schema_name}")

    def get_enabled_tag_keys(self) -> List[str]:
        """Get enabled tag keys from PostgreSQL using Django ORM.

        Returns:
            List of enabled tag keys
        """
        with schema_context(self.schema):
            keys = list(
                EnabledTagKeys.objects.filter(enabled=True)
                .values_list("key", flat=True)
            )
            # Always include 'vm_kubevirt_io_name' (from Trino SQL line 96)
            keys = ["vm_kubevirt_io_name"] + list(keys)
            LOG.info(f"Fetched {len(keys)} enabled tag keys")
            return keys

    def get_cost_category_namespaces(self) -> pd.DataFrame:
        """Get cost category namespace mappings.

        Returns:
            DataFrame with namespace and cost_category_id columns
        """
        query = f"""
            SELECT namespace, cost_category_id
            FROM {self.schema}.reporting_ocp_cost_category_namespace
        """

        try:
            with connection.cursor() as cursor:
                cursor.db.set_schema(self.schema)
                cursor.execute(query)
                rows = cursor.fetchall()

            if rows:
                df = pd.DataFrame(rows, columns=["namespace", "cost_category_id"])
                LOG.info(f"Fetched {len(df)} cost category namespaces")
                return df
            return pd.DataFrame()
        except Exception as e:
            LOG.warning(f"Could not fetch cost category namespaces: {e}")
            return pd.DataFrame()

    def get_node_roles(self) -> pd.DataFrame:
        """Get node roles from reporting_ocp_nodes table.

        Returns:
            DataFrame with node, resource_id, node_role columns
        """
        query = f"""
            SELECT node, resource_id, MAX(node_role) as node_role
            FROM {self.schema}.reporting_ocp_nodes
            GROUP BY node, resource_id
        """

        try:
            with connection.cursor() as cursor:
                cursor.db.set_schema(self.schema)
                cursor.execute(query)
                rows = cursor.fetchall()

            if rows:
                df = pd.DataFrame(rows, columns=["node", "resource_id", "node_role"])
                LOG.info(f"Fetched {len(df)} node roles")
                return df
            return pd.DataFrame()
        except Exception as e:
            LOG.warning(f"Could not fetch node roles: {e}")
            return pd.DataFrame()

    def write_summary_data(
        self,
        df: pd.DataFrame,
        batch_size: int = 1000,
        truncate: bool = False,
    ) -> int:
        """Write OCP summary data to PostgreSQL.

        Args:
            df: DataFrame with aggregated data
            batch_size: Number of rows per batch insert
            truncate: Whether to truncate table first

        Returns:
            Number of rows inserted
        """
        table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"
        return self._write_data(df, table_name, batch_size, truncate)

    def write_ocp_aws_summary_data(
        self,
        df: pd.DataFrame,
        batch_size: int = 1000,
        truncate: bool = False,
    ) -> int:
        """Write OCP-AWS summary data to PostgreSQL.

        Args:
            df: DataFrame with OCP-AWS aggregated data
            batch_size: Number of rows per batch insert
            truncate: Whether to truncate table first

        Returns:
            Number of rows inserted
        """
        table_name = f"{self.schema}.reporting_ocpawscostlineitem_project_daily_summary_p"
        return self._write_data(df, table_name, batch_size, truncate, json_columns=["pod_labels", "tags", "aws_cost_category"])

    def _write_data(
        self,
        df: pd.DataFrame,
        table_name: str,
        batch_size: int,
        truncate: bool,
        json_columns: Optional[List[str]] = None,
    ) -> int:
        """Internal method to write data to a table.

        Args:
            df: DataFrame to write
            table_name: Full table name (schema.table)
            batch_size: Rows per batch
            truncate: Whether to truncate first
            json_columns: Columns that need JSON conversion

        Returns:
            Number of rows inserted
        """
        if df.empty:
            LOG.warning(f"Empty DataFrame, nothing to write to {table_name}")
            return 0

        LOG.info(f"Writing {len(df)} rows to {table_name}")

        try:
            # Get raw psycopg2 connection from Django
            raw_conn = connection.connection

            with raw_conn.cursor() as cursor:
                # Set schema
                cursor.execute(f"SET search_path TO {self.schema}")

                # Truncate if requested
                if truncate:
                    cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")
                    LOG.warning(f"Truncated {table_name}")

                # Prepare data - include uuid since we generate it in aggregators
                # (Koku's PostgreSQL schema requires uuid but doesn't auto-generate)
                columns = list(df.columns)
                df_insert = df[columns].copy()

                # Convert JSON columns
                if json_columns:
                    for col in json_columns:
                        if col in df_insert.columns:
                            df_insert[col] = df_insert[col].apply(self._to_json)

                # Replace NaN with None for PostgreSQL
                df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

                # Build INSERT query
                column_names = ", ".join(columns)
                insert_query = f"INSERT INTO {table_name} ({column_names}) VALUES %s"

                # Convert to tuples
                data = [tuple(row) for row in df_insert.values]

                # Batch insert
                total_inserted = 0
                for i in range(0, len(data), batch_size):
                    batch = data[i:i + batch_size]
                    execute_values(cursor, insert_query, batch, page_size=batch_size)
                    total_inserted += len(batch)

                raw_conn.commit()

            LOG.info(f"Successfully wrote {total_inserted} rows to {table_name}")
            return total_inserted

        except Exception as e:
            if connection.connection:
                connection.connection.rollback()
            LOG.error(f"Failed to write to {table_name}: {e}")
            raise

    def _to_json(self, value) -> Optional[str]:
        """Convert value to JSON string for JSONB columns."""
        if pd.isna(value) or value is None:
            return None
        if isinstance(value, dict):
            return json.dumps(value)
        if isinstance(value, str):
            try:
                json.loads(value)  # Validate
                return value
            except (ValueError, TypeError):
                return "{}"
        return "{}"

    def validate_summary_data(
        self,
        provider_uuid: str,
        year: int,
        month: int,
    ) -> Dict:
        """Validate summary data by querying aggregates.

        Args:
            provider_uuid: Provider UUID
            year: Year
            month: Month

        Returns:
            Dictionary with validation metrics
        """
        table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        query = f"""
            SELECT
                COUNT(*) as row_count,
                COUNT(DISTINCT namespace) as namespace_count,
                COUNT(DISTINCT node) as node_count,
                COUNT(DISTINCT usage_start) as day_count,
                SUM(pod_usage_cpu_core_hours) as total_cpu_hours,
                SUM(pod_usage_memory_gigabyte_hours) as total_memory_gb_hours
            FROM {table_name}
            WHERE source_uuid::text = %s
              AND EXTRACT(YEAR FROM usage_start) = %s
              AND EXTRACT(MONTH FROM usage_start) = %s
        """

        try:
            with connection.cursor() as cursor:
                cursor.db.set_schema(self.schema)
                cursor.execute(query, (provider_uuid, year, month))
                row = cursor.fetchone()

            result = {
                "row_count": row[0],
                "namespace_count": row[1],
                "node_count": row[2],
                "day_count": row[3],
                "total_cpu_hours": float(row[4]) if row[4] else 0.0,
                "total_memory_gb_hours": float(row[5]) if row[5] else 0.0,
            }

            LOG.info(f"Validation: {result}")
            return result

        except Exception as e:
            LOG.error(f"Validation failed: {e}")
            raise

    def create_streaming_writer(self, table_type: str = "ocp_aws") -> "StreamingDBWriter":
        """Create a streaming writer for incremental chunk writes.

        Args:
            table_type: Type of table ("ocp_aws" or "ocp")

        Returns:
            StreamingDBWriter context manager
        """
        if table_type == "ocp_aws":
            table_name = f"{self.schema}.reporting_ocpawscostlineitem_project_daily_summary_p"
        else:
            table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        return StreamingDBWriter(self.schema, table_name)


class StreamingDBWriter:
    """Context manager for streaming database writes."""

    def __init__(self, schema: str, table_name: str):
        self.schema = schema
        self.table_name = table_name
        self.total_rows = 0
        self.chunk_count = 0
        self._columns = None
        self._insert_query = None

    def __enter__(self):
        """Start transaction and prepare for writes."""
        LOG.info(f"Starting streaming write to {self.table_name}")

        # Truncate table
        raw_conn = connection.connection
        with raw_conn.cursor() as cursor:
            cursor.execute(f"SET search_path TO {self.schema}")
            cursor.execute(f"TRUNCATE TABLE {self.table_name} CASCADE")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit or rollback based on success."""
        raw_conn = connection.connection

        if exc_type is not None:
            raw_conn.rollback()
            LOG.error(f"Streaming write failed, rolled back: {exc_val}")
            return False
        else:
            raw_conn.commit()
            LOG.info(f"Streaming write complete: {self.chunk_count} chunks, {self.total_rows} rows")
            return True

    def write_chunk(self, df: pd.DataFrame, batch_size: int = 1000) -> int:
        """Write a single chunk to the database.

        Args:
            df: DataFrame chunk to write
            batch_size: Rows per batch insert

        Returns:
            Number of rows written
        """
        if df is None or df.empty:
            return 0

        self.chunk_count += 1
        chunk_rows = len(df)

        # Prepare columns (first time only)
        # Include uuid since we generate it in aggregators (Koku schema requires it)
        if self._columns is None:
            self._columns = list(df.columns)
            column_names = ", ".join(self._columns)
            self._insert_query = f"INSERT INTO {self.table_name} ({column_names}) VALUES %s"

        # Prepare data
        df_insert = df[self._columns].copy()

        # Convert JSON columns
        json_columns = ["pod_labels", "tags", "aws_cost_category"]
        for col in json_columns:
            if col in df_insert.columns:
                df_insert[col] = df_insert[col].apply(
                    lambda x: json.dumps(x) if isinstance(x, dict) else (x if pd.notna(x) else None)
                )

        # Replace NaN with None
        df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

        # Convert to tuples and insert
        data = [tuple(row) for row in df_insert.values]

        raw_conn = connection.connection
        with raw_conn.cursor() as cursor:
            cursor.execute(f"SET search_path TO {self.schema}")
            for i in range(0, len(data), batch_size):
                batch = data[i:i + batch_size]
                execute_values(cursor, self._insert_query, batch, page_size=batch_size)

        self.total_rows += chunk_rows
        LOG.debug(f"Chunk {self.chunk_count}: {chunk_rows} rows (total: {self.total_rows})")

        return chunk_rows

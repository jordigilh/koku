"""Parquet reader for OCP usage data from S3 - Koku native implementation."""

import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Iterator, List, Optional

import pandas as pd
import pyarrow.parquet as pq
from django.conf import settings

from masu.config import Config
from masu.util.aws.common import get_s3_resource
from masu.util.common import get_path_prefix

LOG = logging.getLogger(__name__)


class ParquetReader:
    """Read Parquet files from S3 using koku's native patterns."""

    def __init__(self, schema_name: str):
        """Initialize Parquet reader with koku's S3 configuration.

        Args:
            schema_name: Database schema (org ID, e.g., "org1234567")
        """
        self.schema = schema_name

        # S3 configuration from koku settings
        self.endpoint = settings.S3_ENDPOINT
        self.bucket = settings.S3_BUCKET_NAME
        self.access_key = settings.S3_ACCESS_KEY
        self.secret_key = settings.S3_SECRET
        self.region = settings.S3_REGION

        # Performance settings from environment
        self.use_categorical = os.getenv("POC_USE_CATEGORICAL", "true").lower() == "true"
        self.column_filtering = os.getenv("POC_COLUMN_FILTERING", "true").lower() == "true"
        self.parallel_readers = int(os.getenv("POC_PARALLEL_READERS", "4"))

        # Initialize S3 resource using koku's pattern
        self._s3_resource = None

        LOG.info(f"Initialized ParquetReader for schema={schema_name}, bucket={self.bucket}")

    @property
    def s3_resource(self):
        """Lazy-load S3 resource using koku's utility."""
        if self._s3_resource is None:
            self._s3_resource = get_s3_resource(
                self.access_key,
                self.secret_key,
                self.region,
                endpoint_url=self.endpoint,
            )
        return self._s3_resource

    def _get_s3_path(
        self,
        provider_uuid: str,
        start_date: date,
        report_type: str,
    ) -> str:
        """Build S3 path using koku's get_path_prefix.

        Args:
            provider_uuid: Provider UUID
            start_date: Start date for the data
            report_type: Type of report (pod_usage, storage_usage, node_labels, namespace_labels)

        Returns:
            S3 path prefix
        """
        return get_path_prefix(
            account=self.schema,
            provider_type="OCP",
            provider_uuid=provider_uuid,
            start_date=start_date,
            data_type=Config.PARQUET_DATA_TYPE,
            report_type=report_type,
            daily=True,
        )

    def list_parquet_files(self, s3_prefix: str) -> List[str]:
        """List all Parquet files in an S3 prefix.

        Args:
            s3_prefix: S3 prefix path

        Returns:
            List of S3 keys for Parquet files
        """
        LOG.debug(f"Listing Parquet files in: {self.bucket}/{s3_prefix}")

        try:
            bucket = self.s3_resource.Bucket(self.bucket)
            files = []
            for obj in bucket.objects.filter(Prefix=s3_prefix):
                if obj.key.endswith(".parquet"):
                    files.append(obj.key)

            LOG.info(f"Found {len(files)} Parquet files in {s3_prefix}")
            return files
        except Exception as e:
            LOG.error(f"Failed to list Parquet files: {e}")
            raise

    def read_parquet_file(
        self,
        s3_key: str,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read a single Parquet file from S3.

        Args:
            s3_key: S3 object key
            columns: List of columns to read (None = all columns)

        Returns:
            pandas DataFrame
        """
        LOG.debug(f"Reading parquet: {s3_key}")

        try:
            # Get object from S3
            obj = self.s3_resource.Object(self.bucket, s3_key)
            response = obj.get()
            data = response["Body"].read()

            # Read parquet with PyArrow
            parquet_file = pq.ParquetFile(io.BytesIO(data))
            table = parquet_file.read(columns=columns)
            df = table.to_pandas()

            # Apply memory optimization if enabled
            if self.use_categorical:
                df = self._optimize_dataframe_memory(df)

            LOG.info(f"Loaded {len(df)} rows from {Path(s3_key).name}")
            return df

        except Exception as e:
            LOG.error(f"Failed to read Parquet file {s3_key}: {e}")
            raise

    def read_parquet_streaming(
        self,
        s3_key: str,
        chunk_size: int = 10000,
        columns: Optional[List[str]] = None,
    ) -> Iterator[pd.DataFrame]:
        """Read Parquet file in chunks (streaming mode).

        Args:
            s3_key: S3 object key
            chunk_size: Number of rows per chunk
            columns: List of columns to read

        Yields:
            pandas DataFrame chunks
        """
        LOG.info(f"Starting streaming read: {s3_key}, chunk_size={chunk_size}")

        try:
            obj = self.s3_resource.Object(self.bucket, s3_key)
            response = obj.get()
            data = response["Body"].read()

            parquet_file = pq.ParquetFile(io.BytesIO(data))

            for batch in parquet_file.iter_batches(batch_size=chunk_size, columns=columns):
                df = batch.to_pandas()
                if self.use_categorical:
                    df = self._optimize_dataframe_memory(df)
                yield df

        except Exception as e:
            LOG.error(f"Failed to stream Parquet file {s3_key}: {e}")
            raise

    def read_pod_usage(
        self,
        provider_uuid: str,
        start_date: date,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """Read OCP pod usage line items.

        Args:
            provider_uuid: Provider UUID
            start_date: Start date
            streaming: Whether to stream chunks
            chunk_size: Chunk size for streaming

        Returns:
            DataFrame or Iterator of DataFrames
        """
        s3_prefix = self._get_s3_path(provider_uuid, start_date, "pod_usage")
        files = self.list_parquet_files(s3_prefix)

        if not files:
            LOG.warning(f"No pod usage files found in {s3_prefix}")
            return pd.DataFrame() if not streaming else iter([])

        columns = self.get_optimal_columns_pod_usage() if self.column_filtering else None

        if streaming:
            def stream_all():
                for f in files:
                    yield from self.read_parquet_streaming(f, chunk_size, columns)
            return stream_all()
        else:
            return self._read_files_parallel(files, columns)

    def read_storage_usage(
        self,
        provider_uuid: str,
        start_date: date,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """Read OCP storage usage line items.

        Args:
            provider_uuid: Provider UUID
            start_date: Start date
            streaming: Whether to stream chunks
            chunk_size: Chunk size for streaming

        Returns:
            DataFrame or Iterator of DataFrames
        """
        s3_prefix = self._get_s3_path(provider_uuid, start_date, "storage_usage")
        files = self.list_parquet_files(s3_prefix)

        if not files:
            LOG.warning(f"No storage usage files found in {s3_prefix}")
            return pd.DataFrame() if not streaming else iter([])

        columns = self.get_optimal_columns_storage_usage() if self.column_filtering else None

        if streaming:
            def stream_all():
                for f in files:
                    yield from self.read_parquet_streaming(f, chunk_size, columns)
            return stream_all()
        else:
            return self._read_files_parallel(files, columns)

    def read_node_labels(self, provider_uuid: str, start_date: date) -> pd.DataFrame:
        """Read OCP node labels.

        Args:
            provider_uuid: Provider UUID
            start_date: Start date

        Returns:
            DataFrame
        """
        s3_prefix = self._get_s3_path(provider_uuid, start_date, "node_labels")
        files = self.list_parquet_files(s3_prefix)

        if not files:
            LOG.warning(f"No node labels found in {s3_prefix}")
            return pd.DataFrame()

        return self._read_files_parallel(files)

    def read_namespace_labels(self, provider_uuid: str, start_date: date) -> pd.DataFrame:
        """Read OCP namespace labels.

        Args:
            provider_uuid: Provider UUID
            start_date: Start date

        Returns:
            DataFrame
        """
        s3_prefix = self._get_s3_path(provider_uuid, start_date, "namespace_labels")
        files = self.list_parquet_files(s3_prefix)

        if not files:
            LOG.warning(f"No namespace labels found in {s3_prefix}")
            return pd.DataFrame()

        return self._read_files_parallel(files)

    def _read_files_parallel(
        self,
        files: List[str],
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read multiple Parquet files in parallel.

        Args:
            files: List of S3 keys
            columns: Optional list of columns to read

        Returns:
            Combined DataFrame
        """
        if not files:
            return pd.DataFrame()

        LOG.info(f"Reading {len(files)} files in parallel (workers={self.parallel_readers})")

        dfs = []
        with ThreadPoolExecutor(max_workers=self.parallel_readers) as executor:
            future_to_file = {
                executor.submit(self.read_parquet_file, f, columns): f
                for f in files
            }

            for future in as_completed(future_to_file):
                try:
                    df = future.result()
                    if not df.empty:
                        dfs.append(df)
                except Exception as e:
                    file = future_to_file[future]
                    LOG.error(f"Failed to read {file}: {e}")

        if not dfs:
            return pd.DataFrame()

        combined = pd.concat(dfs, ignore_index=True)
        LOG.info(f"Combined {len(dfs)} files: {len(combined)} total rows")
        return combined

    def get_optimal_columns_pod_usage(self) -> List[str]:
        """Get optimal column list for pod usage (reduce memory)."""
        return [
            "interval_start",
            "namespace",
            "node",
            "pod",
            "resource_id",
            "cluster_id",
            "pod_labels",
            "pod_usage_cpu_core_seconds",
            "pod_request_cpu_core_seconds",
            "pod_limit_cpu_core_seconds",
            "pod_usage_memory_byte_seconds",
            "pod_request_memory_byte_seconds",
            "pod_limit_memory_byte_seconds",
            "node_capacity_cpu_core_seconds",
            "node_capacity_memory_byte_seconds",
        ]

    def get_optimal_columns_storage_usage(self) -> List[str]:
        """Get optimal column list for storage usage (reduce memory)."""
        return [
            "interval_start",
            "namespace",
            "pod",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "cluster_id",
            "persistentvolumeclaim_capacity_byte_seconds",
            "volume_request_storage_byte_seconds",
            "persistentvolumeclaim_usage_byte_seconds",
            "persistentvolume_labels",
            "persistentvolumeclaim_labels",
            "csi_volume_handle",
        ]

    def _optimize_dataframe_memory(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimize DataFrame memory using categorical types."""
        categorical_cols = ["namespace", "node", "pod", "resource_id", "cluster_id"]

        for col in categorical_cols:
            if col in df.columns and df[col].dtype == "object":
                df[col] = df[col].astype("category")

        return df

    def test_connectivity(self) -> bool:
        """Test S3 connectivity."""
        try:
            bucket = self.s3_resource.Bucket(self.bucket)
            # Just check if bucket exists
            bucket.creation_date
            LOG.info(f"S3 connectivity test: SUCCESS (bucket={self.bucket})")
            return True
        except Exception as e:
            LOG.error(f"S3 connectivity test: FAILED - {e}")
            return False

    # =========================================================================
    # POC-compatible methods (wrappers for aggregator_ocp_aws.py compatibility)
    # These methods use year/month strings instead of date objects
    # =========================================================================

    def read_pod_usage_line_items(
        self,
        provider_uuid: str,
        year: int,
        month: int,
        daily: bool = True,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """POC-compatible wrapper for read_pod_usage.

        Converts year/month to date and calls read_pod_usage.
        """
        start_date = date(int(year), int(month), 1)
        return self.read_pod_usage(provider_uuid, start_date, streaming, chunk_size)

    def read_storage_usage_line_items(
        self,
        provider_uuid: str,
        year: int,
        month: int,
        daily: bool = True,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """POC-compatible wrapper for read_storage_usage.

        Converts year/month to date and calls read_storage_usage.
        """
        start_date = date(int(year), int(month), 1)
        return self.read_storage_usage(provider_uuid, start_date, streaming, chunk_size)

    def read_node_labels_line_items(
        self,
        provider_uuid: str,
        year: int,
        month: int,
    ) -> pd.DataFrame:
        """POC-compatible wrapper for read_node_labels.

        Converts year/month to date and calls read_node_labels.
        """
        start_date = date(int(year), int(month), 1)
        return self.read_node_labels(provider_uuid, start_date)

    def read_namespace_labels_line_items(
        self,
        provider_uuid: str,
        year: int,
        month: int,
    ) -> pd.DataFrame:
        """POC-compatible wrapper for read_namespace_labels.

        Converts year/month to date and calls read_namespace_labels.
        """
        start_date = date(int(year), int(month), 1)
        return self.read_namespace_labels(provider_uuid, start_date)

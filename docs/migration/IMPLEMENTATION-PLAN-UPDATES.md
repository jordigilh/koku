# IMPLEMENTATION PLAN UPDATES
**Based on Pre-Implementation Clarifications**

---

## 📋 Key Changes to Implementation Plan

### **1. Data Architecture Changes**

#### **Before**: Org-Specific Schemas
```sql
-- Old approach (one schema per org)
org1234567.aws_line_items_daily_staging
org7890123.aws_line_items_daily_staging
```

#### **After**: Shared Schema with Tenant ID
```sql
-- New approach (shared schema, tenant_id column)
public.aws_line_items_daily_staging
  - tenant_id (references tenants table)
  - source_uuid
  - ... other columns
```

**Impact**: 
- Simpler schema management
- Better for multi-tenancy
- Easier to maintain

---

### **2. Data Pipeline Simplification**

#### **Before**: CSV → Parquet → Hive → PostgreSQL
```
CSV Files
  ↓
Parquet Conversion (MASU)
  ↓
S3/MinIO Storage
  ↓
Hive External Tables
  ↓
Trino Queries
  ↓
PostgreSQL Summary Tables
```

#### **After**: CSV → PostgreSQL (Direct)
```
CSV Files
  ↓
PostgreSQL Staging Tables (Direct COPY)
  ↓
PostgreSQL Summary Tables
```

**Benefits**:
- ✅ Eliminates Parquet generation
- ✅ Eliminates S3/MinIO dependency
- ✅ Eliminates Hive Metastore
- ✅ Eliminates Trino
- ✅ Simpler pipeline (1 step instead of 5)

**Note**: Can add Parquet back later if performance testing shows benefit.

---

### **3. Timeline Restructure: Daily Deliverables**

#### **New Timeline** (30 days with daily checkpoints):

**Week 1: Foundation (Days 1-5)**
- **Day 1**: Environment setup + PostgreSQL 16 deployment
- **Day 2**: Staging tables creation + indexes
- **Day 3**: Custom PostgreSQL functions deployment
- **Day 4**: Python helpers + CSV loading logic
- **Day 5**: Feature flag + accessor refactoring

**Week 2: Core SQL Migration (Days 6-10)**
- **Day 6**: AWS daily summary migration
- **Day 7**: Azure daily summary migration
- **Day 8**: GCP daily summary migration
- **Day 9**: OCP daily summary migration
- **Day 10**: Tag matching queries (AWS/Azure)

**Week 3: OCP-on-Cloud Queries (Days 11-15)**
- **Day 11-12**: AWS-on-OCP queries (12 files)
- **Day 13-14**: Azure-on-OCP queries (12 files)
- **Day 15**: GCP-on-OCP queries (12 files)

**Week 4: Remaining Queries + Unit Tests (Days 16-20)**
- **Day 16-17**: OCP cost model queries (7 files)
- **Day 18**: Infrastructure provider maps (3 files)
- **Day 19**: Special queries (2 files)
- **Day 20**: All unit tests complete

**Week 5: Integration + Performance Testing (Days 21-25)**
- **Day 21**: IQE test suite integration
- **Day 22**: Integration tests (AWS/Azure/GCP)
- **Day 23**: Integration tests (OCP/OCP-on-Cloud)
- **Day 24**: Trino baseline capture (optional)
- **Day 25**: Performance comparison tests

**Week 6: Deployment + Validation (Days 26-30)**
- **Day 26**: Docker Compose dev environment
- **Day 27**: OpenShift manifests + Prometheus integration
- **Day 28**: Dev deployment + smoke tests
- **Day 29**: Staging deployment + validation
- **Day 30**: Production deployment + monitoring

---

### **4. PostgreSQL 16 Configuration**

#### **Image**: `registry.redhat.io/rhel10/postgresql-16@sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1`

#### **Extensions to Enable**:
```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";     -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";  -- Query monitoring
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- Text search (for tag matching)
```

#### **Configuration Tuning**:
```conf
# postgresql.conf optimizations
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 64MB
min_wal_size = 1GB
max_wal_size = 4GB
max_worker_processes = 8
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
```

---

### **5. Staging Tables DDL**

#### **File**: `koku/masu/database/sql/create_staging_tables.sql`

```sql
-- ============================================================================
-- PostgreSQL Staging Tables for CSV Direct Loading
-- ============================================================================
-- Purpose: Replace Hive external tables with PostgreSQL staging tables
-- Author: Koku Development Team
-- Date: November 2025
-- ============================================================================

-- Tenants table (for multi-tenancy)
CREATE TABLE IF NOT EXISTS public.tenants (
    id SERIAL PRIMARY KEY,
    schema_name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AWS Line Items Daily Staging
CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging (
    -- Metadata
    tenant_id INTEGER NOT NULL REFERENCES public.tenants(id),
    source UUID NOT NULL,
    year VARCHAR(4) NOT NULL,
    month VARCHAR(2) NOT NULL,
    row_uuid UUID DEFAULT gen_random_uuid(),
    
    -- AWS CUR fields (from CSV)
    bill_billingentity VARCHAR(255),
    bill_billingperiodstartdate TIMESTAMP,
    bill_billingperiodenddate TIMESTAMP,
    bill_invoiceid VARCHAR(255),
    bill_payeraccountid VARCHAR(50),
    
    lineitem_usagestartdate TIMESTAMP NOT NULL,
    lineitem_usageenddate TIMESTAMP,
    lineitem_productcode VARCHAR(255),
    lineitem_usagetype VARCHAR(255),
    lineitem_operation VARCHAR(255),
    lineitem_availabilityzone VARCHAR(50),
    lineitem_resourceid TEXT,
    lineitem_usageamount DECIMAL(24,9),
    lineitem_normalizationfactor DECIMAL(24,9),
    lineitem_normalizedusageamount DECIMAL(24,9),
    lineitem_currencycode VARCHAR(10),
    lineitem_unblendedrate DECIMAL(24,9),
    lineitem_unblendedcost DECIMAL(24,9),
    lineitem_blendedrate DECIMAL(24,9),
    lineitem_blendedcost DECIMAL(24,9),
    lineitem_lineitemtype VARCHAR(50),
    lineitem_usageaccountid VARCHAR(50),
    
    product_productname VARCHAR(255),
    product_productfamily VARCHAR(255),
    product_region VARCHAR(50),
    product_instancetype VARCHAR(100),
    
    pricing_unit VARCHAR(50),
    pricing_publicondemandcost DECIMAL(24,9),
    pricing_publicondemandrate DECIMAL(24,9),
    
    savingsplan_savingsplaneffectivecost DECIMAL(24,9),
    
    resourcetags JSONB,
    costcategory JSONB,
    
    -- Partitioning key
    partition_date DATE GENERATED ALWAYS AS (lineitem_usagestartdate::date) STORED,
    
    -- Constraints
    PRIMARY KEY (tenant_id, source, year, month, row_uuid)
) PARTITION BY RANGE (partition_date);

-- Create partitions for current and next 3 months
-- (Add more as needed)
CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2025_11
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2025_12
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

-- Indexes for AWS staging table
CREATE INDEX IF NOT EXISTS idx_aws_staging_tenant_source_date
    ON public.aws_line_items_daily_staging (tenant_id, source, partition_date);

CREATE INDEX IF NOT EXISTS idx_aws_staging_usage_date
    ON public.aws_line_items_daily_staging (lineitem_usagestartdate);

CREATE INDEX IF NOT EXISTS idx_aws_staging_resource_id
    ON public.aws_line_items_daily_staging (lineitem_resourceid);

CREATE INDEX IF NOT EXISTS idx_aws_staging_account_id
    ON public.aws_line_items_daily_staging (lineitem_usageaccountid);

-- GIN index for JSONB tags (fast tag filtering)
CREATE INDEX IF NOT EXISTS idx_aws_staging_tags_gin
    ON public.aws_line_items_daily_staging USING GIN (resourcetags jsonb_path_ops);

-- Similar tables for Azure, GCP, OCP...
-- (Abbreviated for brevity - full DDL in actual implementation)

-- Azure Line Items Daily Staging
CREATE TABLE IF NOT EXISTS public.azure_line_items_daily_staging (
    tenant_id INTEGER NOT NULL REFERENCES public.tenants(id),
    source UUID NOT NULL,
    year VARCHAR(4) NOT NULL,
    month VARCHAR(2) NOT NULL,
    row_uuid UUID DEFAULT gen_random_uuid(),
    
    -- Azure fields
    subscriptionid VARCHAR(255),
    resourceid TEXT,
    usagedatetime TIMESTAMP NOT NULL,
    metercategory VARCHAR(255),
    metersubcategory VARCHAR(255),
    meterid VARCHAR(255),
    meterregion VARCHAR(100),
    usagequantity DECIMAL(24,9),
    resourcerate DECIMAL(24,9),
    pretaxcost DECIMAL(24,9),
    costinbillingcurrency DECIMAL(24,9),
    tags JSONB,
    
    partition_date DATE GENERATED ALWAYS AS (usagedatetime::date) STORED,
    PRIMARY KEY (tenant_id, source, year, month, row_uuid)
) PARTITION BY RANGE (partition_date);

-- GCP Line Items Daily Staging
CREATE TABLE IF NOT EXISTS public.gcp_line_items_daily_staging (
    tenant_id INTEGER NOT NULL REFERENCES public.tenants(id),
    source UUID NOT NULL,
    year VARCHAR(4) NOT NULL,
    month VARCHAR(2) NOT NULL,
    row_uuid UUID DEFAULT gen_random_uuid(),
    
    -- GCP fields
    billing_account_id VARCHAR(255),
    project_id VARCHAR(255),
    project_name VARCHAR(255),
    service_description VARCHAR(255),
    sku_description VARCHAR(255),
    usage_start_time TIMESTAMP NOT NULL,
    usage_end_time TIMESTAMP,
    usage_amount DECIMAL(24,9),
    usage_unit VARCHAR(50),
    cost DECIMAL(24,9),
    currency VARCHAR(10),
    resource_name TEXT,
    labels JSONB,
    
    partition_date DATE GENERATED ALWAYS AS (usage_start_time::date) STORED,
    PRIMARY KEY (tenant_id, source, year, month, row_uuid)
) PARTITION BY RANGE (partition_date);

-- OCP Pod Usage Line Items Daily
CREATE TABLE IF NOT EXISTS public.openshift_pod_usage_line_items_daily (
    tenant_id INTEGER NOT NULL REFERENCES public.tenants(id),
    source UUID NOT NULL,
    year VARCHAR(4) NOT NULL,
    month VARCHAR(2) NOT NULL,
    row_uuid UUID DEFAULT gen_random_uuid(),
    
    -- OCP fields
    cluster_id VARCHAR(255),
    cluster_alias VARCHAR(255),
    namespace VARCHAR(255),
    pod VARCHAR(255),
    node VARCHAR(255),
    resource_id VARCHAR(255),
    interval_start TIMESTAMP NOT NULL,
    interval_end TIMESTAMP,
    pod_usage_cpu_core_seconds DECIMAL(24,9),
    pod_request_cpu_core_seconds DECIMAL(24,9),
    pod_limit_cpu_core_seconds DECIMAL(24,9),
    pod_usage_memory_byte_seconds DECIMAL(24,9),
    pod_request_memory_byte_seconds DECIMAL(24,9),
    pod_limit_memory_byte_seconds DECIMAL(24,9),
    pod_labels JSONB,
    volume_labels JSONB,
    
    partition_date DATE GENERATED ALWAYS AS (interval_start::date) STORED,
    PRIMARY KEY (tenant_id, source, year, month, row_uuid)
) PARTITION BY RANGE (partition_date);

-- ============================================================================
-- CSV Loading Helper Function
-- ============================================================================

CREATE OR REPLACE FUNCTION load_csv_to_staging(
    p_tenant_id INTEGER,
    p_source UUID,
    p_provider_type VARCHAR(10),  -- 'AWS', 'Azure', 'GCP', 'OCP'
    p_csv_path TEXT,
    p_year VARCHAR(4),
    p_month VARCHAR(2)
) RETURNS INTEGER AS $$
DECLARE
    v_table_name TEXT;
    v_copy_sql TEXT;
    v_row_count INTEGER;
BEGIN
    -- Determine target table based on provider type
    v_table_name := CASE p_provider_type
        WHEN 'AWS' THEN 'aws_line_items_daily_staging'
        WHEN 'Azure' THEN 'azure_line_items_daily_staging'
        WHEN 'GCP' THEN 'gcp_line_items_daily_staging'
        WHEN 'OCP' THEN 'openshift_pod_usage_line_items_daily'
        ELSE NULL
    END;
    
    IF v_table_name IS NULL THEN
        RAISE EXCEPTION 'Invalid provider type: %', p_provider_type;
    END IF;
    
    -- Build COPY command
    v_copy_sql := format(
        'COPY public.%I (tenant_id, source, year, month, %s) 
         FROM %L 
         WITH (FORMAT csv, HEADER true, DELIMITER '','', ENCODING ''UTF8'')',
        v_table_name,
        -- Column list varies by provider (omitted for brevity)
        'lineitem_usagestartdate, lineitem_usageamount, ...',
        p_csv_path
    );
    
    -- Execute COPY
    EXECUTE v_copy_sql;
    
    -- Get row count
    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    
    RETURN v_row_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Partition Management Function
-- ============================================================================

CREATE OR REPLACE FUNCTION create_staging_partition(
    p_table_name TEXT,
    p_partition_date DATE
) RETURNS VOID AS $$
DECLARE
    v_partition_name TEXT;
    v_start_date DATE;
    v_end_date DATE;
BEGIN
    -- Calculate partition boundaries (monthly partitions)
    v_start_date := date_trunc('month', p_partition_date);
    v_end_date := v_start_date + INTERVAL '1 month';
    
    -- Generate partition name
    v_partition_name := format(
        '%s_%s',
        p_table_name,
        to_char(v_start_date, 'YYYY_MM')
    );
    
    -- Create partition if it doesn't exist
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS public.%I 
         PARTITION OF public.%I 
         FOR VALUES FROM (%L) TO (%L)',
        v_partition_name,
        p_table_name,
        v_start_date,
        v_end_date
    );
    
    RAISE NOTICE 'Created partition: %', v_partition_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Analyze all staging tables
-- ============================================================================
ANALYZE public.aws_line_items_daily_staging;
ANALYZE public.azure_line_items_daily_staging;
ANALYZE public.gcp_line_items_daily_staging;
ANALYZE public.openshift_pod_usage_line_items_daily;
```

---

### **6. CSV Direct Loading Implementation**

#### **File**: `koku/masu/processor/csv_loader.py`

```python
"""
CSV Direct Loader for PostgreSQL
=================================
Purpose: Load CSV files directly into PostgreSQL staging tables
Replaces: ParquetReportProcessor + Hive table creation
"""

import logging
import os
from typing import Dict, Optional
from django.db import connection
from django.conf import settings

LOG = logging.getLogger(__name__)


class CSVDirectLoader:
    """Load CSV files directly into PostgreSQL staging tables"""
    
    def __init__(self, tenant_id: int, source_uuid: str, provider_type: str):
        """
        Initialize CSV loader.
        
        Args:
            tenant_id: Tenant ID from tenants table
            source_uuid: Provider source UUID
            provider_type: 'AWS', 'Azure', 'GCP', or 'OCP'
        """
        self.tenant_id = tenant_id
        self.source_uuid = source_uuid
        self.provider_type = provider_type.upper()
        
        # Map provider types to table names
        self.table_map = {
            'AWS': 'aws_line_items_daily_staging',
            'AZURE': 'azure_line_items_daily_staging',
            'GCP': 'gcp_line_items_daily_staging',
            'OCP': 'openshift_pod_usage_line_items_daily'
        }
    
    def load_csv_file(self, csv_file_path: str, year: str, month: str) -> int:
        """
        Load CSV file directly into PostgreSQL staging table.
        
        Args:
            csv_file_path: Path to CSV file
            year: Year (YYYY)
            month: Month (MM)
            
        Returns:
            Number of rows loaded
            
        Example:
            >>> loader = CSVDirectLoader(tenant_id=1, source_uuid='...', provider_type='AWS')
            >>> rows = loader.load_csv_file('/path/to/file.csv', '2025', '11')
            >>> print(f"Loaded {rows} rows")
        """
        if not os.path.exists(csv_file_path):
            raise FileNotFoundError(f"CSV file not found: {csv_file_path}")
        
        table_name = self.table_map.get(self.provider_type)
        if not table_name:
            raise ValueError(f"Invalid provider type: {self.provider_type}")
        
        LOG.info(f"Loading CSV file: {csv_file_path} into {table_name}")
        
        # Ensure partition exists for this month
        self._ensure_partition_exists(table_name, year, month)
        
        # Load CSV using PostgreSQL COPY command
        row_count = self._copy_csv_to_table(csv_file_path, table_name, year, month)
        
        LOG.info(f"Successfully loaded {row_count} rows from {csv_file_path}")
        
        return row_count
    
    def _ensure_partition_exists(self, table_name: str, year: str, month: str):
        """Ensure partition exists for the given year/month"""
        partition_date = f"{year}-{month}-01"
        
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT create_staging_partition(%s, %s)",
                [table_name, partition_date]
            )
    
    def _copy_csv_to_table(self, csv_file_path: str, table_name: str, year: str, month: str) -> int:
        """
        Use PostgreSQL COPY command to load CSV.
        
        This is the fastest way to load data into PostgreSQL.
        """
        # Get column list for this provider type
        columns = self._get_column_list(self.provider_type)
        
        # Build COPY command
        copy_sql = f"""
            COPY public.{table_name} (
                tenant_id,
                source,
                year,
                month,
                {columns}
            )
            FROM STDIN
            WITH (
                FORMAT csv,
                HEADER true,
                DELIMITER ',',
                ENCODING 'UTF8',
                NULL ''
            )
        """
        
        # Execute COPY
        with connection.cursor() as cursor:
            with open(csv_file_path, 'r') as f:
                cursor.copy_expert(copy_sql, f)
                row_count = cursor.rowcount
        
        return row_count
    
    def _get_column_list(self, provider_type: str) -> str:
        """Get comma-separated column list for provider type"""
        # Column mappings for each provider
        # (Abbreviated - full list in actual implementation)
        
        columns_map = {
            'AWS': """
                bill_billingentity,
                lineitem_usagestartdate,
                lineitem_usageamount,
                lineitem_unblendedcost,
                resourcetags,
                costcategory
                -- ... all AWS CUR columns
            """,
            'AZURE': """
                subscriptionid,
                usagedatetime,
                usagequantity,
                pretaxcost,
                tags
                -- ... all Azure columns
            """,
            'GCP': """
                billing_account_id,
                project_id,
                usage_start_time,
                cost,
                labels
                -- ... all GCP columns
            """,
            'OCP': """
                cluster_id,
                namespace,
                pod,
                interval_start,
                pod_usage_cpu_core_seconds,
                pod_labels
                -- ... all OCP columns
            """
        }
        
        return columns_map.get(provider_type, '')


# Example usage in MASU processor
def process_csv_report(tenant_id, source_uuid, provider_type, csv_file_path, year, month):
    """
    Process CSV report by loading directly into PostgreSQL.
    
    This replaces the old flow:
        CSV → Parquet → S3 → Hive → Trino → PostgreSQL
    
    With new flow:
        CSV → PostgreSQL (direct)
    """
    loader = CSVDirectLoader(tenant_id, source_uuid, provider_type)
    row_count = loader.load_csv_file(csv_file_path, year, month)
    
    LOG.info(f"Processed {row_count} rows for {provider_type} source {source_uuid}")
    
    return row_count
```

---

## 📅 Updated Daily Deliverables Checklist

I'll create a separate detailed daily plan that breaks down each day's work with specific deliverables, acceptance criteria, and checkpoints.

Would you like me to:

1. **Create the detailed 30-day plan** with daily deliverables?
2. **Update the main implementation plan** with all these changes?
3. **Create OpenShift deployment manifests** now?
4. **Create Docker Compose dev environment** now?

Or should I proceed with all of the above?


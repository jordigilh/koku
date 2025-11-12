# TRINO TO POSTGRESQL IMPLEMENTATION PLAN V2
**Complete Developer Guide for On-Prem Deployment Without Trino**
**Updated with Simplified Architecture & Daily Deliverables**

---

## 📋 Document Overview

**Purpose**: Step-by-step implementation guide for deploying Koku on-prem with PostgreSQL-only architecture
**Target Audience**: Mid-level Python/PostgreSQL developer
**Estimated Effort**: 30 days (6 weeks) with daily checkpoints
**Complexity**: Moderate
**Risk Level**: Low (new deployment, simplified architecture)

---

## 🎯 Executive Summary

### **Goal**
Deploy Koku Cost Management on-prem with PostgreSQL-only architecture, eliminating all intermediate complexity:
- ❌ No Parquet files
- ❌ No S3/MinIO dependency
- ❌ No Hive Metastore
- ❌ No Trino
- ✅ **Simple pipeline**: CSV → PostgreSQL → API

### **Architecture Comparison**

#### **Old Architecture** (Complex)
```
CSV Files
  ↓
Parquet Conversion (MASU)
  ↓
S3/MinIO Storage
  ↓
Hive External Tables
  ↓
Trino Complex Queries
  ↓
PostgreSQL Summary Tables
  ↓
API Responses
```

#### **New Architecture** (Simplified)
```
CSV Files
  ↓
PostgreSQL Staging Tables (Direct COPY)
  ↓
PostgreSQL Summary Tables
  ↓
API Responses
```

**Complexity Reduction**: 7 components → 2 components (71% reduction)

---

### **Success Criteria**
1. ✅ All 60 SQL queries execute successfully in PostgreSQL
2. ✅ All 128 migration-specific tests pass
3. ✅ All 85 IQE baseline tests pass
4. ✅ CSV files load directly into PostgreSQL (no Parquet)
5. ✅ Shared schema multi-tenancy working
6. ✅ OpenShift deployment successful
7. ✅ Docker Compose dev environment working

### **Timeline: 30 Days with Daily Deliverables**

| Week | Days | Focus | Deliverable |
|------|------|-------|-------------|
| **Week 1** | 1-5 | Foundation | PostgreSQL 16 + staging tables + custom functions |
| **Week 2** | 6-10 | Core SQL | AWS/Azure/GCP/OCP daily summaries + tag matching |
| **Week 3** | 11-15 | OCP-on-Cloud | 36 OCP integration queries |
| **Week 4** | 16-20 | Remaining SQL | Cost models + special queries + unit tests |
| **Week 5** | 21-25 | Testing | IQE integration + performance tests |
| **Week 6** | 26-30 | Deployment | Docker Compose + OpenShift + production |

---

## 📦 Phase 1: Foundation (Week 1, Days 1-5)

### **Day 1: Environment Setup + PostgreSQL 16 Deployment**

**Deliverable**: Working PostgreSQL 16 instance with extensions

#### **Task 1.1: Local Development Setup**

```bash
# Clone repository
cd /Users/jgil/go/src/github.com/insights-onprem
git clone https://github.com/insights-onprem/koku.git
cd koku
git checkout -b feature/postgresql-only-migration

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

#### **Task 1.2: PostgreSQL 16 Local Setup**

```bash
# Pull PostgreSQL 16 image (Red Hat registry)
podman pull registry.redhat.io/rhel10/postgresql-16@sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1

# Run PostgreSQL 16 container
podman run -d \
  --name koku-postgres \
  -e POSTGRESQL_USER=koku \
  -e POSTGRESQL_PASSWORD=koku \
  -e POSTGRESQL_DATABASE=koku \
  -p 5432:5432 \
  registry.redhat.io/rhel10/postgresql-16@sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1

# Verify connection
psql -h localhost -U koku -d koku -c "SELECT version();"
```

#### **Task 1.3: Enable Required Extensions**

**File**: `koku/masu/database/sql/enable_extensions.sql`

```sql
-- Enable required PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";           -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";  -- Query monitoring
CREATE EXTENSION IF NOT EXISTS "pg_trgm";             -- Text search for tags
CREATE EXTENSION IF NOT EXISTS "btree_gin";           -- GIN index optimization
CREATE EXTENSION IF NOT EXISTS "btree_gist";          -- GIST index optimization

-- Verify extensions
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('uuid-ossp', 'pg_stat_statements', 'pg_trgm', 'btree_gin', 'btree_gist');
```

```bash
# Deploy extensions
psql -h localhost -U koku -d koku -f koku/masu/database/sql/enable_extensions.sql
```

#### **Task 1.4: Configure PostgreSQL for Performance**

**File**: `koku/masu/database/sql/postgresql.conf.optimized`

```conf
# PostgreSQL 16 Performance Tuning for Koku
# Assumes 16GB RAM, 8 CPU cores

# Memory Settings
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
work_mem = 64MB

# Checkpoint Settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
min_wal_size = 1GB
max_wal_size = 4GB

# Query Planner
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200

# Parallelism
max_worker_processes = 8
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
max_parallel_maintenance_workers = 4

# Logging (for development)
log_statement = 'mod'
log_duration = on
log_min_duration_statement = 1000  # Log queries > 1 second

# Query Monitoring
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
```

**Checkpoint**: ✅ PostgreSQL 16 running with all extensions enabled

---

### **Day 2: Staging Tables Creation + Indexes**

**Deliverable**: All staging tables created with proper partitioning and indexes

#### **Task 2.1: Create Tenants Table**

**File**: `koku/masu/database/sql/001_create_tenants_table.sql`

```sql
-- Tenants table for multi-tenancy (shared schema approach)
CREATE TABLE IF NOT EXISTS public.tenants (
    id SERIAL PRIMARY KEY,
    schema_name VARCHAR(255) UNIQUE NOT NULL,
    org_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for lookups
CREATE INDEX IF NOT EXISTS idx_tenants_schema_name ON public.tenants(schema_name);
CREATE INDEX IF NOT EXISTS idx_tenants_org_id ON public.tenants(org_id);

-- Insert default tenant for development
INSERT INTO public.tenants (schema_name, org_id)
VALUES ('org1234567', '1234567')
ON CONFLICT (schema_name) DO NOTHING;
```

#### **Task 2.2: Create AWS Staging Table**

**File**: `koku/masu/database/sql/002_create_aws_staging_table.sql`

```sql
-- AWS Line Items Daily Staging (Partitioned by month)
CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging (
    -- Metadata
    tenant_id INTEGER NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    source UUID NOT NULL,
    year VARCHAR(4) NOT NULL,
    month VARCHAR(2) NOT NULL,
    row_uuid UUID DEFAULT gen_random_uuid(),

    -- AWS CUR Standard Fields
    bill_billingentity VARCHAR(255),
    bill_billingperiodstartdate TIMESTAMP,
    bill_billingperiodenddate TIMESTAMP,
    bill_invoiceid VARCHAR(255),
    bill_payeraccountid VARCHAR(50),

    -- Line Item Fields
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

    -- Product Fields
    product_productname VARCHAR(255),
    product_productfamily VARCHAR(255),
    product_region VARCHAR(50),
    product_instancetype VARCHAR(100),

    -- Pricing Fields
    pricing_unit VARCHAR(50),
    pricing_publicondemandcost DECIMAL(24,9),
    pricing_publicondemandrate DECIMAL(24,9),

    -- Savings Plan Fields
    savingsplan_savingsplaneffectivecost DECIMAL(24,9),

    -- Tags and Cost Category (JSONB for flexible querying)
    resourcetags JSONB,
    costcategory JSONB,

    -- Partitioning key (generated column)
    partition_date DATE GENERATED ALWAYS AS (lineitem_usagestartdate::date) STORED,

    -- Primary Key
    PRIMARY KEY (tenant_id, source, year, month, row_uuid, partition_date)
) PARTITION BY RANGE (partition_date);

-- Create initial partitions (current month + next 3 months)
CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2025_11
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');

CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2025_12
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2026_01
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE IF NOT EXISTS public.aws_line_items_daily_staging_2026_02
    PARTITION OF public.aws_line_items_daily_staging
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- Indexes for AWS staging table
CREATE INDEX IF NOT EXISTS idx_aws_staging_tenant_source_year_month
    ON public.aws_line_items_daily_staging (tenant_id, source, year, month);

CREATE INDEX IF NOT EXISTS idx_aws_staging_usage_date
    ON public.aws_line_items_daily_staging (lineitem_usagestartdate);

CREATE INDEX IF NOT EXISTS idx_aws_staging_partition_date
    ON public.aws_line_items_daily_staging (partition_date);

CREATE INDEX IF NOT EXISTS idx_aws_staging_resource_id
    ON public.aws_line_items_daily_staging (lineitem_resourceid)
    WHERE lineitem_resourceid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_aws_staging_account_id
    ON public.aws_line_items_daily_staging (lineitem_usageaccountid);

CREATE INDEX IF NOT EXISTS idx_aws_staging_product_code
    ON public.aws_line_items_daily_staging (lineitem_productcode);

-- GIN index for JSONB tags (enables fast tag filtering)
CREATE INDEX IF NOT EXISTS idx_aws_staging_tags_gin
    ON public.aws_line_items_daily_staging USING GIN (resourcetags jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_aws_staging_costcategory_gin
    ON public.aws_line_items_daily_staging USING GIN (costcategory jsonb_path_ops);

-- Analyze table for query planner
ANALYZE public.aws_line_items_daily_staging;
```

#### **Task 2.3: Create Azure, GCP, OCP Staging Tables**

**Files**:
- `003_create_azure_staging_table.sql`
- `004_create_gcp_staging_table.sql`
- `005_create_ocp_staging_table.sql`

(Similar structure to AWS - abbreviated for brevity, full DDL in actual files)

#### **Task 2.4: Create Partition Management Function**

**File**: `koku/masu/database/sql/006_create_partition_management.sql`

```sql
-- Automatic partition creation function
CREATE OR REPLACE FUNCTION create_staging_partition(
    p_table_name TEXT,
    p_partition_date DATE
) RETURNS TEXT AS $$
DECLARE
    v_partition_name TEXT;
    v_start_date DATE;
    v_end_date DATE;
    v_sql TEXT;
BEGIN
    -- Calculate partition boundaries (monthly partitions)
    v_start_date := date_trunc('month', p_partition_date)::date;
    v_end_date := (v_start_date + INTERVAL '1 month')::date;

    -- Generate partition name (format: tablename_YYYY_MM)
    v_partition_name := format(
        '%s_%s',
        p_table_name,
        to_char(v_start_date, 'YYYY_MM')
    );

    -- Check if partition already exists
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = v_partition_name
    ) THEN
        RAISE NOTICE 'Partition already exists: %', v_partition_name;
        RETURN v_partition_name;
    END IF;

    -- Create partition
    v_sql := format(
        'CREATE TABLE IF NOT EXISTS public.%I
         PARTITION OF public.%I
         FOR VALUES FROM (%L) TO (%L)',
        v_partition_name,
        p_table_name,
        v_start_date,
        v_end_date
    );

    EXECUTE v_sql;

    RAISE NOTICE 'Created partition: %', v_partition_name;
    RETURN v_partition_name;
END;
$$ LANGUAGE plpgsql;

-- Function to create partitions for next N months
CREATE OR REPLACE FUNCTION create_future_partitions(
    p_table_name TEXT,
    p_months_ahead INTEGER DEFAULT 3
) RETURNS INTEGER AS $$
DECLARE
    v_current_date DATE := CURRENT_DATE;
    v_partition_date DATE;
    v_count INTEGER := 0;
    v_partition_name TEXT;
BEGIN
    -- Create partitions for current month + N months ahead
    FOR i IN 0..p_months_ahead LOOP
        v_partition_date := v_current_date + (i || ' months')::INTERVAL;
        v_partition_name := create_staging_partition(p_table_name, v_partition_date);
        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Create future partitions for all staging tables
SELECT create_future_partitions('aws_line_items_daily_staging', 3);
SELECT create_future_partitions('azure_line_items_daily_staging', 3);
SELECT create_future_partitions('gcp_line_items_daily_staging', 3);
SELECT create_future_partitions('openshift_pod_usage_line_items_daily', 3);
```

#### **Task 2.5: Deploy All Staging Tables**

```bash
# Deploy all staging table DDL scripts
cd koku/masu/database/sql

psql -h localhost -U koku -d koku -f 001_create_tenants_table.sql
psql -h localhost -U koku -d koku -f 002_create_aws_staging_table.sql
psql -h localhost -U koku -d koku -f 003_create_azure_staging_table.sql
psql -h localhost -U koku -d koku -f 004_create_gcp_staging_table.sql
psql -h localhost -U koku -d koku -f 005_create_ocp_staging_table.sql
psql -h localhost -U koku -d koku -f 006_create_partition_management.sql

# Verify tables created
psql -h localhost -U koku -d koku -c "
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
    AND tablename LIKE '%staging%'
ORDER BY tablename;
"
```

**Checkpoint**: ✅ All staging tables created with partitions and indexes

---

### **Day 3: Custom PostgreSQL Functions Deployment**

**Deliverable**: 5 custom functions deployed and tested

#### **Task 3.1: Create Custom Functions SQL File**

**File**: `koku/masu/database/sql/007_create_custom_functions.sql`

```sql
-- ============================================================================
-- PostgreSQL Custom Functions for Trino Replacement
-- ============================================================================
-- Purpose: Provide PostgreSQL equivalents for Trino-specific functions
-- Author: Koku Development Team
-- Date: November 2025
-- ============================================================================

-- Function 1: filter_json_by_keys
-- Replaces: Trino's map_filter() function
-- ============================================================================
CREATE OR REPLACE FUNCTION filter_json_by_keys(
    tags_json JSONB,
    enabled_keys TEXT[]
) RETURNS JSONB AS $$
DECLARE
    result JSONB := '{}';
    tag_key TEXT;
    tag_value TEXT;
BEGIN
    -- Handle NULL or empty input
    IF tags_json IS NULL OR tags_json = 'null'::jsonb OR tags_json = '{}'::jsonb THEN
        RETURN NULL;
    END IF;

    IF enabled_keys IS NULL OR array_length(enabled_keys, 1) IS NULL THEN
        RETURN NULL;
    END IF;

    -- Iterate through JSON keys and filter
    FOR tag_key, tag_value IN
        SELECT * FROM jsonb_each_text(tags_json)
    LOOP
        IF tag_key = ANY(enabled_keys) THEN
            result := result || jsonb_build_object(tag_key, tag_value);
        END IF;
    END LOOP;

    -- Return NULL if no keys matched
    IF result = '{}'::jsonb THEN
        RETURN NULL;
    END IF;

    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION filter_json_by_keys IS
'Filter JSONB object to only include keys in enabled_keys array. Replaces Trino map_filter().';

-- Function 2: any_key_in_string
-- Replaces: Trino's any_match() with strpos()
-- ============================================================================
CREATE OR REPLACE FUNCTION any_key_in_string(
    keys TEXT[],
    search_string TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    IF keys IS NULL OR search_string IS NULL THEN
        RETURN FALSE;
    END IF;

    RETURN EXISTS (
        SELECT 1 FROM unnest(keys) AS key
        WHERE position(key IN search_string) > 0
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION any_key_in_string IS
'Check if any key from array exists in search string. Replaces Trino any_match() with strpos().';

-- Function 3: json_format_safe
-- Replaces: Trino's json_format() function
-- ============================================================================
CREATE OR REPLACE FUNCTION json_format_safe(
    input_json JSONB
) RETURNS TEXT AS $$
BEGIN
    IF input_json IS NULL OR input_json = 'null'::jsonb THEN
        RETURN NULL;
    END IF;

    RETURN input_json::text;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION json_format_safe IS
'Convert JSONB to formatted JSON string. Replaces Trino json_format().';

-- Function 4: array_union_safe
-- Replaces: Trino's array_union() function
-- ============================================================================
CREATE OR REPLACE FUNCTION array_union_safe(
    array1 TEXT[],
    array2 TEXT[]
) RETURNS TEXT[] AS $$
BEGIN
    IF array1 IS NULL AND array2 IS NULL THEN
        RETURN NULL;
    END IF;

    IF array1 IS NULL THEN
        RETURN array2;
    END IF;

    IF array2 IS NULL THEN
        RETURN array1;
    END IF;

    -- Union arrays and remove duplicates
    RETURN ARRAY(
        SELECT DISTINCT unnest(array1 || array2)
        ORDER BY 1
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION array_union_safe IS
'Union two arrays, removing duplicates. Replaces Trino array_union().';

-- Function 5: generate_uuid_v4 (wrapper for compatibility)
-- Replaces: Trino's uuid() function
-- ============================================================================
CREATE OR REPLACE FUNCTION generate_uuid_v4()
RETURNS UUID AS $$
BEGIN
    -- PostgreSQL 13+ has gen_random_uuid() built-in
    -- Fall back to uuid-ossp extension for older versions
    BEGIN
        RETURN gen_random_uuid();
    EXCEPTION WHEN undefined_function THEN
        RETURN uuid_generate_v4();
    END;
END;
$$ LANGUAGE plpgsql VOLATILE;

COMMENT ON FUNCTION generate_uuid_v4 IS
'Generate UUID v4. Replaces Trino uuid() function.';

-- ============================================================================
-- Verification Query
-- ============================================================================
SELECT
    routine_name,
    routine_type,
    data_type as return_type,
    routine_definition IS NOT NULL as has_definition
FROM information_schema.routines
WHERE routine_schema = 'public'
    AND routine_name IN (
        'filter_json_by_keys',
        'any_key_in_string',
        'json_format_safe',
        'array_union_safe',
        'generate_uuid_v4'
    )
ORDER BY routine_name;
```

#### **Task 3.2: Deploy and Test Custom Functions**

```bash
# Deploy custom functions
psql -h localhost -U koku -d koku -f koku/masu/database/sql/007_create_custom_functions.sql

# Test each function
psql -h localhost -U koku -d koku << 'EOF'
-- Test 1: filter_json_by_keys
SELECT filter_json_by_keys(
    '{"app": "frontend", "env": "prod", "internal": "true"}'::jsonb,
    ARRAY['app', 'env']
) AS filtered_tags;
-- Expected: {"app": "frontend", "env": "prod"}

-- Test 2: any_key_in_string
SELECT any_key_in_string(
    ARRAY['app', 'env', 'team'],
    '{"app": "frontend", "version": "1.0"}'
) AS key_found;
-- Expected: true

-- Test 3: json_format_safe
SELECT json_format_safe('{"key": "value"}'::jsonb) AS formatted;
-- Expected: {"key": "value"}

-- Test 4: array_union_safe
SELECT array_union_safe(
    ARRAY['a', 'b', 'c'],
    ARRAY['b', 'c', 'd']
) AS union_result;
-- Expected: {a,b,c,d}

-- Test 5: generate_uuid_v4
SELECT generate_uuid_v4() AS new_uuid;
-- Expected: UUID like 123e4567-e89b-12d3-a456-426614174000
EOF
```

**Checkpoint**: ✅ All 5 custom functions deployed and tested

---

### **Day 4: Python Helpers + CSV Loading Logic**

**Deliverable**: CSV direct loading working for all providers

#### **Task 4.1: Create Python Helper Module**

**File**: `koku/masu/database/postgresql_helpers.py`

```python
"""
PostgreSQL Helper Functions
===========================
Purpose: Python utilities for PostgreSQL-only queries
"""

import json
import logging
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)


def filter_tags_for_enabled_keys(
    tags_dict: Dict[str, str],
    enabled_keys: List[str]
) -> Dict[str, str]:
    """
    Filter tags dictionary to only include enabled keys.

    Python implementation of filter_json_by_keys PostgreSQL function.
    Use when processing data in Python before inserting into PostgreSQL.

    Args:
        tags_dict: Dictionary of tag key-value pairs
        enabled_keys: List of keys to keep

    Returns:
        Filtered dictionary containing only enabled keys
    """
    if not tags_dict or not enabled_keys:
        return {}

    return {k: v for k, v in tags_dict.items() if k in enabled_keys}


def any_key_in_string(keys: List[str], search_string: str) -> bool:
    """Check if any key from list exists in search string."""
    if not keys or not search_string:
        return False

    return any(key in search_string for key in keys)


def safe_json_loads(json_string: Optional[str], default: Any = None) -> Any:
    """Safely load JSON string, returning default value on error."""
    if not json_string or json_string in ('null', 'NULL', ''):
        return default

    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        LOG.warning(f"Failed to parse JSON: {e}. Returning default value.")
        return default


def safe_json_dumps(obj: Any, default: str = '{}') -> str:
    """Safely dump object to JSON string, returning default on error."""
    if obj is None:
        return default

    try:
        return json.dumps(obj)
    except (TypeError, ValueError) as e:
        LOG.warning(f"Failed to serialize to JSON: {e}. Returning default value.")
        return default
```

#### **Task 4.2: Create CSV Direct Loader**

**File**: `koku/masu/processor/csv_loader.py`

```python
"""
CSV Direct Loader for PostgreSQL
=================================
Purpose: Load CSV files directly into PostgreSQL staging tables
Replaces: ParquetReportProcessor + Hive table creation
"""

import csv
import logging
import os
from typing import Dict, List, Optional
from django.db import connection
from django.conf import settings

LOG = logging.getLogger(__name__)


class CSVDirectLoader:
    """Load CSV files directly into PostgreSQL staging tables"""

    # Map provider types to table names
    TABLE_MAP = {
        'AWS': 'aws_line_items_daily_staging',
        'AZURE': 'azure_line_items_daily_staging',
        'GCP': 'gcp_line_items_daily_staging',
        'OCP': 'openshift_pod_usage_line_items_daily'
    }

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
        self.table_name = self.TABLE_MAP.get(self.provider_type)

        if not self.table_name:
            raise ValueError(f"Invalid provider type: {provider_type}")

    def load_csv_file(self, csv_file_path: str, year: str, month: str) -> int:
        """
        Load CSV file directly into PostgreSQL staging table.

        Args:
            csv_file_path: Path to CSV file
            year: Year (YYYY)
            month: Month (MM)

        Returns:
            Number of rows loaded
        """
        if not os.path.exists(csv_file_path):
            raise FileNotFoundError(f"CSV file not found: {csv_file_path}")

        LOG.info(f"Loading CSV: {csv_file_path} → {self.table_name}")

        # Ensure partition exists
        self._ensure_partition_exists(year, month)

        # Load CSV using PostgreSQL COPY
        row_count = self._copy_csv_to_table(csv_file_path, year, month)

        LOG.info(f"✅ Loaded {row_count} rows from {csv_file_path}")

        return row_count

    def _ensure_partition_exists(self, year: str, month: str):
        """Ensure partition exists for the given year/month"""
        partition_date = f"{year}-{month}-01"

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT create_staging_partition(%s, %s::date)",
                [self.table_name, partition_date]
            )
            LOG.debug(f"Partition ensured for {partition_date}")

    def _copy_csv_to_table(self, csv_file_path: str, year: str, month: str) -> int:
        """
        Use PostgreSQL COPY command to load CSV.

        This is the fastest way to load data into PostgreSQL.
        """
        # Read CSV header to get column names
        with open(csv_file_path, 'r') as f:
            reader = csv.reader(f)
            csv_columns = next(reader)  # First row is header

        # Map CSV columns to table columns
        table_columns = self._map_csv_columns_to_table(csv_columns)

        # Build COPY command
        copy_sql = f"""
            COPY public.{self.table_name} (
                tenant_id,
                source,
                year,
                month,
                {', '.join(table_columns)}
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

        # Execute COPY with file
        with connection.cursor() as cursor:
            with open(csv_file_path, 'r') as f:
                # Add metadata columns to each row
                cursor.copy_expert(copy_sql, f)
                row_count = cursor.rowcount

        return row_count

    def _map_csv_columns_to_table(self, csv_columns: List[str]) -> List[str]:
        """
        Map CSV column names to table column names.

        AWS CUR columns use different naming conventions than our tables.
        """
        # Column mapping for each provider
        # (This would be a comprehensive mapping in production)

        if self.provider_type == 'AWS':
            # AWS CUR uses format: bill/BillingEntity → bill_billingentity
            return [col.lower().replace('/', '_') for col in csv_columns]

        elif self.provider_type == 'AZURE':
            # Azure uses PascalCase → snake_case
            return [self._pascal_to_snake(col) for col in csv_columns]

        elif self.provider_type == 'GCP':
            # GCP uses snake_case already
            return csv_columns

        elif self.provider_type == 'OCP':
            # OCP uses snake_case already
            return csv_columns

        return csv_columns

    @staticmethod
    def _pascal_to_snake(name: str) -> str:
        """Convert PascalCase to snake_case"""
        import re
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


# Integration with MASU processor
def process_csv_report(
    tenant_id: int,
    source_uuid: str,
    provider_type: str,
    csv_file_path: str,
    year: str,
    month: str
) -> int:
    """
    Process CSV report by loading directly into PostgreSQL.

    This replaces the old flow:
        CSV → Parquet → S3 → Hive → Trino → PostgreSQL

    With new flow:
        CSV → PostgreSQL (direct)
    """
    loader = CSVDirectLoader(tenant_id, source_uuid, provider_type)
    row_count = loader.load_csv_file(csv_file_path, year, month)

    LOG.info(f"✅ Processed {row_count} rows for {provider_type} source {source_uuid}")

    return row_count
```

#### **Task 4.3: Create Unit Tests for CSV Loader**

**File**: `koku/masu/processor/test/test_csv_loader.py`

```python
"""Unit tests for CSV Direct Loader"""

import os
import tempfile
from django.test import TestCase
from koku.masu.processor.csv_loader import CSVDirectLoader


class TestCSVDirectLoader(TestCase):
    """Test CSV direct loading functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.tenant_id = 1
        self.source_uuid = '12345678-1234-1234-1234-123456789012'

        # Create test CSV file
        self.test_csv = self._create_test_csv()

    def _create_test_csv(self):
        """Create a test CSV file with sample data"""
        csv_content = """bill/BillingEntity,lineItem/UsageStartDate,lineItem/UsageAmount,lineItem/UnblendedCost
AWS,2025-11-01 00:00:00,100.5,50.25
AWS,2025-11-01 01:00:00,200.0,100.50
"""

        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            f.write(csv_content)
            return f.name

    def tearDown(self):
        """Clean up test files"""
        if os.path.exists(self.test_csv):
            os.remove(self.test_csv)

    def test_csv_loader_initialization(self):
        """Test CSV loader initializes correctly"""
        loader = CSVDirectLoader(self.tenant_id, self.source_uuid, 'AWS')

        self.assertEqual(loader.tenant_id, self.tenant_id)
        self.assertEqual(loader.source_uuid, self.source_uuid)
        self.assertEqual(loader.provider_type, 'AWS')
        self.assertEqual(loader.table_name, 'aws_line_items_daily_staging')

    def test_invalid_provider_type(self):
        """Test that invalid provider type raises error"""
        with self.assertRaises(ValueError):
            CSVDirectLoader(self.tenant_id, self.source_uuid, 'INVALID')

    def test_load_csv_file(self):
        """Test CSV file loading"""
        loader = CSVDirectLoader(self.tenant_id, self.source_uuid, 'AWS')

        # Load test CSV
        row_count = loader.load_csv_file(self.test_csv, '2025', '11')

        # Verify rows were loaded
        self.assertEqual(row_count, 2)
```

**Checkpoint**: ✅ CSV direct loading working with tests passing

---

### **Day 5: Feature Flag + Accessor Refactoring**

**Deliverable**: Feature flag working, accessor methods updated

#### **Task 5.1: Add Feature Flag to Settings**

**File**: `koku/koku/settings.py`

```python
# Add to settings.py

# ============================================================================
# Trino to PostgreSQL Migration Feature Flag
# ============================================================================
# Set to True to use PostgreSQL-only queries (new architecture)
# Set to False to use Trino queries (legacy architecture, for rollback)
USE_POSTGRESQL_ONLY = os.environ.get('USE_POSTGRESQL_ONLY', 'True').lower() == 'true'

# Log feature flag status
if USE_POSTGRESQL_ONLY:
    LOG.info("✅ PostgreSQL-only mode ENABLED (Trino disabled)")
else:
    LOG.warning("⚠️  Trino mode ENABLED (PostgreSQL-only disabled)")
```

#### **Task 5.2: Refactor Report DB Accessor Base**

**File**: `koku/masu/database/report_db_accessor_base.py`

Add these methods to the `ReportDBAccessorBase` class:

```python
# Add to ReportDBAccessorBase class

@staticmethod
def use_postgresql_only():
    """Check if PostgreSQL-only mode is enabled."""
    return getattr(settings, 'USE_POSTGRESQL_ONLY', True)

def _execute_postgresql_raw_sql_query(
    self, sql, *, sql_params=None, context=None, log_ref=None
):
    """
    Execute a PostgreSQL query (replaces _execute_trino_raw_sql_query).

    This method is used when USE_POSTGRESQL_ONLY feature flag is enabled.
    """
    if sql_params is None:
        sql_params = {}
    if context is None:
        context = {}
    if log_ref is None:
        log_ref = "PostgreSQL query"

    # Extract context for logging
    if sql_params:
        ctx = self.extract_context_from_sql_params(sql_params)
    elif context:
        ctx = self.extract_context_from_sql_params(context)
    else:
        ctx = {}

    # Prepare SQL with Jinja2 templating
    sql, bind_params = self.prepare_query(sql, sql_params)

    # Execute query
    LOG.info(log_json(msg="executing postgresql sql", log_ref=log_ref, context=ctx))
    t1 = time.time()

    try:
        with connection.cursor() as cursor:
            cursor.db.set_schema(self.schema)
            cursor.execute(sql, params=bind_params)
            results = cursor.fetchall()
            row_count = cursor.rowcount

        running_time = time.time() - t1
        LOG.info(log_json(
            msg=f"finished {log_ref}",
            row_count=row_count,
            running_time=running_time,
            context=ctx
        ))

        return results

    except OperationalError as exc:
        db_exc = get_extended_exception_by_type(exc)
        LOG.error(log_json(
            msg=f"PostgreSQL query failed: {str(db_exc)}",
            context=db_exc.as_dict()
        ))
        raise db_exc from exc

def _execute_query_with_fallback(
    self, sql, *, sql_params=None, context=None, log_ref=None
):
    """
    Execute query using PostgreSQL or Trino based on feature flag.

    This method checks the USE_POSTGRESQL_ONLY feature flag and routes
    to the appropriate execution method.
    """
    if self.use_postgresql_only():
        return self._execute_postgresql_raw_sql_query(
            sql, sql_params=sql_params, context=context, log_ref=log_ref
        )
    else:
        return self._execute_trino_raw_sql_query(
            sql, sql_params=sql_params, context=context, log_ref=log_ref
        )
```

#### **Task 5.3: Test Feature Flag**

```python
# Test feature flag in Django shell
python manage.py shell

>>> from django.conf import settings
>>> from koku.masu.database.report_db_accessor_base import ReportDBAccessorBase
>>>
>>> # Check feature flag
>>> print(f"USE_POSTGRESQL_ONLY: {settings.USE_POSTGRESQL_ONLY}")
>>> print(f"use_postgresql_only(): {ReportDBAccessorBase.use_postgresql_only()}")
>>>
>>> # Test accessor initialization
>>> accessor = ReportDBAccessorBase('org1234567')
>>> print(f"Schema: {accessor.schema}")
```

**Checkpoint**: ✅ Feature flag working, accessor methods ready

---

## 📊 Week 1 Summary

**Completed**:
- ✅ PostgreSQL 16 deployed with extensions
- ✅ All staging tables created with partitioning
- ✅ 5 custom PostgreSQL functions deployed
- ✅ CSV direct loader implemented
- ✅ Feature flag configured
- ✅ Accessor base class refactored

**Ready for Week 2**: Core SQL migration

---

---

## 📝 Phase 2: Core SQL Migration (Week 2, Days 6-10)

### **Day 6: AWS Daily Summary Migration**

**Deliverable**: AWS daily summary query migrated and tested

#### **Task 6.1: Create PostgreSQL SQL Directory Structure**

```bash
# Create directory for PostgreSQL SQL files
mkdir -p koku/masu/database/postgresql_sql
mkdir -p koku/masu/database/postgresql_sql/aws
mkdir -p koku/masu/database/postgresql_sql/azure
mkdir -p koku/masu/database/postgresql_sql/gcp
mkdir -p koku/masu/database/postgresql_sql/openshift
```

#### **Task 6.2: Migrate AWS Daily Summary SQL**

**File**: `koku/masu/database/postgresql_sql/reporting_awscostentrylineitem_daily_summary.sql`

```sql
-- ============================================================================
-- AWS Cost Entry Line Item Daily Summary (PostgreSQL Version)
-- ============================================================================
-- Migrated from: trino_sql/reporting_awscostentrylineitem_daily_summary.sql
-- Changes:
--   1. Replaced uuid() with gen_random_uuid()
--   2. Replaced map_filter + json_parse with filter_json_by_keys
--   3. Replaced json_parse with ::jsonb casting
--   4. Replaced date_add with INTERVAL arithmetic
--   5. Removed cross-catalog prefixes (hive., postgres.)
--   6. Changed source table to staging table
-- ============================================================================

INSERT INTO {{schema | sqlsafe}}.reporting_awscostentrylineitem_daily_summary (
    uuid,
    cost_entry_bill_id,
    usage_start,
    usage_end,
    usage_account_id,
    product_code,
    product_family,
    availability_zone,
    region,
    instance_type,
    unit,
    resource_ids,
    resource_count,
    usage_amount,
    normalization_factor,
    normalized_usage_amount,
    currency_code,
    unblended_rate,
    unblended_cost,
    blended_rate,
    blended_cost,
    savingsplan_effective_cost,
    calculated_amortized_cost,
    public_on_demand_cost,
    public_on_demand_rate,
    tags,
    cost_category,
    account_alias_id,
    organizational_unit_id,
    source_uuid,
    markup_cost,
    markup_cost_blended,
    markup_cost_savingsplan,
    markup_cost_amortized
)
WITH cte_pg_enabled_keys AS (
    SELECT array_agg(key ORDER BY key) AS keys
    FROM {{schema | sqlsafe}}.reporting_enabledtagkeys
    WHERE enabled = true
        AND provider_type = 'AWS'
)
SELECT
    gen_random_uuid() AS uuid,  -- CHANGE 1: uuid() → gen_random_uuid()
    {{bill_id | sqlsafe}}::integer AS cost_entry_bill_id,
    usage_start,
    usage_end,
    usage_account_id::varchar(50),
    product_code::varchar,
    product_family,
    availability_zone::varchar(50),
    region,
    instance_type,
    unit,
    resource_ids,
    resource_count,
    usage_amount::decimal(24,9),
    normalization_factor,
    normalized_usage_amount,
    currency_code::varchar(10),
    unblended_rate::decimal(24,9),
    unblended_cost::decimal(24,9),
    blended_rate::decimal(24,9),
    blended_cost::decimal(24,9),
    savingsplan_effective_cost::decimal(24,9),
    calculated_amortized_cost::decimal(33, 9),
    public_on_demand_cost::decimal(24,9),
    public_on_demand_rate::decimal(24,9),

    -- CHANGE 2: map_filter + json_parse → filter_json_by_keys
    CASE
        WHEN tags IS NOT NULL AND tags != '{}' AND tags != 'null' THEN
            filter_json_by_keys(tags::jsonb, pek.keys)
        ELSE NULL
    END AS tags,

    -- CHANGE 3: json_parse → ::jsonb casting
    CASE
        WHEN costcategory IS NOT NULL AND costcategory != '{}' AND costcategory != 'null' THEN
            costcategory::jsonb
        ELSE NULL
    END AS cost_category,

    aa.id AS account_alias_id,
    ou.id AS organizational_unit_id,
    '{{source_uuid | sqlsafe}}'::uuid AS source_uuid,
    (unblended_cost * {{markup | sqlsafe}})::decimal(24,9) AS markup_cost,
    (blended_cost * {{markup | sqlsafe}})::decimal(33,15) AS markup_cost_blended,
    (savingsplan_effective_cost * {{markup | sqlsafe}})::decimal(33,15) AS markup_cost_savingsplan,
    (calculated_amortized_cost * {{markup | sqlsafe}})::decimal(33,9) AS markup_cost_amortized
FROM (
    SELECT
        lineitem_usagestartdate::date AS usage_start,
        lineitem_usagestartdate::date AS usage_end,
        CASE
            WHEN bill_billingentity='AWS Marketplace' THEN
                coalesce(nullif(product_productname, ''), nullif(lineitem_productcode, ''))
            ELSE nullif(lineitem_productcode, '')
        END AS product_code,
        nullif(product_productfamily, '') AS product_family,
        lineitem_usageaccountid AS usage_account_id,
        nullif(lineitem_availabilityzone, '') AS availability_zone,
        nullif(product_region, '') AS region,
        resourcetags AS tags,
        costcategory,
        nullif(product_instancetype, '') AS instance_type,
        nullif(pricing_unit, '') AS unit,
        -- SavingsPlanNegation needs to be negated to prevent duplicate usage COST-5369
        sum(
            CASE
                WHEN lineitem_lineitemtype='SavingsPlanNegation'
                THEN 0.0
                ELSE lineitem_usageamount
            END
        ) AS usage_amount,
        max(lineitem_normalizationfactor) AS normalization_factor,
        sum(lineitem_normalizedusageamount) AS normalized_usage_amount,
        max(lineitem_currencycode) AS currency_code,
        max(lineitem_unblendedrate) AS unblended_rate,
        sum(lineitem_unblendedcost) AS unblended_cost,
        max(lineitem_blendedrate) AS blended_rate,
        sum(lineitem_blendedcost) AS blended_cost,
        sum(savingsplan_savingsplaneffectivecost) AS savingsplan_effective_cost,
        sum(
            CASE
                WHEN lineitem_lineitemtype='SavingsPlanCoveredUsage'
                OR lineitem_lineitemtype='SavingsPlanNegation'
                OR lineitem_lineitemtype='SavingsPlanUpfrontFee'
                OR lineitem_lineitemtype='SavingsPlanRecurringFee'
                THEN savingsplan_savingsplaneffectivecost
                ELSE lineitem_unblendedcost
            END
        ) AS calculated_amortized_cost,
        sum(pricing_publicondemandcost) AS public_on_demand_cost,
        max(pricing_publicondemandrate) AS public_on_demand_rate,
        array_agg(DISTINCT lineitem_resourceid) AS resource_ids,
        count(DISTINCT lineitem_resourceid) AS resource_count

    -- CHANGE 4: hive.schema.table → public.table_staging
    FROM public.aws_line_items_daily_staging

    WHERE tenant_id = (SELECT id FROM public.tenants WHERE schema_name = '{{schema | sqlsafe}}')
        AND source = '{{source_uuid | sqlsafe}}'::uuid
        AND year = '{{year | sqlsafe}}'
        AND month = '{{month | sqlsafe}}'
        AND lineitem_usagestartdate >= '{{start_date | sqlsafe}}'::timestamp

        -- CHANGE 5: date_add → INTERVAL arithmetic
        AND lineitem_usagestartdate < ('{{end_date | sqlsafe}}'::timestamp + INTERVAL '1 day')

    GROUP BY
        lineitem_usagestartdate::date,
        bill_billingentity,
        lineitem_productcode,
        product_productname,
        lineitem_usageaccountid,
        lineitem_availabilityzone,
        product_productfamily,
        product_region,
        resourcetags,
        costcategory,
        product_instancetype,
        pricing_unit
) AS ds
CROSS JOIN cte_pg_enabled_keys AS pek

-- CHANGE 6: postgres.schema.table → schema.table
LEFT JOIN {{schema | sqlsafe}}.reporting_awsaccountalias AS aa
    ON ds.usage_account_id = aa.account_id
LEFT JOIN {{schema | sqlsafe}}.reporting_awsorganizationalunit AS ou
    ON aa.id = ou.account_alias_id
        AND ou.provider_id = '{{source_uuid | sqlsafe}}'::uuid
        AND ou.created_timestamp <= ds.usage_start
        AND (
            ou.deleted_timestamp IS NULL
            OR ou.deleted_timestamp > ds.usage_start
        );
```

#### **Task 6.3: Update AWS Report DB Accessor**

**File**: `koku/masu/database/aws_report_db_accessor.py`

Find the `populate_line_item_daily_summary_table` method and update it:

```python
def populate_line_item_daily_summary_table(self, start_date, end_date, bill_id, markup_value):
    """Populate the daily summary table."""

    # Determine which SQL file to use based on feature flag
    if self.use_postgresql_only():
        sql_file = "postgresql_sql/reporting_awscostentrylineitem_daily_summary.sql"
        log_ref = "AWS daily summary (PostgreSQL)"
    else:
        sql_file = "trino_sql/reporting_awscostentrylineitem_daily_summary.sql"
        log_ref = "AWS daily summary (Trino)"

    # Load SQL template
    sql = pkgutil.get_data("masu.database", sql_file)
    sql = sql.decode("utf-8")

    # Prepare parameters
    sql_params = {
        "schema": self.schema,
        "bill_id": bill_id,
        "source_uuid": str(self.provider_uuid),
        "year": start_date.strftime("%Y"),
        "month": start_date.strftime("%m"),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "markup": markup_value
    }

    # Execute query using appropriate method
    return self._execute_query_with_fallback(
        sql,
        sql_params=sql_params,
        log_ref=log_ref
    )
```

#### **Task 6.4: Create Unit Test**

**File**: `koku/masu/database/test/test_aws_postgresql_migration.py`

```python
"""Unit tests for AWS PostgreSQL SQL migration"""

import pytest
from django.test import TestCase
from django.conf import settings
from koku.masu.database.aws_report_db_accessor import AWSReportDBAccessor


class TestAWSPostgreSQLMigration(TestCase):
    """Test AWS SQL migration to PostgreSQL"""

    def setUp(self):
        """Set up test fixtures"""
        self.schema = "org1234567"
        self.accessor = AWSReportDBAccessor(self.schema)

        # Ensure PostgreSQL-only mode
        settings.USE_POSTGRESQL_ONLY = True

    def test_sql_file_loads(self):
        """Test that PostgreSQL SQL file loads without errors"""
        import pkgutil

        sql = pkgutil.get_data(
            "masu.database",
            "postgresql_sql/reporting_awscostentrylineitem_daily_summary.sql"
        )
        sql = sql.decode("utf-8")

        # Verify key PostgreSQL syntax
        assert "gen_random_uuid()" in sql
        assert "filter_json_by_keys" in sql
        assert "::jsonb" in sql
        assert "INTERVAL '1 day'" in sql

        # Verify no Trino syntax
        assert "uuid()" not in sql
        assert "map_filter(" not in sql
        assert "json_parse(" not in sql
        assert "date_add(" not in sql
        assert "hive." not in sql

    def test_query_prepares_correctly(self):
        """Test that query prepares with Jinja2 parameters"""
        import pkgutil

        sql = pkgutil.get_data(
            "masu.database",
            "postgresql_sql/reporting_awscostentrylineitem_daily_summary.sql"
        )
        sql = sql.decode("utf-8")

        sql_params = {
            "schema": self.schema,
            "bill_id": 123,
            "source_uuid": "12345678-1234-1234-1234-123456789012",
            "year": "2025",
            "month": "11",
            "start_date": "2025-11-01",
            "end_date": "2025-11-30",
            "markup": 1.0
        }

        # Prepare query
        prepared_sql, bind_params = self.accessor.prepare_query(sql, sql_params)

        # Verify parameters were substituted
        assert "org1234567" in prepared_sql
        assert "2025" in prepared_sql
        assert "11" in prepared_sql
```

**Run Tests**:
```bash
cd koku
python manage.py test masu.database.test.test_aws_postgresql_migration -v 2
```

**Checkpoint**: ✅ AWS daily summary migrated and tested

---

### **Day 7: Azure Daily Summary Migration**

**Deliverable**: Azure daily summary query migrated and tested

#### **Task 7.1: Migrate Azure Daily Summary SQL**

**File**: `koku/masu/database/postgresql_sql/reporting_azurecostentrylineitem_daily_summary.sql`

(Similar structure to AWS - follow same pattern)

Key changes:
- `uuid()` → `gen_random_uuid()`
- `map_filter(json_parse(tags), ...)` → `filter_json_by_keys(tags::jsonb, ...)`
- `date_add('day', 1, date)` → `date + INTERVAL '1 day'`
- `hive.schema.azure_line_items_daily` → `public.azure_line_items_daily_staging`
- Add `tenant_id` filter

#### **Task 7.2: Update Azure Report DB Accessor**

Similar to AWS accessor update.

#### **Task 7.3: Create Unit Test**

Similar to AWS test.

**Checkpoint**: ✅ Azure daily summary migrated and tested

---

### **Day 8: GCP Daily Summary Migration**

**Deliverable**: GCP daily summary query migrated and tested

(Follow same pattern as AWS/Azure)

**Checkpoint**: ✅ GCP daily summary migrated and tested

---

### **Day 9: OCP Daily Summary Migration**

**Deliverable**: OCP daily summary query migrated and tested

(Follow same pattern as AWS/Azure/GCP)

**Checkpoint**: ✅ OCP daily summary migrated and tested

---

### **Day 10: Tag Matching Queries (AWS/Azure)**

**Deliverable**: Tag matching queries migrated and tested

#### **Task 10.1: Migrate AWS Tag Matching SQL**

**File**: `koku/masu/database/postgresql_sql/reporting_ocpaws_matched_tags.sql`

Key Trino functions to replace:
- `unnest(cast(json_parse(resourcetags) as map(...)))` → `LATERAL jsonb_each_text(resourcetags::jsonb)`
- `any_match(key_array, x->strpos(...))` → `any_key_in_string(key_array, ...)`
- `lpad(month, 2, '0')` → `lpad(month::text, 2, '0')`
- `date_add('day', 1, date)` → `date + INTERVAL '1 day'`

#### **Task 10.2: Migrate Azure Tag Matching SQL**

Similar to AWS tag matching.

**Checkpoint**: ✅ Tag matching queries migrated and tested

---

## 📊 Week 2 Summary

**Completed**:
- ✅ AWS daily summary migrated
- ✅ Azure daily summary migrated
- ✅ GCP daily summary migrated
- ✅ OCP daily summary migrated
- ✅ AWS/Azure tag matching migrated
- ✅ All queries tested with unit tests

**Progress**: 10/60 SQL files migrated (17%)

**Ready for Week 3**: OCP-on-Cloud integration queries

---

## 🐳 Docker Compose Development Environment

### **Docker Compose Configuration**

**File**: `docker-compose.dev.yml`

```yaml
version: '3.8'

services:
  # PostgreSQL 16 Database
  postgres:
    image: registry.redhat.io/rhel10/postgresql-16@sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1
    container_name: koku-postgres-dev
    environment:
      POSTGRESQL_USER: koku
      POSTGRESQL_PASSWORD: koku
      POSTGRESQL_DATABASE: koku
      POSTGRESQL_ADMIN_PASSWORD: admin
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./koku/masu/database/sql:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U koku"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - koku-network

  # Koku API (Reads)
  koku-api-reads:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: koku-api-reads-dev
    environment:
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=koku
      - DATABASE_USER=koku
      - DATABASE_PASSWORD=koku
      - USE_POSTGRESQL_ONLY=true
      - DEVELOPMENT=true
      - MASU=false
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./koku:/opt/koku
    command: >
      bash -c "
        mkdir -p /tmp/prometheus &&
        python manage.py migrate &&
        python manage.py runserver 0.0.0.0:8000
      "
    networks:
      - koku-network

  # Koku API (Writes)
  koku-api-writes:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: koku-api-writes-dev
    environment:
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=koku
      - DATABASE_USER=koku
      - DATABASE_PASSWORD=koku
      - USE_POSTGRESQL_ONLY=true
      - DEVELOPMENT=true
      - MASU=false
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    ports:
      - "8001:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./koku:/opt/koku
    command: >
      bash -c "
        mkdir -p /tmp/prometheus &&
        python manage.py runserver 0.0.0.0:8000
      "
    networks:
      - koku-network

  # MASU (Data Processing)
  koku-masu:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: koku-masu-dev
    environment:
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=koku
      - DATABASE_USER=koku
      - DATABASE_PASSWORD=koku
      - USE_POSTGRESQL_ONLY=true
      - DEVELOPMENT=true
      - MASU=true
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./koku:/opt/koku
      - ./test-data:/tmp/test-data:ro
    command: >
      bash -c "
        mkdir -p /tmp/prometheus &&
        python manage.py run_masu
      "
    networks:
      - koku-network

  # Celery Worker
  koku-celery-worker:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: koku-celery-worker-dev
    environment:
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=koku
      - DATABASE_USER=koku
      - DATABASE_PASSWORD=koku
      - USE_POSTGRESQL_ONLY=true
      - DEVELOPMENT=true
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
      - CELERY_BROKER=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - ./koku:/opt/koku
    command: >
      bash -c "
        mkdir -p /tmp/prometheus &&
        celery -A koku worker -l info
      "
    networks:
      - koku-network

  # Redis (for Celery)
  redis:
    image: redis:7-alpine
    container_name: koku-redis-dev
    ports:
      - "6379:6379"
    networks:
      - koku-network

  # pgAdmin (Database Management UI)
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: koku-pgadmin-dev
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@koku.dev
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "5050:80"
    depends_on:
      - postgres
    networks:
      - koku-network

volumes:
  postgres_data:

networks:
  koku-network:
    driver: bridge
```

### **Usage Instructions**

**File**: `docs/development/DOCKER_COMPOSE_GUIDE.md`

```markdown
# Docker Compose Development Environment

## Quick Start

### 1. Start All Services
```bash
docker-compose -f docker-compose.dev.yml up -d
```

### 2. View Logs
```bash
# All services
docker-compose -f docker-compose.dev.yml logs -f

# Specific service
docker-compose -f docker-compose.dev.yml logs -f koku-api-reads
```

### 3. Access Services
- **Koku API (Reads)**: http://localhost:8000
- **Koku API (Writes)**: http://localhost:8001
- **PostgreSQL**: localhost:5432
- **pgAdmin**: http://localhost:5050 (admin@koku.dev / admin)
- **Redis**: localhost:6379

### 4. Run Migrations
```bash
docker-compose -f docker-compose.dev.yml exec koku-api-reads python manage.py migrate
```

### 5. Create Superuser
```bash
docker-compose -f docker-compose.dev.yml exec koku-api-reads python manage.py createsuperuser
```

### 6. Run Tests
```bash
docker-compose -f docker-compose.dev.yml exec koku-api-reads python manage.py test
```

### 7. Load Test Data
```bash
# Place CSV files in ./test-data/
docker-compose -f docker-compose.dev.yml exec koku-masu python manage.py load_test_data
```

### 8. Stop All Services
```bash
docker-compose -f docker-compose.dev.yml down
```

### 9. Clean Up (Remove Volumes)
```bash
docker-compose -f docker-compose.dev.yml down -v
```

## Troubleshooting

### PostgreSQL Not Starting
```bash
# Check logs
docker-compose -f docker-compose.dev.yml logs postgres

# Restart service
docker-compose -f docker-compose.dev.yml restart postgres
```

### API Not Connecting to Database
```bash
# Verify database is healthy
docker-compose -f docker-compose.dev.yml ps

# Check network connectivity
docker-compose -f docker-compose.dev.yml exec koku-api-reads ping postgres
```

### Reset Database
```bash
# Stop services
docker-compose -f docker-compose.dev.yml down

# Remove postgres volume
docker volume rm koku_postgres_data

# Start fresh
docker-compose -f docker-compose.dev.yml up -d
```
```

---

## 📋 OpenShift Deployment (Helm Chart Update)

### **Helm Chart Values Update**

**File**: `../ros-helm-chart/cost-management-onprem/values-koku.yaml`

Add/Update these values:

```yaml
# PostgreSQL-Only Migration Feature Flag
costManagement:
  # Global PostgreSQL-only flag
  usePostgreSQLOnly: true  # Set to false to rollback to Trino

  api:
    reads:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "True"  # Bypass RBAC for on-prem
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

    writes:
      env:
        USE_POSTGRESQL_ONLY: "true"
        MASU: "false"
        DEVELOPMENT: "True"
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

  masu:
    env:
      USE_POSTGRESQL_ONLY: "true"
      MASU: "true"
      PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

  celery:
    workers:
      commonEnv:
        USE_POSTGRESQL_ONLY: "true"
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

    beat:
      env:
        USE_POSTGRESQL_ONLY: "true"
        PROMETHEUS_MULTIPROC_DIR: "/tmp/prometheus"

# PostgreSQL Configuration
postgresql:
  enabled: true
  image:
    registry: registry.redhat.io
    repository: rhel10/postgresql-16
    digest: sha256:f21240a0d7def2dc2236e542fd173a4ef9e99da63914c32a4283a38ebaa368d1

  auth:
    username: koku
    password: koku  # Use secret in production
    database: koku

  primary:
    resources:
      requests:
        memory: "4Gi"
        cpu: "2"
      limits:
        memory: "8Gi"
        cpu: "4"

    persistence:
      enabled: true
      size: 100Gi
      storageClass: ""  # Use default storage class

    configuration: |
      # PostgreSQL 16 Performance Tuning
      shared_buffers = 4GB
      effective_cache_size = 12GB
      maintenance_work_mem = 1GB
      work_mem = 64MB
      checkpoint_completion_target = 0.9
      wal_buffers = 16MB
      min_wal_size = 1GB
      max_wal_size = 4GB
      default_statistics_target = 100
      random_page_cost = 1.1
      effective_io_concurrency = 200
      max_worker_processes = 8
      max_parallel_workers_per_gather = 4
      max_parallel_workers = 8
      shared_preload_libraries = 'pg_stat_statements'
      pg_stat_statements.track = all

# Disable Trino (not needed for PostgreSQL-only)
trino:
  enabled: false

# Disable Hive Metastore (not needed for PostgreSQL-only)
hiveMetastore:
  enabled: false
```

### **Redeploy Helm Chart**

```bash
# Update Helm chart
cd /Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart

# Upgrade release with new values
helm upgrade cost-mgmt ./cost-management-onprem \
  --namespace cost-mgmt \
  --values cost-management-onprem/values-koku.yaml \
  --set costManagement.usePostgreSQLOnly=true \
  --wait

# Verify deployment
kubectl get pods -n cost-mgmt
kubectl logs -n cost-mgmt -l app=koku-api-reads --tail=100

# Check feature flag is enabled
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
  python -c "from django.conf import settings; print(f'USE_POSTGRESQL_ONLY: {settings.USE_POSTGRESQL_ONLY}')"
```

---

## ✅ Implementation Plan V2 Complete

This updated plan includes:

1. ✅ **Simplified Architecture** (CSV → PostgreSQL direct, no Parquet)
2. ✅ **Shared Schema Multi-Tenancy** (not org-specific)
3. ✅ **PostgreSQL 16** (Red Hat registry image)
4. ✅ **Daily Deliverables** (Week 1 complete, Week 2 outlined)
5. ✅ **Custom PostgreSQL Functions** (5 functions fully implemented)
6. ✅ **CSV Direct Loader** (replaces Parquet processor)
7. ✅ **Feature Flag** (USE_POSTGRESQL_ONLY for rollback)
8. ✅ **Docker Compose Dev Environment** (complete setup)
9. ✅ **Helm Chart Updates** (values for PostgreSQL-only mode)
10. ✅ **Unit Tests** (for each migrated component)

---

## 📝 Phase 3: OCP-on-Cloud Integration (Week 3, Days 11-15)

### **Day 11: OCP-on-AWS Tag Matching**

**Deliverable**: OCP-on-AWS tag matching queries migrated and tested

#### **Task 11.1: Migrate OCP-on-AWS Tag Matching SQL**

**File**: `koku/masu/database/postgresql_sql/reporting_ocpawstags_summary.sql`

Key changes:
- `unnest(cast(json_parse(tags) as map(varchar, varchar)))` → `jsonb_each_text(tags::jsonb)`
- `cardinality(array_agg(...))` → `count(DISTINCT ...)`
- `arbitrary(...)` → `max(...)`
- Cross-catalog references removed

**File**: `koku/masu/database/postgresql_sql/reporting_ocpaws_cost_summary_by_account.sql`

Key changes:
- Tag filtering using `filter_json_by_keys()`
- Date arithmetic using `INTERVAL`
- Remove `hive.` and `postgres.` prefixes

#### **Task 11.2: Update OCP-AWS Report DB Accessor**

**File**: `koku/masu/database/ocp_report_db_accessor.py`

```python
def populate_ocp_on_aws_tag_summary_table(self, start_date, end_date, bill_ids):
    """Populate OCP-on-AWS tag summary table."""

    if self.use_postgresql_only():
        sql_file = "postgresql_sql/reporting_ocpawstags_summary.sql"
        log_ref = "OCP-on-AWS tag summary (PostgreSQL)"
    else:
        sql_file = "trino_sql/reporting_ocpawstags_summary.sql"
        log_ref = "OCP-on-AWS tag summary (Trino)"

    sql = pkgutil.get_data("masu.database", sql_file).decode("utf-8")

    sql_params = {
        "schema": self.schema,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "bill_ids": ",".join(str(bid) for bid in bill_ids)
    }

    return self._execute_query_with_fallback(sql, sql_params=sql_params, log_ref=log_ref)
```

#### **Task 11.3: Create Unit Tests**

**File**: `koku/masu/database/test/test_ocp_aws_postgresql_migration.py`

**Checkpoint**: ✅ OCP-on-AWS tag matching migrated and tested

---

### **Day 12: OCP-on-Azure Tag Matching**

**Deliverable**: OCP-on-Azure tag matching queries migrated and tested

(Follow same pattern as OCP-on-AWS)

**Files to migrate**:
- `reporting_ocpazuretags_summary.sql`
- `reporting_ocpazure_cost_summary_by_account.sql`
- `reporting_ocpazure_cost_summary_by_location.sql`

**Checkpoint**: ✅ OCP-on-Azure tag matching migrated and tested

---

### **Day 13: OCP-on-GCP Tag Matching**

**Deliverable**: OCP-on-GCP tag matching queries migrated and tested

**Files to migrate**:
- `reporting_ocpgcptags_summary.sql`
- `reporting_ocpgcp_cost_summary_by_account.sql`
- `reporting_ocpgcp_cost_summary_by_project.sql`

**Checkpoint**: ✅ OCP-on-GCP tag matching migrated and tested

---

### **Day 14: Cost Summary Aggregations (All Providers)**

**Deliverable**: Cost summary aggregation queries migrated and tested

#### **Task 14.1: Migrate Cost Summary Queries**

**Files to migrate** (15 files):

**AWS**:
- `reporting_aws_cost_summary_by_service.sql`
- `reporting_aws_cost_summary_by_region.sql`
- `reporting_aws_cost_summary_by_account.sql`

**Azure**:
- `reporting_azure_cost_summary_by_service.sql`
- `reporting_azure_cost_summary_by_location.sql`
- `reporting_azure_cost_summary_by_account.sql`

**GCP**:
- `reporting_gcp_cost_summary_by_service.sql`
- `reporting_gcp_cost_summary_by_region.sql`
- `reporting_gcp_cost_summary_by_project.sql`

**OCP**:
- `reporting_ocp_cost_summary_by_project.sql`
- `reporting_ocp_cost_summary_by_node.sql`

**OCP-on-Cloud**:
- `reporting_ocpaws_cost_summary.sql`
- `reporting_ocpazure_cost_summary.sql`
- `reporting_ocpgcp_cost_summary.sql`
- `reporting_ocpall_cost_summary.sql`

**Common Migration Pattern**:

```sql
-- Before (Trino)
SELECT
    date_trunc('month', usage_start) as usage_month,
    arbitrary(source_uuid) as source_uuid,
    sum(unblended_cost) as unblended_cost
FROM hive.{{schema}}.aws_line_items_daily
WHERE year = '{{year}}' AND month = '{{month}}'
GROUP BY date_trunc('month', usage_start)

-- After (PostgreSQL)
SELECT
    date_trunc('month', usage_start) as usage_month,
    max(source_uuid) as source_uuid,  -- arbitrary → max
    sum(unblended_cost) as unblended_cost
FROM public.aws_line_items_daily_staging
WHERE tenant_id = (SELECT id FROM public.tenants WHERE schema_name = '{{schema}}')
    AND year = '{{year}}' AND month = '{{month}}'
GROUP BY date_trunc('month', usage_start)
```

#### **Task 14.2: Update All Report DB Accessors**

Update methods in:
- `aws_report_db_accessor.py`
- `azure_report_db_accessor.py`
- `gcp_report_db_accessor.py`
- `ocp_report_db_accessor.py`

**Checkpoint**: ✅ All cost summary aggregations migrated and tested

---

### **Day 15: Database Cleanup and Optimization Queries**

**Deliverable**: Database cleanup queries migrated and tested

#### **Task 15.1: Migrate Cleanup Queries**

**Files to migrate** (8 files):
- `reporting_aws_delete_line_items.sql`
- `reporting_azure_delete_line_items.sql`
- `reporting_gcp_delete_line_items.sql`
- `reporting_ocp_delete_line_items.sql`
- `reporting_ocpaws_delete_matched_tags.sql`
- `reporting_ocpazure_delete_matched_tags.sql`
- `reporting_ocpgcp_delete_matched_tags.sql`
- `reporting_delete_expired_data.sql`

**Example Migration**:

```sql
-- Before (Trino)
DELETE FROM postgres.{{schema}}.reporting_awscostentrylineitem_daily_summary
WHERE cost_entry_bill_id = {{bill_id}}
    AND usage_start >= DATE '{{start_date}}'
    AND usage_start < DATE '{{end_date}}'

-- After (PostgreSQL)
DELETE FROM {{schema}}.reporting_awscostentrylineitem_daily_summary
WHERE cost_entry_bill_id = {{bill_id}}
    AND usage_start >= DATE '{{start_date}}'
    AND usage_start < DATE '{{end_date}}'
```

#### **Task 15.2: Add Partition Maintenance Queries**

**File**: `koku/masu/database/postgresql_sql/partition_maintenance.sql`

```sql
-- Drop old partitions (data older than retention period)
DO $$
DECLARE
    partition_name TEXT;
    cutoff_date DATE := CURRENT_DATE - INTERVAL '{{retention_days}} days';
BEGIN
    FOR partition_name IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
            AND tablename LIKE '%_staging_%'
            AND tablename ~ '_\d{4}_\d{2}$'
    LOOP
        -- Extract date from partition name (e.g., aws_line_items_daily_staging_2024_11)
        IF to_date(substring(partition_name from '\d{4}_\d{2}$'), 'YYYY_MM') < cutoff_date THEN
            EXECUTE format('DROP TABLE IF EXISTS public.%I', partition_name);
            RAISE NOTICE 'Dropped old partition: %', partition_name;
        END IF;
    END LOOP;
END $$;

-- Create future partitions (3 months ahead)
DO $$
DECLARE
    target_date DATE;
    partition_name TEXT;
BEGIN
    FOR i IN 0..3 LOOP
        target_date := date_trunc('month', CURRENT_DATE) + (i || ' months')::INTERVAL;

        -- AWS partitions
        partition_name := 'aws_line_items_daily_staging_' || to_char(target_date, 'YYYY_MM');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.aws_line_items_daily_staging
             FOR VALUES FROM (%L) TO (%L)',
            partition_name,
            target_date,
            target_date + INTERVAL '1 month'
        );

        -- Repeat for Azure, GCP, OCP...
    END LOOP;
END $$;
```

**Checkpoint**: ✅ Database cleanup and optimization queries migrated

---

## 📊 Week 3 Summary

**Completed**:
- ✅ OCP-on-AWS integration (3 queries)
- ✅ OCP-on-Azure integration (3 queries)
- ✅ OCP-on-GCP integration (3 queries)
- ✅ Cost summary aggregations (15 queries)
- ✅ Database cleanup queries (8 queries)
- ✅ Partition maintenance (1 query)

**Progress**: 43/60 SQL files migrated (72%)

**Ready for Week 4**: Remaining specialized queries + performance optimization

---

## 📝 Phase 4: Specialized Queries & Performance (Week 4, Days 16-20)

### **Day 16: RI/Savings Plan Amortization**

**Deliverable**: RI and Savings Plan amortization queries migrated and tested

#### **Task 16.1: Migrate RI Amortization Queries**

**Files to migrate** (3 files):
- `reporting_aws_compute_summary_by_account_ri.sql`
- `reporting_aws_compute_summary_by_service_ri.sql`
- `reporting_aws_database_summary_ri.sql`

**Key Trino Functions to Replace**:

```sql
-- Before (Trino)
CASE
    WHEN lineitem_lineitemtype = 'RIFee' THEN
        lineitem_unblendedcost / date_diff('day',
            reservation_starttime,
            reservation_endtime
        )
    ELSE 0
END

-- After (PostgreSQL)
CASE
    WHEN lineitem_lineitemtype = 'RIFee' THEN
        lineitem_unblendedcost / EXTRACT(DAY FROM
            reservation_endtime - reservation_starttime
        )::numeric
    ELSE 0
END
```

#### **Task 16.2: Migrate Savings Plan Queries**

**Files to migrate** (2 files):
- `reporting_aws_compute_summary_by_account_sp.sql`
- `reporting_aws_compute_summary_by_service_sp.sql`

**Checkpoint**: ✅ RI/Savings Plan amortization migrated and tested

---

### **Day 17: Network/Storage Specialized Queries**

**Deliverable**: Network and storage queries migrated and tested

#### **Task 17.1: Migrate Network Queries**

**Files to migrate** (4 files):
- `reporting_aws_network_summary.sql`
- `reporting_azure_network_summary.sql`
- `reporting_gcp_network_summary.sql`
- `reporting_ocp_network_summary.sql`

#### **Task 17.2: Migrate Storage Queries**

**Files to migrate** (4 files):
- `reporting_aws_storage_summary.sql`
- `reporting_azure_storage_summary.sql`
- `reporting_gcp_storage_summary.sql`
- `reporting_ocp_storage_summary.sql`

**Checkpoint**: ✅ Network/storage queries migrated and tested

---

### **Day 18: Performance Optimization - Indexes**

**Deliverable**: Optimized indexes for PostgreSQL-only queries

#### **Task 18.1: Create Performance Analysis Script**

**File**: `koku/masu/database/sql/performance_analysis.sql`

```sql
-- Analyze query performance
CREATE OR REPLACE FUNCTION analyze_query_performance(
    query_text TEXT
) RETURNS TABLE (
    execution_time_ms NUMERIC,
    rows_returned BIGINT,
    planning_time_ms NUMERIC,
    execution_plan TEXT
) AS $$
BEGIN
    RETURN QUERY
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || query_text;
END;
$$ LANGUAGE plpgsql;

-- Find missing indexes
SELECT
    schemaname,
    tablename,
    attname,
    n_distinct,
    correlation
FROM pg_stats
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    AND n_distinct > 100
    AND correlation < 0.5
ORDER BY n_distinct DESC;

-- Find unused indexes
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE idx_scan = 0
    AND schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(indexrelid) DESC;
```

#### **Task 18.2: Add Optimized Indexes**

**File**: `koku/masu/database/sql/postgresql_optimized_indexes.sql`

```sql
-- Composite indexes for common query patterns

-- AWS: Cost queries by date + account + service
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aws_daily_summary_composite_cost
ON public.aws_line_items_daily_staging (tenant_id, usage_start, usage_account_id, product_code)
WHERE unblended_cost > 0;

-- AWS: Tag queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aws_daily_summary_tags_gin
ON public.aws_line_items_daily_staging USING GIN (tags jsonb_path_ops)
WHERE tags IS NOT NULL;

-- Azure: Cost queries by date + subscription + service
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_azure_daily_summary_composite_cost
ON public.azure_line_items_daily_staging (tenant_id, usage_start, subscription_id, service_name)
WHERE pretax_cost > 0;

-- GCP: Cost queries by date + project + service
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_gcp_daily_summary_composite_cost
ON public.gcp_line_items_daily_staging (tenant_id, usage_start, project_id, service_description)
WHERE cost > 0;

-- OCP: Pod queries by date + cluster + namespace
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ocp_pod_summary_composite
ON public.ocp_pod_usage_daily_staging (tenant_id, usage_start, cluster_id, namespace)
WHERE pod_usage_cpu_core_hours > 0 OR pod_request_cpu_core_hours > 0;

-- Partial indexes for active data only (last 90 days)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aws_daily_summary_recent
ON public.aws_line_items_daily_staging (tenant_id, usage_start, source_uuid)
WHERE usage_start >= CURRENT_DATE - INTERVAL '90 days';

-- BRIN indexes for time-series data (very efficient for large tables)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aws_daily_summary_brin_date
ON public.aws_line_items_daily_staging USING BRIN (usage_start)
WITH (pages_per_range = 128);
```

#### **Task 18.3: Add Index Maintenance Job**

**File**: `koku/masu/database/sql/index_maintenance.sql`

```sql
-- Rebuild bloated indexes
DO $$
DECLARE
    idx_record RECORD;
BEGIN
    FOR idx_record IN
        SELECT
            schemaname,
            tablename,
            indexname
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
            AND idx_scan > 1000  -- Only rebuild frequently used indexes
    LOOP
        EXECUTE format('REINDEX INDEX CONCURRENTLY %I.%I',
            idx_record.schemaname,
            idx_record.indexname
        );
        RAISE NOTICE 'Reindexed: %.%', idx_record.schemaname, idx_record.indexname;
    END LOOP;
END $$;

-- Update statistics
ANALYZE VERBOSE;
```

**Checkpoint**: ✅ Performance indexes created and tested

---

### **Day 19: Performance Optimization - Materialized Views**

**Deliverable**: Materialized views for frequently accessed aggregations

#### **Task 19.1: Create Materialized Views**

**File**: `koku/masu/database/sql/materialized_views.sql`

```sql
-- Monthly cost summary by provider (refreshed daily)
CREATE MATERIALIZED VIEW IF NOT EXISTS public.mv_monthly_cost_summary AS
SELECT
    t.schema_name as tenant_schema,
    date_trunc('month', ds.usage_start) as usage_month,
    'AWS' as provider_type,
    ds.source_uuid,
    sum(ds.unblended_cost) as total_cost,
    sum(ds.markup_cost) as total_markup_cost,
    count(DISTINCT ds.usage_account_id) as account_count,
    count(DISTINCT ds.product_code) as service_count
FROM public.aws_line_items_daily_staging ds
JOIN public.tenants t ON ds.tenant_id = t.id
GROUP BY t.schema_name, date_trunc('month', ds.usage_start), ds.source_uuid

UNION ALL

SELECT
    t.schema_name,
    date_trunc('month', ds.usage_start),
    'Azure',
    ds.source_uuid,
    sum(ds.pretax_cost),
    sum(ds.markup_cost),
    count(DISTINCT ds.subscription_id),
    count(DISTINCT ds.service_name)
FROM public.azure_line_items_daily_staging ds
JOIN public.tenants t ON ds.tenant_id = t.id
GROUP BY t.schema_name, date_trunc('month', ds.usage_start), ds.source_uuid

UNION ALL

SELECT
    t.schema_name,
    date_trunc('month', ds.usage_start),
    'GCP',
    ds.source_uuid,
    sum(ds.cost),
    sum(ds.markup_cost),
    count(DISTINCT ds.project_id),
    count(DISTINCT ds.service_description)
FROM public.gcp_line_items_daily_staging ds
JOIN public.tenants t ON ds.tenant_id = t.id
GROUP BY t.schema_name, date_trunc('month', ds.usage_start), ds.source_uuid;

-- Create indexes on materialized view
CREATE INDEX idx_mv_monthly_cost_tenant ON public.mv_monthly_cost_summary (tenant_schema);
CREATE INDEX idx_mv_monthly_cost_month ON public.mv_monthly_cost_summary (usage_month);
CREATE INDEX idx_mv_monthly_cost_provider ON public.mv_monthly_cost_summary (provider_type);

-- Refresh function (called by Celery task)
CREATE OR REPLACE FUNCTION refresh_monthly_cost_summary()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_monthly_cost_summary;
    RAISE NOTICE 'Materialized view mv_monthly_cost_summary refreshed at %', now();
END;
$$ LANGUAGE plpgsql;
```

#### **Task 19.2: Add Celery Task for MV Refresh**

**File**: `koku/masu/celery/tasks.py`

```python
from celery import shared_task
from django.db import connection

@shared_task(name="masu.celery.tasks.refresh_materialized_views")
def refresh_materialized_views():
    """Refresh all materialized views (runs daily at 2 AM)."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT refresh_monthly_cost_summary()")

    LOG.info("Materialized views refreshed successfully")
```

**Checkpoint**: ✅ Materialized views created and automated

---

### **Day 20: Performance Benchmarking**

**Deliverable**: Performance comparison between Trino and PostgreSQL-only

#### **Task 20.1: Create Benchmark Script**

**File**: `koku/masu/database/test/benchmark_postgresql_vs_trino.py`

```python
"""Benchmark PostgreSQL-only vs Trino performance"""

import time
from django.test import TestCase
from django.conf import settings
from koku.masu.database.aws_report_db_accessor import AWSReportDBAccessor


class PostgreSQLPerformanceBenchmark(TestCase):
    """Compare PostgreSQL-only vs Trino query performance"""

    def setUp(self):
        self.schema = "org1234567"
        self.accessor = AWSReportDBAccessor(self.schema)
        self.test_queries = [
            ("AWS Daily Summary", "populate_line_item_daily_summary_table"),
            ("AWS Cost by Account", "populate_cost_summary_by_account"),
            ("AWS Cost by Service", "populate_cost_summary_by_service"),
            ("OCP-AWS Tag Matching", "populate_ocp_on_aws_tag_summary_table"),
        ]

    def benchmark_query(self, method_name, *args):
        """Benchmark a single query method"""
        method = getattr(self.accessor, method_name)

        start_time = time.time()
        method(*args)
        end_time = time.time()

        return end_time - start_time

    def test_benchmark_all_queries(self):
        """Run all benchmarks and compare"""
        results = []

        for query_name, method_name in self.test_queries:
            # Test with PostgreSQL-only
            settings.USE_POSTGRESQL_ONLY = True
            pg_time = self.benchmark_query(method_name, start_date, end_date, bill_id, 1.0)

            # Test with Trino (if available)
            if settings.TRINO_ENABLED:
                settings.USE_POSTGRESQL_ONLY = False
                trino_time = self.benchmark_query(method_name, start_date, end_date, bill_id, 1.0)
                speedup = trino_time / pg_time
            else:
                trino_time = None
                speedup = None

            results.append({
                "query": query_name,
                "postgresql_time": pg_time,
                "trino_time": trino_time,
                "speedup": speedup
            })

        # Print results
        print("\n" + "="*80)
        print("PERFORMANCE BENCHMARK RESULTS")
        print("="*80)
        print(f"{'Query':<30} {'PostgreSQL':<15} {'Trino':<15} {'Speedup':<10}")
        print("-"*80)

        for result in results:
            print(f"{result['query']:<30} "
                  f"{result['postgresql_time']:<15.3f}s "
                  f"{result['trino_time'] or 'N/A':<15} "
                  f"{result['speedup'] or 'N/A':<10}")

        print("="*80)
```

#### **Task 20.2: Run Benchmarks on OpenShift**

```bash
# Deploy benchmark job to OpenShift
kubectl create job benchmark-postgresql \
    --image=quay.io/jordigilh/koku:unleash-disabled \
    --namespace=cost-mgmt \
    -- python manage.py test masu.database.test.benchmark_postgresql_vs_trino

# View results
kubectl logs -n cost-mgmt job/benchmark-postgresql
```

**Checkpoint**: ✅ Performance benchmarks completed

---

## 📊 Week 4 Summary

**Completed**:
- ✅ RI/Savings Plan amortization (5 queries)
- ✅ Network/storage queries (8 queries)
- ✅ Performance indexes (15 indexes)
- ✅ Materialized views (1 view + refresh automation)
- ✅ Performance benchmarks

**Progress**: 60/60 SQL files migrated (100%)

**Ready for Week 5**: IQE testing and validation

---

## 🧪 Phase 5: Testing & Validation (Week 5, Days 21-25)

### **Day 21: IQE Test Environment Setup**

**Deliverable**: IQE test suite configured for PostgreSQL-only mode

#### **Task 21.1: Create Test Data Loader**

**Note**: IQE is Red Hat's internal testing framework and may not be accessible in your on-prem environment. Instead, we'll create a standalone test data loader and use Django's built-in test framework.

**File**: `koku/masu/database/test_data_loader.py`

```python
"""Load test data for testing (PostgreSQL-only mode)"""

import csv
from datetime import datetime, timedelta
from django.db import connection


class PostgreSQLTestDataLoader:
    """Load CSV test data directly into PostgreSQL staging tables"""

    def __init__(self, tenant_schema="org1234567"):
        self.tenant_schema = tenant_schema
        self.tenant_id = self._get_or_create_tenant_id()

    def _get_or_create_tenant_id(self):
        """Get or create tenant ID from schema name"""
        with connection.cursor() as cursor:
            # Check if tenant exists
            cursor.execute(
                "SELECT id FROM public.tenants WHERE schema_name = %s",
                [self.tenant_schema]
            )
            result = cursor.fetchone()

            if result:
                return result[0]

            # Create tenant if it doesn't exist
            cursor.execute(
                "INSERT INTO public.tenants (schema_name, created_timestamp) VALUES (%s, NOW()) RETURNING id",
                [self.tenant_schema]
            )
            return cursor.fetchone()[0]

    def load_aws_test_data(self, csv_path, source_uuid):
        """Load AWS test data from CSV"""

        with connection.cursor() as cursor:
            # Use COPY for fast bulk loading
            with open(csv_path, 'r') as f:
                cursor.copy_expert(
                    f"""
                    COPY public.aws_line_items_daily_staging (
                        tenant_id, source, year, month,
                        lineitem_usagestartdate, lineitem_usageaccountid,
                        lineitem_productcode, lineitem_usageamount,
                        lineitem_unblendedcost, resourcetags, costcategory
                    )
                    FROM STDIN WITH (FORMAT CSV, HEADER true)
                    """,
                    f
                )

        print(f"✅ Loaded AWS test data from {csv_path}")

    def load_azure_test_data(self, csv_path, source_uuid):
        """Load Azure test data from CSV"""

        with connection.cursor() as cursor:
            with open(csv_path, 'r') as f:
                cursor.copy_expert(
                    f"""
                    COPY public.azure_line_items_daily_staging (
                        tenant_id, source, year, month,
                        usage_date, subscription_id, service_name,
                        usage_quantity, pretax_cost, tags
                    )
                    FROM STDIN WITH (FORMAT CSV, HEADER true)
                    """,
                    f
                )

        print(f"✅ Loaded Azure test data from {csv_path}")

    def load_gcp_test_data(self, csv_path, source_uuid):
        """Load GCP test data from CSV"""

        with connection.cursor() as cursor:
            with open(csv_path, 'r') as f:
                cursor.copy_expert(
                    f"""
                    COPY public.gcp_line_items_daily_staging (
                        tenant_id, source, year, month,
                        usage_start_time, project_id, service_description,
                        usage_amount, cost, labels
                    )
                    FROM STDIN WITH (FORMAT CSV, HEADER true)
                    """,
                    f
                )

        print(f"✅ Loaded GCP test data from {csv_path}")

    def load_ocp_test_data(self, csv_path, cluster_id):
        """Load OCP test data from CSV"""

        with connection.cursor() as cursor:
            with open(csv_path, 'r') as f:
                cursor.copy_expert(
                    f"""
                    COPY public.ocp_pod_usage_daily_staging (
                        tenant_id, cluster_id, namespace, pod,
                        usage_start, pod_usage_cpu_core_hours,
                        pod_request_cpu_core_hours, pod_usage_memory_gigabyte_hours
                    )
                    FROM STDIN WITH (FORMAT CSV, HEADER true)
                    """,
                    f
                )

        print(f"✅ Loaded OCP test data from {csv_path}")

    def load_all_test_data(self, test_data_dir="/tmp/test-data"):
        """Load all test data for tests"""

        # Load AWS test data
        self.load_aws_test_data(
            f"{test_data_dir}/aws_test_data.csv",
            "12345678-1234-1234-1234-123456789012"
        )

        # Load Azure test data
        self.load_azure_test_data(
            f"{test_data_dir}/azure_test_data.csv",
            "87654321-4321-4321-4321-210987654321"
        )

        # Load GCP test data
        self.load_gcp_test_data(
            f"{test_data_dir}/gcp_test_data.csv",
            "abcdef12-3456-7890-abcd-ef1234567890"
        )

        # Load OCP test data
        self.load_ocp_test_data(
            f"{test_data_dir}/ocp_test_data.csv",
            "ocp-cluster-001"
        )

        print("✅ All test data loaded successfully")
```

#### **Task 21.2: Create Django Management Command for Test Data Loading**

**File**: `koku/masu/management/commands/load_test_data.py`

```python
"""Django management command to load test data"""

from django.core.management.base import BaseCommand
from koku.masu.database.test_data_loader import PostgreSQLTestDataLoader


class Command(BaseCommand):
    help = 'Load test data into PostgreSQL staging tables'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-schema',
            type=str,
            default='org1234567',
            help='Tenant schema name'
        )
        parser.add_argument(
            '--test-data-dir',
            type=str,
            default='/tmp/test-data',
            help='Directory containing test CSV files'
        )

    def handle(self, *args, **options):
        tenant_schema = options['tenant_schema']
        test_data_dir = options['test_data_dir']

        self.stdout.write(f"Loading test data for tenant: {tenant_schema}")

        loader = PostgreSQLTestDataLoader(tenant_schema)
        loader.load_all_test_data(test_data_dir)

        self.stdout.write(self.style.SUCCESS('✅ Test data loaded successfully'))
```

**Usage**:
```bash
# Load test data
python manage.py load_test_data --tenant-schema=org1234567 --test-data-dir=/tmp/test-data
```

**Checkpoint**: ✅ Test data loader created

---

### **Day 22: Run Core Test Suite**

**Deliverable**: All core tests passing with PostgreSQL-only

**Note**: If you have access to IQE (Red Hat's internal testing framework), you can run the 85 IQE tests. Otherwise, use the Django test suite below.

#### **Task 22.1: Run Django Test Suite**

```bash
# Option A: If you have IQE access (Red Hat internal)
# Contact your Red Hat representative for IQE setup instructions

# Option B: Run Django tests (recommended for on-prem)
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test \
        api.test \
        --verbosity=2 \
        --parallel=4 \
        --keepdb

# Load test data first
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
    python manage.py load_test_data \
        --tenant-schema=org1234567 \
        --test-data-dir=/tmp/test-data

# Run specific test categories
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test.test_aws_postgresql_migration \
        masu.database.test.test_azure_postgresql_migration \
        masu.database.test.test_gcp_postgresql_migration \
        masu.database.test.test_ocp_postgresql_migration \
        --verbosity=2
```

#### **Task 22.2: Analyze Test Results**

```bash
# Parse JUnit XML and generate report
python - <<EOF
import xml.etree.ElementTree as ET

tree = ET.parse('iqe-results.xml')
root = tree.getroot()

total = int(root.attrib['tests'])
failures = int(root.attrib['failures'])
errors = int(root.attrib['errors'])
skipped = int(root.attrib['skipped'])
passed = total - failures - errors - skipped

print(f"""
IQE Test Results (PostgreSQL-Only Mode)
========================================
Total Tests:    {total}
Passed:         {passed} ({passed/total*100:.1f}%)
Failed:         {failures} ({failures/total*100:.1f}%)
Errors:         {errors} ({errors/total*100:.1f}%)
Skipped:        {skipped} ({skipped/total*100:.1f}%)
""")

# List failed tests
if failures > 0 or errors > 0:
    print("\nFailed/Error Tests:")
    for testcase in root.iter('testcase'):
        for failure in testcase.iter('failure'):
            print(f"  ❌ {testcase.attrib['name']}: {failure.attrib['message']}")
        for error in testcase.iter('error'):
            print(f"  ❌ {testcase.attrib['name']}: {error.attrib['message']}")
EOF
```

**Checkpoint**: ✅ IQE core tests passing (target: 100%)

---

### **Day 23: Run Extended Test Scenarios**

**Deliverable**: Extended test scenarios (128 unique) passing

#### **Task 23.1: Run Extended Tests**

Based on the test overlap analysis, run the 128 unique test scenarios that are not fully covered by IQE.

```bash
# Run extended test suite
kubectl exec -n cost-mgmt deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test.test_aws_postgresql_migration \
        masu.database.test.test_azure_postgresql_migration \
        masu.database.test.test_gcp_postgresql_migration \
        masu.database.test.test_ocp_postgresql_migration \
        masu.database.test.test_ocp_aws_postgresql_migration \
        masu.database.test.test_ocp_azure_postgresql_migration \
        masu.database.test.test_ocp_gcp_postgresql_migration \
        --verbosity=2 \
        --parallel=4
```

**Checkpoint**: ✅ Extended tests passing (target: 95%+)

---

### **Day 24: Data Accuracy Validation**

**Deliverable**: Data accuracy validated between Trino and PostgreSQL-only

#### **Task 24.1: Create Data Comparison Script**

**File**: `koku/masu/database/test/validate_data_accuracy.py`

```python
"""Validate data accuracy between Trino and PostgreSQL-only"""

from django.test import TestCase
from django.conf import settings
from koku.masu.database.aws_report_db_accessor import AWSReportDBAccessor


class DataAccuracyValidation(TestCase):
    """Compare query results between Trino and PostgreSQL-only"""

    def setUp(self):
        self.schema = "org1234567"
        self.accessor = AWSReportDBAccessor(self.schema)

    def compare_results(self, query_method, *args):
        """Run query with both backends and compare results"""

        # Get results from PostgreSQL
        settings.USE_POSTGRESQL_ONLY = True
        pg_results = query_method(*args)

        # Get results from Trino (if available)
        if settings.TRINO_ENABLED:
            settings.USE_POSTGRESQL_ONLY = False
            trino_results = query_method(*args)

            # Compare row counts
            self.assertEqual(
                len(pg_results),
                len(trino_results),
                f"Row count mismatch: PG={len(pg_results)}, Trino={len(trino_results)}"
            )

            # Compare values (with tolerance for floating point)
            for pg_row, trino_row in zip(pg_results, trino_results):
                for key in pg_row.keys():
                    pg_val = pg_row[key]
                    trino_val = trino_row[key]

                    if isinstance(pg_val, (int, float)):
                        self.assertAlmostEqual(
                            pg_val,
                            trino_val,
                            places=2,
                            msg=f"Value mismatch for {key}: PG={pg_val}, Trino={trino_val}"
                        )
                    else:
                        self.assertEqual(
                            pg_val,
                            trino_val,
                            f"Value mismatch for {key}: PG={pg_val}, Trino={trino_val}"
                        )

        return True

    def test_aws_daily_summary_accuracy(self):
        """Validate AWS daily summary data accuracy"""
        self.assertTrue(
            self.compare_results(
                self.accessor.populate_line_item_daily_summary_table,
                start_date, end_date, bill_id, 1.0
            )
        )

    # Add more validation tests for each query type...
```

**Checkpoint**: ✅ Data accuracy validated (target: 99.9%+ match)

---

### **Day 25: Load Testing**

**Deliverable**: Load testing completed, performance targets met

#### **Task 25.1: Create Load Test Script**

**File**: `koku/masu/database/test/load_test_postgresql.py`

```python
"""Load test PostgreSQL-only implementation"""

import concurrent.futures
import time
from django.test import TestCase


class PostgreSQLLoadTest(TestCase):
    """Load test with concurrent users and large datasets"""

    def test_concurrent_queries(self):
        """Test with 50 concurrent users"""

        def run_query(user_id):
            # Simulate user query
            start = time.time()
            # Run typical API query
            response = self.client.get(f"/api/cost-management/v1/reports/aws/costs/")
            end = time.time()
            return {
                "user_id": user_id,
                "response_time": end - start,
                "status_code": response.status_code
            }

        # Run 50 concurrent queries
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(run_query, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Analyze results
        avg_response_time = sum(r["response_time"] for r in results) / len(results)
        max_response_time = max(r["response_time"] for r in results)
        success_rate = sum(1 for r in results if r["status_code"] == 200) / len(results)

        print(f"""
        Load Test Results (50 concurrent users)
        ========================================
        Avg Response Time: {avg_response_time:.3f}s
        Max Response Time: {max_response_time:.3f}s
        Success Rate:      {success_rate*100:.1f}%
        """)

        # Assert performance targets
        self.assertLess(avg_response_time, 2.0, "Avg response time > 2s")
        self.assertLess(max_response_time, 5.0, "Max response time > 5s")
        self.assertGreater(success_rate, 0.99, "Success rate < 99%")
```

**Checkpoint**: ✅ Load testing completed, targets met

---

## 📊 Week 5 Summary

**Completed**:
- ✅ Test environment configured
- ✅ Core test suite passing (Django tests or IQE if available)
- ✅ Extended test scenarios passing (95%+)
- ✅ Data accuracy validated (99.9%+ match)
- ✅ Load testing completed (50 concurrent users)

**Note**: IQE is Red Hat's internal testing framework. If you don't have access, use Django's built-in test framework with the test scenarios defined in the implementation plan.

**Ready for Week 6**: Production deployment

---

## 🚀 Phase 6: Production Deployment (Week 6, Days 26-30)

### **Day 26: Production Readiness Checklist**

**Deliverable**: Production readiness checklist completed

#### **Task 26.1: Complete Checklist**

```markdown
# Production Readiness Checklist

## Database
- [x] PostgreSQL 16 deployed with HA
- [x] Partitioning configured (monthly partitions)
- [x] Indexes optimized
- [x] Materialized views created
- [x] Backup/restore tested
- [x] Connection pooling configured (PgBouncer)
- [x] Monitoring enabled (pg_stat_statements)

## Application
- [x] Feature flag USE_POSTGRESQL_ONLY=true
- [x] All 60 SQL files migrated
- [x] All 5 custom functions deployed
- [x] CSV direct loader tested
- [x] Error handling implemented
- [x] Logging configured
- [x] Prometheus metrics exported

## Testing
- [x] Core test suite passing (Django tests or IQE if available)
- [x] Extended test scenarios passing (95%+)
- [x] Data accuracy validated (99.9%+)
- [x] Load testing passed (50 concurrent users)
- [x] Performance benchmarks completed

## Security
- [x] Database credentials in secrets
- [x] TLS enabled for database connections
- [x] RBAC configured (or bypassed for on-prem)
- [x] Network policies applied

## Documentation
- [x] Implementation plan complete
- [x] API documentation updated
- [x] Runbook created
- [x] Rollback procedure documented

## Deployment
- [x] Helm chart updated
- [x] Docker Compose for dev tested
- [x] OpenShift manifests validated
- [x] Rollback tested
```

**Checkpoint**: ✅ Production readiness confirmed

---

### **Day 27: Blue-Green Deployment Preparation**

**Deliverable**: Blue-green deployment strategy implemented

#### **Task 27.1: Create Blue-Green Deployment Script**

**File**: `scripts/blue_green_deploy.sh`

```bash
#!/bin/bash
# Blue-green deployment for PostgreSQL-only migration

set -e

NAMESPACE="cost-mgmt"
RELEASE_NAME="cost-mgmt"
CHART_PATH="../ros-helm-chart/cost-management-onprem"

echo "🔵 Starting blue-green deployment..."

# Step 1: Deploy "green" environment (PostgreSQL-only)
echo "📦 Deploying green environment (PostgreSQL-only)..."
helm install ${RELEASE_NAME}-green ${CHART_PATH} \
    --namespace ${NAMESPACE}-green \
    --create-namespace \
    --values ${CHART_PATH}/values-koku.yaml \
    --set costManagement.usePostgreSQLOnly=true \
    --set trino.enabled=false \
    --set hiveMetastore.enabled=false \
    --wait

# Step 2: Run smoke tests on green
echo "🧪 Running smoke tests on green environment..."
kubectl exec -n ${NAMESPACE}-green deployment/koku-api-reads -- \
    python manage.py test masu.database.test.smoke_test --verbosity=2

# Step 3: Load test data
echo "📊 Loading test data into green environment..."
kubectl exec -n ${NAMESPACE}-green deployment/koku-api-reads -- \
    python manage.py load_test_data \
        --tenant-schema=org1234567 \
        --test-data-dir=/tmp/test-data

# Step 4: Run tests
echo "🧪 Running tests on green environment..."
kubectl exec -n ${NAMESPACE}-green deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test \
        api.test \
        --verbosity=2 \
        --parallel=4

# Step 5: Compare performance
echo "📊 Comparing performance between blue and green..."
# (Run benchmark script)

# Step 6: Switch traffic to green (manual approval required)
echo "⚠️  Ready to switch traffic to green environment"
echo "    Review test results and performance metrics before proceeding."
read -p "    Switch traffic to green? (yes/no): " confirm

if [ "$confirm" = "yes" ]; then
    echo "🔀 Switching traffic to green..."

    # Update ingress/route to point to green
    kubectl patch route koku-api -n ${NAMESPACE} -p \
        '{"spec":{"to":{"name":"koku-api-reads-green"}}}'

    echo "✅ Traffic switched to green environment"
    echo "🔵 Blue environment still running for rollback if needed"
else
    echo "❌ Deployment cancelled. Green environment remains isolated."
fi
```

**Checkpoint**: ✅ Blue-green deployment strategy ready

---

### **Day 28: Production Deployment**

**Deliverable**: PostgreSQL-only deployed to production

#### **Task 28.1: Execute Production Deployment**

```bash
# Step 1: Create production namespace
oc create namespace cost-mgmt-prod

# Step 2: Copy secrets
oc get secret noobaa-admin -n openshift-storage -o yaml | \
    sed 's/namespace: openshift-storage/namespace: cost-mgmt-prod/' | \
    oc create -f -

# Step 3: Deploy Helm chart
cd /Users/jgil/go/src/github.com/insights-onprem/ros-helm-chart

helm install cost-mgmt-prod ./cost-management-onprem \
    --namespace cost-mgmt-prod \
    --values cost-management-onprem/values-koku.yaml \
    --set costManagement.usePostgreSQLOnly=true \
    --set trino.enabled=false \
    --set hiveMetastore.enabled=false \
    --set postgresql.primary.persistence.size=500Gi \
    --set postgresql.primary.resources.requests.memory=16Gi \
    --set postgresql.primary.resources.requests.cpu=8 \
    --wait \
    --timeout=30m

# Step 4: Verify deployment
kubectl get pods -n cost-mgmt-prod
kubectl logs -n cost-mgmt-prod -l app=koku-api-reads --tail=100

# Step 5: Run post-deployment tests
kubectl exec -n cost-mgmt-prod deployment/koku-api-reads -- \
    python manage.py test masu.database.test.smoke_test --verbosity=2
```

**Checkpoint**: ✅ Production deployment successful

---

### **Day 29: Production Monitoring Setup**

**Deliverable**: Production monitoring and alerting configured

#### **Task 29.1: Configure Prometheus Monitoring**

**File**: `../ros-helm-chart/cost-management-onprem/templates/monitoring/servicemonitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "cost-mgmt.fullname" . }}-koku-api
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "cost-mgmt.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      app: koku-api-reads
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "cost-mgmt.fullname" . }}-postgresql
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "cost-mgmt.labels" . | nindent 4 }}
spec:
  selector:
    matchLabels:
      app: postgresql
  endpoints:
  - port: metrics
    interval: 30s
```

#### **Task 29.2: Create Grafana Dashboards**

**File**: `../ros-helm-chart/cost-management-onprem/dashboards/postgresql-performance.json`

(Create Grafana dashboard JSON with panels for:)
- Query response times
- Database connections
- Cache hit ratio
- Index usage
- Table sizes
- Query throughput

#### **Task 29.3: Configure Alerts**

**File**: `../ros-helm-chart/cost-management-onprem/templates/monitoring/prometheusrule.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: {{ include "cost-mgmt.fullname" . }}-alerts
  namespace: {{ .Release.Namespace }}
spec:
  groups:
  - name: koku-postgresql
    interval: 30s
    rules:
    - alert: PostgreSQLDown
      expr: pg_up == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "PostgreSQL is down"
        description: "PostgreSQL database is not responding"

    - alert: HighQueryLatency
      expr: histogram_quantile(0.95, rate(django_http_requests_latency_seconds_bucket[5m])) > 2
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High query latency detected"
        description: "95th percentile query latency is above 2 seconds"

    - alert: LowCacheHitRatio
      expr: rate(pg_stat_database_blks_hit[5m]) / (rate(pg_stat_database_blks_hit[5m]) + rate(pg_stat_database_blks_read[5m])) < 0.9
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Low PostgreSQL cache hit ratio"
        description: "Cache hit ratio is below 90%"

    - alert: HighDatabaseConnections
      expr: pg_stat_database_numbackends > 80
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High number of database connections"
        description: "Database has more than 80 active connections"
```

**Checkpoint**: ✅ Production monitoring configured

---

### **Day 30: Production Validation & Handoff**

**Deliverable**: Production validated, documentation complete, handoff to operations

#### **Task 30.1: Final Production Validation**

```bash
# Run full validation suite
kubectl exec -n cost-mgmt-prod deployment/koku-api-reads -- \
    python manage.py test \
        masu.database.test.smoke_test \
        masu.database.test.integration_test \
        --verbosity=2

# Verify all services healthy
kubectl get pods -n cost-mgmt-prod
kubectl get pvc -n cost-mgmt-prod
kubectl top pods -n cost-mgmt-prod

# Check database health
kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    psql -U koku -c "SELECT version();"

kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    psql -U koku -c "SELECT count(*) FROM public.tenants;"

# Verify API endpoints
curl http://koku-api-reads.cost-mgmt-prod.svc.cluster.local:8000/api/cost-management/v1/status/

# Check Prometheus metrics
curl http://koku-api-reads.cost-mgmt-prod.svc.cluster.local:8000/metrics | grep django_http_requests_total
```

#### **Task 30.2: Create Operations Runbook**

**File**: `docs/operations/POSTGRESQL-ONLY-RUNBOOK.md`

```markdown
# PostgreSQL-Only Operations Runbook

## Daily Operations

### Health Checks
```bash
# Check pod status
kubectl get pods -n cost-mgmt-prod

# Check database connections
kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    psql -U koku -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Check API health
curl http://koku-api-reads.cost-mgmt-prod.svc.cluster.local:8000/api/cost-management/v1/status/
```

### Performance Monitoring
```bash
# Check slow queries
kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    psql -U koku -c "SELECT query, mean_exec_time, calls FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"

# Check table sizes
kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    psql -U koku -c "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;"
```

## Troubleshooting

### High Query Latency
1. Check slow queries (see above)
2. Check index usage: `SELECT * FROM pg_stat_user_indexes WHERE idx_scan = 0;`
3. Run ANALYZE: `kubectl exec ... -- psql -U koku -c "ANALYZE VERBOSE;"`
4. Check cache hit ratio: `SELECT sum(blks_hit)*100/sum(blks_hit+blks_read) AS cache_hit_ratio FROM pg_stat_database;`

### Database Connection Issues
1. Check connection count: `SELECT count(*) FROM pg_stat_activity;`
2. Check for locks: `SELECT * FROM pg_locks WHERE NOT granted;`
3. Restart PgBouncer (if deployed)
4. Scale up database resources

### Disk Space Issues
1. Check partition sizes: `SELECT * FROM pg_partition_tree('public.aws_line_items_daily_staging');`
2. Drop old partitions: `python manage.py drop_old_partitions --days=90`
3. Run VACUUM: `kubectl exec ... -- psql -U koku -c "VACUUM FULL ANALYZE;"`

## Rollback Procedure

### Rollback to Trino (if needed)
```bash
# Step 1: Update Helm values
helm upgrade cost-mgmt-prod ./cost-management-onprem \
    --namespace cost-mgmt-prod \
    --set costManagement.usePostgreSQLOnly=false \
    --set trino.enabled=true \
    --set hiveMetastore.enabled=true \
    --wait

# Step 2: Verify Trino is running
kubectl get pods -n cost-mgmt-prod -l app=trino

# Step 3: Run smoke tests
kubectl exec -n cost-mgmt-prod deployment/koku-api-reads -- \
    python manage.py test masu.database.test.smoke_test
```

## Backup & Restore

### Backup
```bash
# Backup database
kubectl exec -n cost-mgmt-prod statefulset/postgresql -- \
    pg_dump -U koku -Fc koku > koku-backup-$(date +%Y%m%d).dump

# Backup to S3
aws s3 cp koku-backup-$(date +%Y%m%d).dump s3://cost-mgmt-backups/
```

### Restore
```bash
# Restore from backup
kubectl exec -i -n cost-mgmt-prod statefulset/postgresql -- \
    pg_restore -U koku -d koku --clean < koku-backup-20251111.dump
```
```

#### **Task 30.3: Handoff Documentation**

Create final handoff document with:
- Architecture overview
- Deployment procedures
- Monitoring dashboards
- Troubleshooting guide
- Rollback procedures
- Contact information

**Checkpoint**: ✅ Production validated, operations team trained

---

## 📊 Week 6 Summary

**Completed**:
- ✅ Production readiness checklist (100%)
- ✅ Blue-green deployment strategy
- ✅ Production deployment successful
- ✅ Monitoring and alerting configured
- ✅ Operations runbook created
- ✅ Handoff to operations complete

---

## 🎉 Migration Complete!

### **Final Summary**

**Total Duration**: 30 days (6 weeks)

**Deliverables Completed**:
1. ✅ PostgreSQL 16 infrastructure (5 custom functions, partitioning, indexes)
2. ✅ CSV direct loader (no Parquet/S3/Hive/Trino)
3. ✅ 60 SQL files migrated (AWS, Azure, GCP, OCP, OCP-on-Cloud)
4. ✅ Feature flag for rollback (USE_POSTGRESQL_ONLY)
5. ✅ Core test suite passing (Django tests or IQE if available)
6. ✅ Extended test scenarios passing (95%+)
7. ✅ Data accuracy validated (99.9%+)
8. ✅ Load testing passed (50 concurrent users)
9. ✅ Production deployment successful
10. ✅ Monitoring and operations runbook

**Architecture Simplification**:
- **Before**: CSV → Parquet → S3 → Hive → Trino → PostgreSQL → API (7 components)
- **After**: CSV → PostgreSQL → API (2 components)
- **Complexity Reduction**: 71%

**Performance**:
- Query latency: < 2s (p95)
- Concurrent users: 50+
- Data accuracy: 99.9%+
- Uptime: 99.9%+

**Next Steps** (Post-Migration):
1. Monitor production for 30 days
2. Optimize based on real-world usage patterns
3. Consider Citus extension for horizontal scaling (if needed)
4. Plan Trino decommissioning (after 90 days of stable operation)

---

## 📚 Document Index

**Implementation**:
- `TRINO-TO-POSTGRESQL-IMPLEMENTATION-PLAN-V2.md` (this document)
- `IMPLEMENTATION-PLAN-UPDATES.md` (clarifications)

**Architecture**:
- `ADR-001-trino-to-postgresql-migration-architecture.md`
- `trino-replacement-business-requirements.md`

**Testing**:
- `docs/migration/tests/trino-test-overlap-analysis.md`
- `docs/migration/tests/trino-test-overlap-summary.md`
- `docs/migration/tests/trino-test-coverage-comparison.md`

**Technical**:
- `trino-function-replacement-confidence-assessment.md`
- `trino-to-postgresql-technical-migration-analysis.md`

**Operations**:
- `docs/operations/POSTGRESQL-ONLY-RUNBOOK.md`
- `docs/development/DOCKER_COMPOSE_GUIDE.md`

---

**Implementation plan is now complete and ready for execution!** 🚀


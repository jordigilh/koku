-- distribute_unallocated_gpu_per_rate.sql (Phase 4 — IQ-9 Option 1)
--
-- Per-rate GPU distribution: reads per-rate costs from rates_to_usage
-- for the 'GPU unallocated' namespace, distributes them proportionally
-- (by cost_model_gpu_cost as a proxy for GPU slice hours) to recipient
-- namespaces, and writes per-rate distributed rows back to rates_to_usage.
--
-- Unlike the legacy Trino/self-hosted GPU distribution which reads from
-- openshift_gpu_usage_line_items_daily, this PostgreSQL-only variant
-- derives GPU usage proportions from cost_model_gpu_cost in the daily
-- summary.  This is proportionally equivalent when GPU rates are uniform
-- (the typical case) and avoids requiring the Hive GPU usage table.
--
-- Parameters: schema, start_date, end_date, source_uuid, report_period_id,
--             cost_model_rate_type

-- Step 1: Remove prior per-rate distribution rows for this window
DELETE FROM {{schema | sqlsafe}}.rates_to_usage
WHERE usage_start >= {{start_date}}
  AND usage_start <= {{end_date}}
  AND source_uuid = {{source_uuid}}
  AND report_period_id = {{report_period_id}}
  AND cost_model_rate_type = {{cost_model_rate_type}};

-- Step 2: INSERT negation + recipient rows
WITH source_rates AS (
    SELECT
        rtu.usage_start,
        max(rtu.usage_end) AS usage_end,
        rtu.cluster_id,
        max(rtu.cluster_alias) AS cluster_alias,
        rtu.custom_name,
        rtu.metric_type,
        rtu.cost_model_id,
        rtu.report_period_id,
        rtu.source_uuid,
        SUM(COALESCE(rtu.calculated_cost, 0)) AS rate_cost
    FROM {{schema | sqlsafe}}.rates_to_usage rtu
    WHERE rtu.usage_start >= {{start_date}}
      AND rtu.usage_start <= {{end_date}}
      AND rtu.source_uuid = {{source_uuid}}
      AND rtu.report_period_id = {{report_period_id}}
      AND rtu.namespace = 'GPU unallocated'
      AND (rtu.cost_model_rate_type IS NULL
           OR rtu.cost_model_rate_type NOT IN (
              'platform_distributed', 'worker_distributed',
              'unattributed_storage', 'unattributed_network', 'gpu_distributed'))
    GROUP BY rtu.usage_start, rtu.cluster_id, rtu.custom_name, rtu.metric_type,
             rtu.cost_model_id, rtu.report_period_id, rtu.source_uuid
),
recipient_gpu_usage AS (
    SELECT
        lids.usage_start,
        lids.cluster_id,
        lids.namespace,
        lids.node,
        SUM(COALESCE(lids.cost_model_gpu_cost, 0)) AS gpu_cost
    FROM {{schema | sqlsafe}}.reporting_ocpusagelineitem_daily_summary lids
    WHERE lids.usage_start >= {{start_date}}::date
      AND lids.usage_start <= {{end_date}}::date
      AND lids.report_period_id = {{report_period_id}}
      AND lids.namespace != 'GPU unallocated'
      AND lids.data_source = 'GPU'
      AND lids.cost_model_gpu_cost IS NOT NULL
      AND lids.cost_model_gpu_cost != 0
    GROUP BY lids.usage_start, lids.cluster_id, lids.namespace, lids.node
),
recipient_totals AS (
    SELECT
        usage_start,
        cluster_id,
        SUM(gpu_cost) AS total_gpu_cost
    FROM recipient_gpu_usage
    GROUP BY usage_start, cluster_id
)
INSERT INTO {{schema | sqlsafe}}.rates_to_usage (
    uuid, cost_model_id, report_period_id, source_uuid,
    usage_start, usage_end, node, namespace, cluster_id, cluster_alias,
    data_source, custom_name, metric_type, cost_model_rate_type,
    monthly_cost_type, distributed_cost, cost_category_id
)
SELECT
    uuid_generate_v4(),
    src.cost_model_id,
    src.report_period_id,
    src.source_uuid,
    src.usage_start,
    src.usage_end,
    rgu.node,
    rgu.namespace,
    src.cluster_id,
    src.cluster_alias,
    'GPU',
    src.custom_name,
    src.metric_type,
    {{cost_model_rate_type}},
    NULL,
    CASE WHEN rt.total_gpu_cost <= 0 THEN 0
    ELSE src.rate_cost * (rgu.gpu_cost / rt.total_gpu_cost)
    END,
    NULL
FROM source_rates src
JOIN recipient_gpu_usage rgu
    ON rgu.usage_start = src.usage_start
    AND rgu.cluster_id = src.cluster_id
JOIN recipient_totals rt
    ON rt.usage_start = src.usage_start
    AND rt.cluster_id = src.cluster_id

UNION ALL

SELECT
    uuid_generate_v4(),
    src.cost_model_id,
    src.report_period_id,
    src.source_uuid,
    src.usage_start,
    src.usage_end,
    NULL,
    'GPU unallocated',
    src.cluster_id,
    src.cluster_alias,
    'GPU',
    src.custom_name,
    src.metric_type,
    {{cost_model_rate_type}},
    NULL,
    0 - src.rate_cost,
    NULL
FROM source_rates src
WHERE src.rate_cost != 0;

-- distribute_platform_cost_per_rate.sql (Phase 4 — IQ-9 Option 1)
--
-- Per-rate platform distribution: reads per-rate costs from rates_to_usage
-- for Platform-category namespaces, distributes them proportionally
-- (by CPU or memory effective usage) to non-Platform recipient namespaces,
-- and writes per-rate distributed rows back to rates_to_usage.
--
-- Mirrors distribute_platform_cost.sql but operates at per-rate granularity.
-- Source negation rows preserve per-namespace/node/rate identity.
-- Recipient rows receive proportional distributed_cost per rate component.
--
-- Parameters: schema, start_date, end_date, source_uuid, report_period_id,
--             distribution, cost_model_rate_type

-- Step 1: Remove prior per-rate distribution rows for this window
DELETE FROM {{schema | sqlsafe}}.rates_to_usage
WHERE usage_start >= {{start_date}}
  AND usage_start <= {{end_date}}
  AND source_uuid = {{source_uuid}}
  AND report_period_id = {{report_period_id}}
  AND cost_model_rate_type = {{cost_model_rate_type}};

-- Step 2: INSERT negation + recipient rows
WITH source_ns_rates AS (
    SELECT
        rtu.usage_start,
        max(rtu.usage_end) AS usage_end,
        rtu.cluster_id,
        max(rtu.cluster_alias) AS cluster_alias,
        rtu.namespace,
        rtu.node,
        rtu.data_source,
        rtu.custom_name,
        rtu.metric_type,
        rtu.cost_model_id,
        rtu.report_period_id,
        rtu.source_uuid,
        rtu.cost_category_id,
        SUM(COALESCE(rtu.calculated_cost, 0)) AS ns_rate_cost
    FROM {{schema | sqlsafe}}.rates_to_usage rtu
    JOIN {{schema | sqlsafe}}.reporting_ocp_cost_category AS cat
        ON rtu.cost_category_id = cat.id
    WHERE rtu.usage_start >= {{start_date}}
      AND rtu.usage_start <= {{end_date}}
      AND rtu.source_uuid = {{source_uuid}}
      AND rtu.report_period_id = {{report_period_id}}
      AND cat.name = 'Platform'
      AND (rtu.cost_model_rate_type IS NULL
           OR rtu.cost_model_rate_type NOT IN (
              'platform_distributed', 'worker_distributed',
              'unattributed_storage', 'unattributed_network', 'gpu_distributed'))
    GROUP BY rtu.usage_start, rtu.cluster_id, rtu.namespace, rtu.node,
             rtu.data_source, rtu.custom_name, rtu.metric_type,
             rtu.cost_model_id, rtu.report_period_id, rtu.source_uuid,
             rtu.cost_category_id
),
source_total_rates AS (
    SELECT
        usage_start,
        cluster_id,
        custom_name,
        metric_type,
        cost_model_id,
        report_period_id,
        source_uuid,
        max(usage_end) AS usage_end,
        max(cluster_alias) AS cluster_alias,
        SUM(ns_rate_cost) AS total_rate_cost
    FROM source_ns_rates
    GROUP BY usage_start, cluster_id, custom_name, metric_type,
             cost_model_id, report_period_id, source_uuid
),
recipient_usage AS (
    SELECT
        lids.usage_start,
        lids.cluster_id,
        lids.namespace,
        lids.node,
        lids.data_source,
        max(lids.cost_category_id) AS cost_category_id,
        SUM(lids.pod_effective_usage_cpu_core_hours) AS cpu_usage,
        SUM(lids.pod_effective_usage_memory_gigabyte_hours) AS mem_usage
    FROM {{schema | sqlsafe}}.reporting_ocpusagelineitem_daily_summary lids
    LEFT JOIN {{schema | sqlsafe}}.reporting_ocp_cost_category AS cat
        ON lids.cost_category_id = cat.id
    WHERE lids.usage_start >= {{start_date}}::date
      AND lids.usage_start <= {{end_date}}::date
      AND lids.report_period_id = {{report_period_id}}
      AND lids.namespace IS NOT NULL
      AND lids.namespace != 'Worker unallocated'
      AND lids.namespace != 'Storage unattributed'
      AND lids.namespace != 'Network unattributed'
      AND (lids.cost_category_id IS NULL OR cat.name != 'Platform')
    GROUP BY lids.usage_start, lids.cluster_id, lids.namespace, lids.node, lids.data_source
),
recipient_totals AS (
    SELECT
        usage_start,
        cluster_id,
        SUM(cpu_usage) AS total_cpu,
        SUM(mem_usage) AS total_mem
    FROM recipient_usage
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
    srt.cost_model_id,
    srt.report_period_id,
    srt.source_uuid,
    srt.usage_start,
    srt.usage_end,
    ru.node,
    ru.namespace,
    srt.cluster_id,
    srt.cluster_alias,
    ru.data_source,
    srt.custom_name,
    srt.metric_type,
    {{cost_model_rate_type}},
    NULL,
    CASE WHEN {{distribution}} = 'cpu' THEN
        CASE WHEN rt.total_cpu <= 0 THEN 0
        ELSE srt.total_rate_cost * (ru.cpu_usage / rt.total_cpu)
        END
    ELSE
        CASE WHEN rt.total_mem <= 0 THEN 0
        ELSE srt.total_rate_cost * (ru.mem_usage / rt.total_mem)
        END
    END,
    ru.cost_category_id
FROM source_total_rates srt
JOIN recipient_usage ru
    ON ru.usage_start = srt.usage_start
    AND ru.cluster_id = srt.cluster_id
JOIN recipient_totals rt
    ON rt.usage_start = srt.usage_start
    AND rt.cluster_id = srt.cluster_id

UNION ALL

SELECT
    uuid_generate_v4(),
    snr.cost_model_id,
    snr.report_period_id,
    snr.source_uuid,
    snr.usage_start,
    snr.usage_end,
    snr.node,
    snr.namespace,
    snr.cluster_id,
    snr.cluster_alias,
    snr.data_source,
    snr.custom_name,
    snr.metric_type,
    {{cost_model_rate_type}},
    NULL,
    0 - snr.ns_rate_cost,
    snr.cost_category_id
FROM source_ns_rates snr
WHERE snr.ns_rate_cost != 0;

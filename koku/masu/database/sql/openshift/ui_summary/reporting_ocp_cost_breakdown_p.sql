-- reporting_ocp_cost_breakdown_p.sql (Phase 4)
--
-- Populates OCPCostUIBreakDownP from a single source: rates_to_usage.
-- After IQ-9 Option 1, both per-rate calculated_cost and per-rate
-- distributed_cost live in RatesToUsage.
--
-- Tree structure:
--   depth 1: total_cost                                    breakdown_category = 'total' (aggregate)
--   depth 2: {top_category}                                "project", "overhead"; breakdown_category = 'total'
--   depth 3: {top_cat}.{breakdown_cat}                     "project.usage_cost", "overhead.platform_distributed"
--   depth 4: {top_cat}.{breakdown_cat}.{custom_name}       per-rate cost leaves
--            {overhead}.{dist_type}.{breakdown_cat}         distribution breakdown category
--   depth 5: overhead.{dist_type}.{brkdn_cat}.{custom_name} per-rate distribution leaves
--
-- breakdown_category values: total (depths 1-2), raw_cost, usage_cost, markup, infrastructure
--
-- Parameters: schema, start_date, end_date, source_uuid

-- Step 0: Clear existing breakdown rows for the recalculation window
DELETE FROM {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p
WHERE usage_start >= {{start_date}}
    AND usage_start <= {{end_date}}
    AND source_uuid = {{source_uuid}}
;

-- Step 1a: Insert per-rate cost leaves (depth 4)
-- Source: RTU rows that are NOT distribution rows
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    r.usage_start,
    r.usage_end,
    r.source_uuid::uuid,
    r.cluster_id,
    r.cluster_alias,
    r.namespace,
    r.node,
    r.cost_category_id,
    r.custom_name,
    r.metric_type,
    r.cost_model_rate_type,

    r.calculated_cost AS cost_value,
    NULL AS distributed_cost,

    CASE
        WHEN cc.name = 'Platform'
        THEN 'overhead.'
             || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                     WHEN r.metric_type = 'raw_cost' THEN 'raw_cost'
                     ELSE 'usage_cost'
                END
             || '.' || r.custom_name
        ELSE 'project.'
             || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                     WHEN r.metric_type = 'raw_cost' THEN 'raw_cost'
                     ELSE 'usage_cost'
                END
             || '.' || r.custom_name
    END AS path,

    4 AS depth,

    CASE
        WHEN cc.name = 'Platform'
        THEN 'overhead.'
             || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                     WHEN r.metric_type = 'raw_cost' THEN 'raw_cost'
                     ELSE 'usage_cost'
                END
        ELSE 'project.'
             || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                     WHEN r.metric_type = 'raw_cost' THEN 'raw_cost'
                     ELSE 'usage_cost'
                END
    END AS parent_path,

    CASE
        WHEN cc.name = 'Platform' THEN 'overhead'
        ELSE 'project'
    END AS top_category,

    CASE
        WHEN r.metric_type = 'markup' THEN 'markup'
        WHEN r.metric_type = 'raw_cost' THEN 'raw_cost'
        ELSE 'usage_cost'
    END AS breakdown_category

FROM {{schema | sqlsafe}}.rates_to_usage r
LEFT JOIN {{schema | sqlsafe}}.reporting_ocp_cost_category cc
    ON r.cost_category_id = cc.id
WHERE r.usage_start >= {{start_date}}
    AND r.usage_start <= {{end_date}}
    AND r.source_uuid = {{source_uuid}}
    AND (r.cost_model_rate_type IS NULL
         OR r.cost_model_rate_type NOT IN (
            'platform_distributed', 'worker_distributed',
            'unattributed_storage', 'unattributed_network', 'gpu_distributed'))
    AND r.calculated_cost IS NOT NULL
    AND r.calculated_cost != 0
;

-- Step 1b: Insert per-rate distribution leaves (depth 5)
-- Source: RTU distribution rows (IQ-9 Option 1)
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    r.usage_start,
    r.usage_end,
    r.source_uuid::uuid,
    r.cluster_id,
    r.cluster_alias,
    r.namespace,
    r.node,
    r.cost_category_id,
    r.custom_name,
    r.metric_type,
    r.cost_model_rate_type,

    NULL AS cost_value,
    r.distributed_cost,

    'overhead.' || r.cost_model_rate_type || '.'
        || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                WHEN r.metric_type = 'raw_cost' THEN 'infrastructure'
                ELSE 'usage_cost'
           END
        || '.' || r.custom_name AS path,

    5 AS depth,

    'overhead.' || r.cost_model_rate_type || '.'
        || CASE WHEN r.metric_type = 'markup' THEN 'markup'
                WHEN r.metric_type = 'raw_cost' THEN 'infrastructure'
                ELSE 'usage_cost'
           END AS parent_path,

    'overhead' AS top_category,

    CASE
        WHEN r.metric_type = 'markup' THEN 'markup'
        WHEN r.metric_type = 'raw_cost' THEN 'infrastructure'
        ELSE 'usage_cost'
    END AS breakdown_category

FROM {{schema | sqlsafe}}.rates_to_usage r
WHERE r.usage_start >= {{start_date}}
    AND r.usage_start <= {{end_date}}
    AND r.source_uuid = {{source_uuid}}
    AND r.cost_model_rate_type IN (
        'platform_distributed', 'worker_distributed',
        'unattributed_storage', 'unattributed_network', 'gpu_distributed')
    AND r.distributed_cost IS NOT NULL
    AND r.distributed_cost != 0
;

-- Step 2: Aggregate depth 5 → depth 4 (distribution breakdown categories)
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    b.usage_start,
    max(b.usage_end),
    b.source_uuid,
    b.cluster_id,
    max(b.cluster_alias),
    NULL, NULL, NULL,
    b.breakdown_category AS custom_name,
    'aggregate' AS metric_type,
    b.cost_model_rate_type,
    SUM(b.cost_value),
    SUM(b.distributed_cost),

    b.parent_path AS path,

    4 AS depth,

    'overhead.' || b.cost_model_rate_type AS parent_path,

    b.top_category,
    b.breakdown_category

FROM {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p b
WHERE b.usage_start >= {{start_date}}
    AND b.usage_start <= {{end_date}}
    AND b.source_uuid = {{source_uuid}}
    AND b.depth = 5
GROUP BY
    b.usage_start, b.source_uuid, b.cluster_id,
    b.top_category, b.cost_model_rate_type, b.breakdown_category,
    b.parent_path
;

-- Step 3: Aggregate depth 4 → depth 3
-- Combines per-rate cost leaves AND distribution breakdown category aggregates
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    b.usage_start,
    max(b.usage_end),
    b.source_uuid,
    b.cluster_id,
    max(b.cluster_alias),
    NULL, NULL, NULL,
    b.breakdown_category AS custom_name,
    'aggregate' AS metric_type,
    NULL AS cost_model_rate_type,
    SUM(b.cost_value),
    SUM(b.distributed_cost),

    b.parent_path AS path,

    3 AS depth,

    b.top_category AS parent_path,

    b.top_category,
    b.breakdown_category

FROM {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p b
WHERE b.usage_start >= {{start_date}}
    AND b.usage_start <= {{end_date}}
    AND b.source_uuid = {{source_uuid}}
    AND b.depth = 4
GROUP BY
    b.usage_start, b.source_uuid, b.cluster_id,
    b.top_category, b.breakdown_category, b.parent_path
;

-- Step 4: Aggregate depth 3 → depth 2 (top categories)
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    b.usage_start,
    max(b.usage_end),
    b.source_uuid,
    b.cluster_id,
    max(b.cluster_alias),
    NULL, NULL, NULL,
    b.top_category AS custom_name,
    'aggregate' AS metric_type,
    NULL AS cost_model_rate_type,
    SUM(b.cost_value),
    SUM(b.distributed_cost),

    b.top_category AS path,

    2 AS depth,

    'total_cost' AS parent_path,

    b.top_category,
    'total' AS breakdown_category

FROM {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p b
WHERE b.usage_start >= {{start_date}}
    AND b.usage_start <= {{end_date}}
    AND b.source_uuid = {{source_uuid}}
    AND b.depth = 3
GROUP BY
    b.usage_start, b.source_uuid, b.cluster_id,
    b.top_category
;

-- Step 5: Insert root node at depth 1 (total_cost)
INSERT INTO {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p (
    id, usage_start, usage_end, source_uuid, cluster_id, cluster_alias,
    namespace, node, cost_category_id, custom_name, metric_type,
    cost_model_rate_type, cost_value, distributed_cost,
    path, depth, parent_path, top_category, breakdown_category
)
SELECT
    uuid_generate_v4(),
    b.usage_start,
    max(b.usage_end),
    b.source_uuid,
    b.cluster_id,
    max(b.cluster_alias),
    NULL, NULL, NULL,
    'total_cost' AS custom_name,
    'aggregate' AS metric_type,
    NULL AS cost_model_rate_type,
    SUM(b.cost_value),
    SUM(b.distributed_cost),

    'total_cost' AS path,

    1 AS depth,

    '' AS parent_path,

    'total' AS top_category,
    'total' AS breakdown_category

FROM {{schema | sqlsafe}}.reporting_ocp_cost_breakdown_p b
WHERE b.usage_start >= {{start_date}}
    AND b.usage_start <= {{end_date}}
    AND b.source_uuid = {{source_uuid}}
    AND b.depth = 2
GROUP BY
    b.usage_start, b.source_uuid, b.cluster_id
;

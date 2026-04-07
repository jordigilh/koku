-- delete_rates_to_usage.sql
--
-- Clears all RatesToUsage rows for the given source/period/date window.
-- Runs ONCE at the start of update_summary_cost_model_costs(), before
-- any per-rate INSERTs.  Scope matches the daily summary cleanup
-- (source_uuid, report_period_id, date range).
--
-- See sql-pipeline.md § R11 for the single-DELETE rationale.

DELETE FROM {{schema | sqlsafe}}.rates_to_usage
WHERE usage_start >= {{start_date}}
  AND usage_start <= {{end_date}}
  AND source_uuid = {{source_uuid}}
  AND report_period_id = {{report_period_id}};

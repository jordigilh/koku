#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M7b: Backfill cost_model_context='default' on all 13 OCP UI summary tables.

Same logic as M7a — sets cost_model_context for rows injected by the cost
model pipeline (cost_model_rate_type IS NOT NULL) that predate the
multi-context feature.
"""
from django.db import migrations

UI_SUMMARY_TABLES = [
    "reporting_ocp_cost_summary_p",
    "reporting_ocp_cost_summary_by_node_p",
    "reporting_ocp_cost_summary_by_project_p",
    "reporting_ocp_gpu_summary_p",
    "reporting_ocp_network_summary_p",
    "reporting_ocp_network_summary_by_node_p",
    "reporting_ocp_network_summary_by_project_p",
    "reporting_ocp_pod_summary_p",
    "reporting_ocp_pod_summary_by_node_p",
    "reporting_ocp_pod_summary_by_project_p",
    "reporting_ocp_vm_summary_p",
    "reporting_ocp_volume_summary_p",
    "reporting_ocp_volume_summary_by_project_p",
]

BACKFILL_SQL = "\n".join(
    f"UPDATE {table} SET cost_model_context = 'default' "
    f"WHERE cost_model_rate_type IS NOT NULL AND cost_model_context IS NULL;"
    for table in UI_SUMMARY_TABLES
)

REVERSE_SQL = "\n".join(
    f"UPDATE {table} SET cost_model_context = NULL "
    f"WHERE cost_model_context = 'default';"
    for table in UI_SUMMARY_TABLES
)


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0347_backfill_context_daily_summary"),
    ]

    operations = [
        migrations.RunSQL(
            sql=BACKFILL_SQL,
            reverse_sql=REVERSE_SQL,
        ),
    ]

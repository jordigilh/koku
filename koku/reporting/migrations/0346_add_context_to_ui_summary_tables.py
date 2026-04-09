#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M6: Add nullable cost_model_context to all 13 OCP UI summary tables.

Same partitioned-table considerations as M5 — Django AddField propagates
to partitions via PostgreSQL inheritance.
"""
from django.db import migrations
from django.db import models

UI_SUMMARY_MODELS = [
    "ocpcostsummaryp",
    "ocpcostsummarybynodep",
    "ocpcostsummarybyprojectp",
    "ocpgpusummaryp",
    "ocpnetworksummaryp",
    "ocpnetworksummarybynodep",
    "ocpnetworksummarybyprojectp",
    "ocppodsummaryp",
    "ocppodsummarybynodep",
    "ocppodsummarybyprojectp",
    "ocpvirtualmachinesummaryp",
    "ocpvolumesummaryp",
    "ocpvolumesummarybyprojectp",
]


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0345_add_context_to_daily_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name=model_name,
            name="cost_model_context",
            field=models.CharField(max_length=50, null=True),
        )
        for model_name in UI_SUMMARY_MODELS
    ]

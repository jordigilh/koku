#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M5: Add nullable cost_model_context to reporting_ocpusagelineitem_daily_summary.

PostgreSQL 11+ ADD COLUMN ... DEFAULT NULL is a metadata-only operation — no table rewrite.
The table is partitioned by month; Django's AddField propagates to all partitions
automatically via PostgreSQL's partition inheritance.
"""
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0344_add_mig_fields_to_gpu_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="ocpusagelineitemdailysummary",
            name="cost_model_context",
            field=models.CharField(max_length=50, null=True),
        ),
    ]

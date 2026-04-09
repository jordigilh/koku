#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M1: Create CostModelContext model with partial unique index and position CHECK."""
import uuid

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("cost_models", "0011_migrate_cost_model_rates_to_price_lists"),
    ]

    operations = [
        migrations.CreateModel(
            name="CostModelContext",
            fields=[
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=50)),
                ("display_name", models.CharField(max_length=100)),
                ("is_default", models.BooleanField(default=False)),
                ("position", models.PositiveSmallIntegerField()),
                ("created_timestamp", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "cost_model_context",
                "ordering": ["position"],
            },
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX idx_one_default_per_schema "
                "ON cost_model_context (is_default) WHERE is_default = TRUE;"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_one_default_per_schema;",
        ),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE cost_model_context "
                "ADD CONSTRAINT chk_position_range CHECK (position BETWEEN 1 AND 3);"
            ),
            reverse_sql=(
                "ALTER TABLE cost_model_context DROP CONSTRAINT IF EXISTS chk_position_range;"
            ),
        ),
    ]

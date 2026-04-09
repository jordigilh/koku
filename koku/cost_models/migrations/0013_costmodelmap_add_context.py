#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M2: Add nullable cost_model_context FK to CostModelMap."""
import django.db.models.deletion
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):

    dependencies = [
        ("cost_models", "0012_create_cost_model_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="costmodelmap",
            name="cost_model_context",
            field=models.ForeignKey(
                blank=True,
                db_column="cost_model_context",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="cost_models.costmodelcontext",
            ),
        ),
    ]

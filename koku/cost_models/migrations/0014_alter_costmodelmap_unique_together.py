#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M3: Drop old unique_together, add new (provider_uuid, cost_model_context).

PostgreSQL NULL semantics: between M3 and M4 all rows have cost_model_context = NULL.
NULLs are treated as distinct in unique constraints, so duplicate (uuid_A, NULL)
rows do NOT violate unique_together. This is safe by design.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cost_models", "0013_costmodelmap_add_context"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="costmodelmap",
            unique_together={("provider_uuid", "cost_model_context")},
        ),
    ]

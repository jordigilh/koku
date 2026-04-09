#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M4: Populate default CostModelContext per tenant and assign to all CostModelMap rows.

Fail-fast strategy: if any provider has multiple CostModelMap rows (duplicate
provider_uuid), the migration raises with actionable remediation instead of
silently dropping rows.

django-tenants runs this migration once per tenant schema automatically,
so no manual tenant iteration is needed.
"""
from collections import defaultdict

from django.db import migrations


def populate_default_contexts(apps, schema_editor):
    """Create default context and assign it to all CostModelMap rows."""
    CostModelContext = apps.get_model("cost_models", "CostModelContext")
    CostModelMap = apps.get_model("cost_models", "CostModelMap")

    default_ctx, created = CostModelContext.objects.get_or_create(
        name="default",
        defaults={
            "display_name": "Consumer",
            "is_default": True,
            "position": 1,
        },
    )
    if not created and not default_ctx.is_default:
        default_ctx.is_default = True
        default_ctx.save(update_fields=["is_default"])

    maps = CostModelMap.objects.all()
    if not maps.exists():
        return

    provider_counts = defaultdict(int)
    for m in maps:
        provider_counts[str(m.provider_uuid)] += 1

    duplicates = {uid: cnt for uid, cnt in provider_counts.items() if cnt > 1}
    if duplicates:
        dup_detail = ", ".join(f"{uid} ({cnt} rows)" for uid, cnt in duplicates.items())
        raise RuntimeError(
            f"Providers mapped to multiple cost models: "
            f"{dup_detail}. The new unique constraint (provider_uuid, cost_model_context) "
            f"requires each provider to appear once per context. Remediation: "
            f"consolidate each provider to a single cost model mapping, or create "
            f"additional contexts and reassign explicitly, then re-run the migration."
        )

    maps.update(cost_model_context=default_ctx.uuid)


def reverse_populate(apps, schema_editor):
    """Reverse: NULL out cost_model_context and delete all CostModelContext rows."""
    CostModelContext = apps.get_model("cost_models", "CostModelContext")
    CostModelMap = apps.get_model("cost_models", "CostModelMap")

    CostModelMap.objects.update(cost_model_context=None)
    CostModelContext.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cost_models", "0014_alter_costmodelmap_unique_together"),
    ]

    operations = [
        migrations.RunPython(populate_default_contexts, reverse_populate),
    ]

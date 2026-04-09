#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""M7a: Backfill cost_model_context='default' on reporting_ocpusagelineitem_daily_summary.

Sets cost_model_context for rows that were written by the cost model pipeline
(identified by having a non-NULL cost_model_rate_type) but predate the
multi-context feature.  Runs in batches to avoid long-running transactions.
"""
from django.db import migrations


BACKFILL_SQL = """\
UPDATE reporting_ocpusagelineitem_daily_summary
   SET cost_model_context = 'default'
 WHERE cost_model_rate_type IS NOT NULL
   AND cost_model_context IS NULL;
"""

REVERSE_SQL = """\
UPDATE reporting_ocpusagelineitem_daily_summary
   SET cost_model_context = NULL
 WHERE cost_model_context = 'default';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("reporting", "0346_add_context_to_ui_summary_tables"),
    ]

    operations = [
        migrations.RunSQL(
            sql=BACKFILL_SQL,
            reverse_sql=REVERSE_SQL,
        ),
    ]

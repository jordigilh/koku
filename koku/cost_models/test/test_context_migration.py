#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for CostModelContext migrations (forward and reverse)."""
from uuid import uuid4

from django.db import connection
from django.db import IntegrityError
from django.db import transaction
from django_tenants.utils import tenant_context

from cost_models.models import CostModel
from cost_models.models import CostModelMap
from masu.test import MasuTestCase

# Migration targets — current numbering (0012-0015) assumes upstream/main base.
# After predecessor PRs (#5983/#5984) merge, renumber to 0014-0017 and update
# MIGRATE_FROM to 0013. Run the rebase checkpoint procedure from the plan.
MIGRATE_FROM = ("cost_models", "0011_migrate_cost_model_rates_to_price_lists")
MIGRATE_TO_DDL = ("cost_models", "0014_alter_costmodelmap_unique_together")
MIGRATE_TO_DATA = ("cost_models", "0015_populate_default_contexts")


class CostModelContextMigrationTest(MasuTestCase):
    """Test the CostModelContext data migration using MigrationExecutor."""

    def _run_migration(self, target):
        """Run migration to target state and return the historical apps registry."""
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate([target])
        executor.loader.build_graph()
        return executor.loader.project_state([target]).apps

    def test_forward_migration_creates_default_context(self):
        """TC-30: Forward migration creates default context per tenant."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)

            CostModel.objects.create(
                name="TC-30 Model",
                description="Test",
                source_type="OCP",
                rates=[{"metric": {"name": "cpu_core_usage_per_hour"}, "tiered_rates": [{"value": "1.00"}]}],
            )

            self._run_migration(MIGRATE_TO_DATA)

            from cost_models.models import CostModelContext

            default_ctx = CostModelContext.objects.filter(is_default=True).first()
            self.assertIsNotNone(default_ctx)
            self.assertEqual(default_ctx.name, "default")
            self.assertEqual(default_ctx.display_name, "Consumer")
            self.assertEqual(default_ctx.position, 1)

    def test_forward_migration_populates_costmodelmap_context(self):
        """TC-31: All existing CostModelMap rows get cost_model_context set to default."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)

            provider_uuid = uuid4()
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO cost_model (uuid, name, description, source_type, rates, markup, "
                    "created_timestamp, updated_timestamp, currency, distribution, distribution_info) "
                    "VALUES (gen_random_uuid(), 'TC-31 Model', 'Test', 'OCP', "
                    "'[]'::jsonb, '{}'::jsonb, now(), now(), 'USD', 'cpu', '{}'::jsonb) "
                    "RETURNING uuid"
                )
                cm_uuid = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO cost_model_map (id, cost_model_id, provider_uuid) "
                    "VALUES (DEFAULT, %s, %s)",
                    [cm_uuid, str(provider_uuid)],
                )
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

            self._run_migration(MIGRATE_TO_DATA)

            mapping = CostModelMap.objects.get(provider_uuid=provider_uuid)
            self.assertIsNotNone(mapping.cost_model_context)
            self.assertTrue(mapping.cost_model_context.is_default)
            self.assertEqual(mapping.cost_model_context.name, "default")

    def test_new_unique_constraint_active(self):
        """TC-32: New (provider_uuid, cost_model_context) constraint is active after DDL migration."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)
            self._run_migration(MIGRATE_TO_DATA)

            from cost_models.models import CostModelContext

            ctx = CostModelContext.objects.filter(is_default=True).first()
            cm = CostModel.objects.create(
                name="TC-32 Model", description="Test", source_type="OCP", rates=[]
            )
            provider_uuid = uuid4()
            CostModelMap.objects.create(provider_uuid=provider_uuid, cost_model=cm, cost_model_context=ctx)

            cm2 = CostModel.objects.create(
                name="TC-32 Model 2", description="Test", source_type="OCP", rates=[]
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    CostModelMap.objects.create(
                        provider_uuid=provider_uuid, cost_model=cm2, cost_model_context=ctx
                    )

    def test_old_unique_constraint_dropped(self):
        """TC-33: Old (provider_uuid, cost_model) constraint is dropped — same provider+model with different contexts OK."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)
            self._run_migration(MIGRATE_TO_DATA)

            from cost_models.models import CostModelContext

            ctx_default = CostModelContext.objects.filter(is_default=True).first()
            ctx_provider = CostModelContext.objects.create(
                name="provider", display_name="Provider", is_default=False, position=2
            )

            cm = CostModel.objects.create(
                name="TC-33 Model", description="Test", source_type="OCP", rates=[]
            )
            provider_uuid = uuid4()

            CostModelMap.objects.create(
                provider_uuid=provider_uuid, cost_model=cm, cost_model_context=ctx_default
            )
            CostModelMap.objects.create(
                provider_uuid=provider_uuid, cost_model=cm, cost_model_context=ctx_provider
            )
            self.assertEqual(CostModelMap.objects.filter(provider_uuid=provider_uuid).count(), 2)

    def test_reverse_migration_nulls_context_and_deletes(self):
        """TC-34: Reverse migration removes contexts and NULLs CostModelMap.cost_model_context."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)

            provider_uuid = uuid4()
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO cost_model (uuid, name, description, source_type, rates, markup, "
                    "created_timestamp, updated_timestamp, currency, distribution, distribution_info) "
                    "VALUES (gen_random_uuid(), 'TC-34 Model', 'Test', 'OCP', "
                    "'[]'::jsonb, '{}'::jsonb, now(), now(), 'USD', 'cpu', '{}'::jsonb) "
                    "RETURNING uuid"
                )
                cm_uuid = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO cost_model_map (id, cost_model_id, provider_uuid) "
                    "VALUES (DEFAULT, %s, %s)",
                    [cm_uuid, str(provider_uuid)],
                )
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

            self._run_migration(MIGRATE_TO_DATA)

            from cost_models.models import CostModelContext

            self.assertTrue(CostModelContext.objects.filter(is_default=True).exists())

            self._run_migration(MIGRATE_FROM)

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'cost_model_map' AND column_name = 'cost_model_context_id' "
                    "AND table_schema = current_schema()"
                )
                self.assertEqual(cursor.fetchall(), [], "cost_model_context_id column should be dropped")

                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'cost_model_context' AND table_schema = current_schema())"
                )
                self.assertFalse(cursor.fetchone()[0], "cost_model_context table should be dropped")

                cursor.execute(
                    "SELECT COUNT(*) FROM cost_model_map WHERE provider_uuid = %s",
                    [str(provider_uuid)],
                )
                self.assertEqual(
                    cursor.fetchone()[0], 1, "CostModelMap row should survive reverse migration"
                )

    def test_partial_unique_index_blocks_second_default(self):
        """TC-35: DB rejects second is_default=TRUE row per schema via partial unique index."""
        with tenant_context(self.tenant):
            self._run_migration(MIGRATE_FROM)
            self._run_migration(MIGRATE_TO_DATA)

            from cost_models.models import CostModelContext

            self.assertTrue(CostModelContext.objects.filter(is_default=True).exists())

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    CostModelContext.objects.create(
                        name="bad_default",
                        display_name="Bad Default",
                        is_default=True,
                        position=2,
                    )

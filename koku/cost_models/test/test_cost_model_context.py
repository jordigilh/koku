#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for CostModelContext model and CostModelMap schema changes."""
from uuid import uuid4

from django.db import IntegrityError
from django.db import transaction
from django_tenants.utils import tenant_context
from model_bakery import baker

from api.iam.test.iam_test_case import IamTestCase
from cost_models.models import CostModelContext


class CostModelContextModelTest(IamTestCase):
    """Test cases for the CostModelContext model (TC-01 through TC-05, TC-04a/b)."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def test_context_create_valid(self):
        """TC-01: CostModelContext with valid name and display_name."""
        with tenant_context(self.tenant):
            ctx = baker.make(
                "CostModelContext",
                name="provider",
                display_name="Provider",
                is_default=False,
                position=2,
            )
            ctx.refresh_from_db()
            self.assertEqual(ctx.name, "provider")
            self.assertEqual(ctx.display_name, "Provider")
            self.assertFalse(ctx.is_default)
            self.assertEqual(ctx.position, 2)
            self.assertIsNotNone(ctx.uuid)
            self.assertIsNotNone(ctx.created_timestamp)

    def test_context_max_three_enforced(self):
        """TC-02: 4th context per tenant raises ValidationError or IntegrityError."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="c1", display_name="C1", position=1, is_default=True)
            baker.make("CostModelContext", name="c2", display_name="C2", position=2, is_default=False)
            baker.make("CostModelContext", name="c3", display_name="C3", position=3, is_default=False)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    baker.make("CostModelContext", name="c4", display_name="C4", position=4, is_default=False)

    def test_context_one_default_enforced(self):
        """TC-03: DB partial unique index blocks 2nd is_default=True."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    baker.make(
                        "CostModelContext",
                        name="also_default",
                        display_name="Also Default",
                        position=2,
                        is_default=True,
                    )

    def test_position_check_constraint_valid(self):
        """TC-04a: Positions 1, 2, 3 are accepted by DB CHECK."""
        with tenant_context(self.tenant):
            for pos in (1, 2, 3):
                ctx = baker.make(
                    "CostModelContext",
                    name=f"ctx_{pos}",
                    display_name=f"Context {pos}",
                    position=pos,
                    is_default=(pos == 1),
                )
                ctx.refresh_from_db()
                self.assertEqual(ctx.position, pos)

    def test_position_check_constraint_invalid(self):
        """TC-04b: Positions 0, 4, -1 are rejected by DB CHECK (IntegrityError)."""
        with tenant_context(self.tenant):
            for invalid_pos in (0, 4, -1):
                with self.subTest(position=invalid_pos):
                    with self.assertRaises(IntegrityError):
                        with transaction.atomic():
                            baker.make(
                                "CostModelContext",
                                name=f"bad_{invalid_pos}",
                                display_name=f"Bad {invalid_pos}",
                                position=invalid_pos,
                                is_default=False,
                            )

    def test_default_context_deletion_blocked(self):
        """TC-04: Default context deletion is blocked by model-level guard."""
        with tenant_context(self.tenant):
            default_ctx = baker.make(
                "CostModelContext",
                name="default",
                display_name="Consumer",
                position=1,
                is_default=True,
            )
            from django.core.exceptions import ValidationError

            with self.assertRaises((ValidationError, IntegrityError)):
                default_ctx.delete()

    def test_non_default_context_deletion_allowed(self):
        """TC-05: Non-default context deletion is allowed."""
        with tenant_context(self.tenant):
            ctx = baker.make(
                "CostModelContext",
                name="provider",
                display_name="Provider",
                position=2,
                is_default=False,
            )
            ctx_uuid = ctx.uuid
            ctx.delete()
            from cost_models.models import CostModelContext

            self.assertFalse(CostModelContext.objects.filter(uuid=ctx_uuid).exists())


class CostModelMapContextTest(IamTestCase):
    """Test cases for CostModelMap multi-context support (TC-09/10)."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def test_costmodelmap_allows_multi_context_rows(self):
        """TC-09: Same provider with different contexts = OK."""
        with tenant_context(self.tenant):
            cost_model = baker.make("CostModel", source_type="OCP")
            ctx_consumer = baker.make(
                "CostModelContext", name="default", display_name="Consumer", position=1, is_default=True
            )
            ctx_provider = baker.make(
                "CostModelContext", name="provider", display_name="Provider", position=2, is_default=False
            )
            provider_uuid = uuid4()

            from cost_models.models import CostModelMap

            CostModelMap.objects.create(
                provider_uuid=provider_uuid,
                cost_model=cost_model,
                cost_model_context=ctx_consumer,
            )
            CostModelMap.objects.create(
                provider_uuid=provider_uuid,
                cost_model=cost_model,
                cost_model_context=ctx_provider,
            )
            self.assertEqual(CostModelMap.objects.filter(provider_uuid=provider_uuid).count(), 2)

    def test_costmodelmap_rejects_duplicate_provider_context(self):
        """TC-10: Same provider + same context = rejected by unique_together."""
        with tenant_context(self.tenant):
            cost_model = baker.make("CostModel", source_type="OCP")
            ctx = baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)
            provider_uuid = uuid4()

            from cost_models.models import CostModelMap

            CostModelMap.objects.create(
                provider_uuid=provider_uuid,
                cost_model=cost_model,
                cost_model_context=ctx,
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    CostModelMap.objects.create(
                        provider_uuid=provider_uuid,
                        cost_model=cost_model,
                        cost_model_context=ctx,
                    )


class CostModelManagerContextTest(IamTestCase):
    """Test cases for CostModelManager context-aware operations (TC-06 through TC-08)."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def test_update_provider_uuids_different_contexts_ok(self):
        """TC-06: Same provider + different contexts = OK via manager."""
        with tenant_context(self.tenant):
            from cost_models.cost_model_manager import CostModelManager

            ctx_consumer = baker.make(
                "CostModelContext", name="default", display_name="Consumer", position=1, is_default=True
            )
            ctx_provider = baker.make(
                "CostModelContext", name="provider", display_name="Provider", position=2, is_default=False
            )

            cm1 = baker.make("CostModel", source_type="OCP")
            cm2 = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())

            mgr1 = CostModelManager(cost_model_uuid=cm1.uuid)
            mgr1.update_provider_uuids([provider_uuid], cost_model_context=ctx_consumer)

            mgr2 = CostModelManager(cost_model_uuid=cm2.uuid)
            mgr2.update_provider_uuids([provider_uuid], cost_model_context=ctx_provider)

            from cost_models.models import CostModelMap

            self.assertEqual(CostModelMap.objects.filter(provider_uuid=provider_uuid).count(), 2)

    def test_update_provider_uuids_same_context_rejected(self):
        """TC-07: Same provider + same context = rejected with descriptive error."""
        with tenant_context(self.tenant):
            from cost_models.cost_model_manager import CostModelException
            from cost_models.cost_model_manager import CostModelManager

            ctx = baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            cm1 = baker.make("CostModel", source_type="OCP")
            cm2 = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())

            mgr1 = CostModelManager(cost_model_uuid=cm1.uuid)
            mgr1.update_provider_uuids([provider_uuid], cost_model_context=ctx)

            mgr2 = CostModelManager(cost_model_uuid=cm2.uuid)
            with self.assertRaises(CostModelException):
                mgr2.update_provider_uuids([provider_uuid], cost_model_context=ctx)

    def test_update_provider_uuids_default_context_when_none(self):
        """TC-08: When cost_model_context is None, manager resolves tenant's default."""
        with tenant_context(self.tenant):
            from cost_models.cost_model_manager import CostModelManager

            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            cm = baker.make("CostModel", source_type="OCP")
            provider_uuid = str(uuid4())

            mgr = CostModelManager(cost_model_uuid=cm.uuid)
            mgr.update_provider_uuids([provider_uuid])

            from cost_models.models import CostModelMap

            mapping = CostModelMap.objects.get(provider_uuid=provider_uuid)
            self.assertIsNotNone(mapping.cost_model_context)
            self.assertEqual(mapping.cost_model_context.name, "default")


class CostModelContextSerializerTest(IamTestCase):
    """Test cases for CostModelContextSerializer (TC-11 through TC-15, TC-XX)."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

    def test_context_serializer_valid_data(self):
        """TC-11: Serializer accepts valid name/display_name."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)
            from cost_models.serializers import CostModelContextSerializer

            data = {"name": "provider", "display_name": "Provider"}
            serializer = CostModelContextSerializer(data=data)
            self.assertTrue(serializer.is_valid(raise_exception=True))

    def test_context_serializer_max_three(self):
        """TC-12: Serializer rejects 4th context."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="c1", display_name="C1", position=1, is_default=True)
            baker.make("CostModelContext", name="c2", display_name="C2", position=2, is_default=False)
            baker.make("CostModelContext", name="c3", display_name="C3", position=3, is_default=False)

            from cost_models.serializers import CostModelContextSerializer

            data = {"name": "c4", "display_name": "C4"}
            serializer = CostModelContextSerializer(data=data)
            self.assertFalse(serializer.is_valid())

    def test_context_serializer_default_not_deletable(self):
        """TC-13: Default context cannot be deleted via serializer/model guard."""
        with tenant_context(self.tenant):
            default_ctx = baker.make(
                "CostModelContext", name="default", display_name="Consumer", position=1, is_default=True
            )
            from django.core.exceptions import ValidationError

            with self.assertRaises((ValidationError, IntegrityError)):
                default_ctx.delete()

    def test_cost_model_serializer_with_context(self):
        """TC-14: CostModelSerializer accepts source_uuids + cost_model_context."""
        with tenant_context(self.tenant):
            ctx = baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            from cost_models.serializers import CostModelSerializer

            data = {
                "name": "test",
                "description": "test",
                "source_type": "OCP",
                "rates": [],
                "source_uuids": [],
                "cost_model_context": str(ctx.uuid),
            }
            serializer = CostModelSerializer(data=data, context=self.request_context)
            self.assertTrue(serializer.is_valid(raise_exception=True))

    def test_cost_model_serializer_default_context(self):
        """TC-15: Missing cost_model_context defaults to tenant's default."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            from cost_models.serializers import CostModelSerializer

            data = {
                "name": "test",
                "description": "test",
                "source_type": "OCP",
                "rates": [],
                "source_uuids": [],
            }
            serializer = CostModelSerializer(data=data, context=self.request_context)
            self.assertTrue(serializer.is_valid(raise_exception=True))

    def test_cost_model_assignment_without_context_field(self):
        """TC-XX: POST/PUT without cost_model_context field succeeds with default context (backward-compat)."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            from cost_models.serializers import CostModelSerializer

            data = {
                "name": "backward compat test",
                "description": "no context field",
                "source_type": "OCP",
                "rates": [],
                "source_uuids": [],
            }
            serializer = CostModelSerializer(data=data, context=self.request_context)
            valid = serializer.is_valid()
            self.assertTrue(valid)
            instance = serializer.save()
            self.assertIsNotNone(instance)

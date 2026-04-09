#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for cost model context write-freeze behavior.

Verifies that when the Unleash flag is active:
  - Context creation is blocked (serializer guard)
  - Context update is blocked (serializer guard)
  - Context read/list is allowed
  - Pipeline context-tagged writes are skipped
  - When flag is off, all writes proceed normally
"""
from unittest.mock import patch

from django.urls import reverse
from django_tenants.utils import tenant_context
from model_bakery import baker
from rest_framework import status
from rest_framework.test import APIClient

from api.iam.test.iam_test_case import IamTestCase
from cost_models.models import CostModelContext
from masu.processor.tasks import update_cost_model_costs

FREEZE_FLAG_PATH = "cost_models.serializers.is_context_writes_disabled"
PIPELINE_FREEZE_FLAG_PATH = "masu.processor.tasks.is_context_writes_disabled"


class ContextWriteFreezeAPITest(IamTestCase):
    """Test write-freeze guards on the CostModelContext API."""

    def setUp(self):
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()
            self.default_ctx = baker.make(
                "CostModelContext", name="default", display_name="Consumer", position=1, is_default=True
            )
        self.client = APIClient()

    def test_create_blocked_when_freeze_active(self):
        """Context creation returns 400 when write freeze is active."""
        with patch(FREEZE_FLAG_PATH, return_value=True):
            url = reverse("cost-model-contexts-list")
            response = self.client.post(
                url,
                data={"name": "provider", "display_name": "Provider"},
                format="json",
                **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("frozen", str(response.data).lower())

    def test_update_blocked_when_freeze_active(self):
        """Context update returns 400 when write freeze is active."""
        with patch(FREEZE_FLAG_PATH, return_value=True):
            with tenant_context(self.tenant):
                ctx_uuid = self.default_ctx.uuid
            detail_url = reverse("cost-model-contexts-detail", kwargs={"uuid": ctx_uuid})
            response = self.client.put(
                detail_url,
                data={"name": "default", "display_name": "Consumer (Updated)"},
                format="json",
                **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("frozen", str(response.data).lower())

    def test_read_allowed_when_freeze_active(self):
        """Context list/detail remains accessible during write freeze."""
        with patch(FREEZE_FLAG_PATH, return_value=True):
            url = reverse("cost-model-contexts-list")
            response = self.client.get(url, **self.headers)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_allowed_when_freeze_off(self):
        """Context creation proceeds when flag is disabled."""
        with patch(FREEZE_FLAG_PATH, return_value=False):
            url = reverse("cost-model-contexts-list")
            response = self.client.post(
                url,
                data={"name": "provider", "display_name": "Provider"},
                format="json",
                **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class PipelineWriteFreezeTest(IamTestCase):
    """Test write-freeze guard on the update_cost_model_costs task."""

    def test_pipeline_skips_context_tagged_writes_when_freeze_active(self):
        """Pipeline returns early without running updater when freeze is on."""
        with patch(PIPELINE_FREEZE_FLAG_PATH, return_value=True), \
             patch("masu.processor.tasks.CostModelCostUpdater") as mock_updater, \
             patch("masu.processor.tasks.WorkerCache"):
            update_cost_model_costs(
                self.schema_name,
                "test-provider-uuid",
                start_date="2026-01-01",
                end_date="2026-01-31",
                synchronous=True,
                cost_model_context="consumer",
            )
            mock_updater.assert_not_called()

    def test_pipeline_runs_when_freeze_off(self):
        """Pipeline executes updater when freeze flag is off."""
        with patch(PIPELINE_FREEZE_FLAG_PATH, return_value=False), \
             patch("masu.processor.tasks.CostModelCostUpdater") as mock_updater, \
             patch("masu.processor.tasks.WorkerCache"), \
             patch("masu.processor.tasks.Provider"):
            mock_updater.return_value.update_cost_model_costs.return_value = None
            update_cost_model_costs(
                self.schema_name,
                "test-provider-uuid",
                start_date="2026-01-01",
                end_date="2026-01-31",
                synchronous=True,
                cost_model_context="consumer",
            )
            mock_updater.assert_called_once()

    def test_pipeline_runs_without_context_when_no_db_contexts(self):
        """Pipeline runs for None context (legacy path) without triggering the freeze guard."""
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()

        with patch(PIPELINE_FREEZE_FLAG_PATH) as mock_flag, \
             patch("masu.processor.tasks.CostModelCostUpdater") as mock_updater, \
             patch("masu.processor.tasks.WorkerCache"), \
             patch("masu.processor.tasks.Provider"):
            mock_updater.return_value.update_cost_model_costs.return_value = None
            update_cost_model_costs(
                self.schema_name,
                "test-provider-uuid",
                start_date="2026-01-01",
                end_date="2026-01-31",
                synchronous=True,
                cost_model_context=None,
            )
            mock_flag.assert_not_called()
            mock_updater.assert_called_once()

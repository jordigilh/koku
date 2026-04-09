#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for CostModelContextViewSet CRUD API (TC-85)."""
from django.urls import reverse
from django_tenants.utils import tenant_context
from model_bakery import baker
from rest_framework import status
from rest_framework.test import APIClient

from api.iam.test.iam_test_case import IamTestCase
from cost_models.models import CostModelContext


class CostModelContextViewSetTest(IamTestCase):
    """Test the CostModelContext CRUD API (TC-85)."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        with tenant_context(self.tenant):
            CostModelContext.objects.all().update(is_default=False)
            CostModelContext.objects.all().delete()
        self.client = APIClient()

    def test_context_crud_api_lifecycle(self):
        """TC-85: Create/list/update/delete context via API."""
        with tenant_context(self.tenant):
            baker.make("CostModelContext", name="default", display_name="Consumer", position=1, is_default=True)

            url = reverse("cost-model-contexts-list")

            # CREATE
            response = self.client.post(
                url,
                data={"name": "provider", "display_name": "Provider"},
                format="json",
                **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            ctx_uuid = response.data["uuid"]

            # LIST
            response = self.client.get(url, **self.headers)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            names = [item["name"] for item in response.data["data"]]
            self.assertIn("provider", names)

            # UPDATE
            detail_url = reverse("cost-model-contexts-detail", kwargs={"uuid": ctx_uuid})
            response = self.client.put(
                detail_url,
                data={"name": "provider", "display_name": "Provider (Updated)"},
                format="json",
                **self.headers,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["display_name"], "Provider (Updated)")

            # DELETE
            response = self.client.delete(detail_url, **self.headers)
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

            # Verify deleted
            response = self.client.get(detail_url, **self.headers)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

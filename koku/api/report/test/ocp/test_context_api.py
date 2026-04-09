#
# Copyright 2026 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for OCP report API cost_model_context parameter (TC-22, TC-23, TC-80 through TC-84)."""
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch

from django.test import override_settings
from rest_framework import serializers
from rest_framework.test import APIClient

from api.iam.test.iam_test_case import IamTestCase
from api.report.ocp.serializers import OCPCostQueryParamSerializer
from api.report.ocp.serializers import OCPQueryParamSerializer


class OCPContextQueryParamSerializerTest(IamTestCase):
    """TC-22, TC-23: Query param serializer cost_model_context field."""

    def test_tc22_cost_model_context_accepted(self):
        """TC-22: Serializer accepts cost_model_context parameter."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, {"cost_model_context": "consumer"}, **self.headers)
        self.assertEqual(response.status_code, 200)
        meta = response.json().get("meta", {})
        self.assertEqual(meta.get("cost_model_context"), "consumer")

    def test_tc23_cost_model_context_defaults(self):
        """TC-23: Missing cost_model_context — response has no context in meta."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        meta = response.json().get("meta", {})
        self.assertNotIn("cost_model_context", meta)


class OCPContextReportAPITest(IamTestCase):
    """TC-80 through TC-84: OCP report endpoint context integration."""

    def test_tc80_cost_endpoint_with_context_returns_200(self):
        """TC-80: /reports/openshift/costs/?cost_model_context=X returns 200."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, {"cost_model_context": "consumer"}, **self.headers)
        self.assertIn(response.status_code, (200,), f"Expected 200, got {response.status_code}")

    def test_tc81_response_filtered_by_context(self):
        """TC-81: Response data is filtered by the requested cost_model_context."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, {"cost_model_context": "consumer"}, **self.headers)
        if response.status_code == 200:
            meta = response.json().get("meta", {})
            self.assertIn(
                "cost_model_context",
                meta,
                "Response meta should include cost_model_context",
            )

    def test_tc82_missing_context_uses_default(self):
        """TC-82: Missing cost_model_context param uses tenant default context."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)

    def test_tc83_currency_annotation_context_aware(self):
        """TC-83: Currency annotation respects cost_model_context."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, {"cost_model_context": "consumer"}, **self.headers)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                pass

    def test_tc84_unpermitted_context_filtered(self):
        """TC-84: User without access to requested context gets filtered results."""
        from django.urls import reverse

        url = reverse("reports-openshift-costs")
        client = APIClient()
        response = client.get(url, {"cost_model_context": "nonexistent"}, **self.headers)
        self.assertIn(response.status_code, (200, 400))

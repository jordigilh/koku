#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for authentication token extractors."""
import json
import unittest
from base64 import b64encode, b64decode
from unittest.mock import Mock, patch

from sources.auth_extractors import (
    XRHIdentityExtractor,
    OAuthBearerExtractor,
    MockTokenExtractor
)
from sources.auth_token import (
    NormalizedAuthToken,
    IdentityType,
    TokenExtractionError,
    TokenExtractionContext
)


class TestXRHIdentityExtractor(unittest.TestCase):
    """Test XRHIdentityExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = XRHIdentityExtractor()

    def test_can_extract_x_rh_identity(self):
        """Test extractor can handle x-rh-identity format."""
        context = TokenExtractionContext(source_format="x-rh-identity")
        self.assertTrue(self.extractor.can_extract(context))

    def test_cannot_extract_other_formats(self):
        """Test extractor rejects other formats."""
        context = TokenExtractionContext(source_format="oauth-bearer")
        self.assertFalse(self.extractor.can_extract(context))

    def test_extract_user_token(self):
        """Test extracting a standard user token."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "test_user",
                    "email": "test@example.com",
                    "is_org_admin": True
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=encoded_token
        )

        result = self.extractor.extract(context)

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.account_number, "12345")
        self.assertEqual(result.org_id, "67890")
        self.assertEqual(result.username, "test_user")
        self.assertEqual(result.email, "test@example.com")
        self.assertEqual(result.identity_type, IdentityType.USER)
        self.assertTrue(result.is_org_admin)
        self.assertTrue(result.is_cost_management_entitled)

    def test_extract_service_account_token(self):
        """Test extracting a service account token."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "ServiceAccount",
                "service_account": {
                    "username": "service_user"
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=encoded_token
        )

        result = self.extractor.extract(context)

        self.assertEqual(result.identity_type, IdentityType.SERVICE_ACCOUNT)
        self.assertEqual(result.username, "service_user")
        self.assertEqual(result.email, "")  # Service accounts have no email

    def test_extract_system_token_with_cluster(self):
        """Test extracting a system token with cluster ID."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "System",
                "auth_type": "uhc-auth",
                "system": {
                    "cluster_id": "cluster-123"
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=encoded_token
        )

        result = self.extractor.extract(context)

        self.assertEqual(result.identity_type, IdentityType.SYSTEM)
        self.assertEqual(result.username, "cluster-123")
        self.assertEqual(result.auth_type, "uhc-auth")
        self.assertEqual(result.cluster_id, "cluster-123")

    def test_extract_no_raw_token(self):
        """Test extraction fails when no raw token provided."""
        context = TokenExtractionContext(source_format="x-rh-identity")

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_invalid_base64(self):
        """Test extraction fails with invalid base64."""
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token="invalid_base64!!!"
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_invalid_json(self):
        """Test extraction fails with invalid JSON."""
        invalid_json = b64encode(b"invalid json").decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=invalid_json
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_missing_required_fields(self):
        """Test extraction fails when required fields are missing."""
        identity_data = {
            "identity": {
                # Missing account_number and org_id
                "type": "User",
                "user": {
                    "username": "test_user"
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=encoded_token
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_unknown_identity_type(self):
        """Test extraction with unknown identity type defaults to User."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "UnknownType",
                "user": {
                    "username": "test_user",
                    "email": "test@example.com"
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token=encoded_token
        )

        result = self.extractor.extract(context)
        self.assertEqual(result.identity_type, IdentityType.USER)


class TestOAuthBearerExtractor(unittest.TestCase):
    """Test OAuthBearerExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = OAuthBearerExtractor()

    def test_can_extract_oauth_bearer(self):
        """Test extractor can handle oauth-bearer format."""
        context = TokenExtractionContext(source_format="oauth-bearer")
        self.assertTrue(self.extractor.can_extract(context))

    def test_cannot_extract_other_formats(self):
        """Test extractor rejects other formats."""
        context = TokenExtractionContext(source_format="x-rh-identity")
        self.assertFalse(self.extractor.can_extract(context))

    def test_extract_user_jwt_token(self):
        """Test extracting a user JWT token."""
        # Create a simple JWT-like token (without signature verification)
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "sub": "user123",
            "preferred_username": "john.doe",
            "email": "john.doe@example.com",
            "account_number": "12345",
            "org_id": "67890",
            "groups": ["cost-management-users"],
            "scope": "cost-management:read"
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.username, "john.doe")
        self.assertEqual(result.email, "john.doe@example.com")
        self.assertEqual(result.account_number, "12345")
        self.assertEqual(result.org_id, "67890")
        self.assertEqual(result.identity_type, IdentityType.USER)
        self.assertEqual(result.auth_type, "oauth")

    def test_extract_service_account_jwt_token(self):
        """Test extracting a service account JWT token."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "sub": "service-account-123",
            "client_id": "cost-mgmt-service",
            "account_id": "99999",
            "tenant_id": "tenant-123",
            "token_type": "service"
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)

        self.assertEqual(result.identity_type, IdentityType.SERVICE_ACCOUNT)
        self.assertEqual(result.username, "service-account-123")
        self.assertEqual(result.account_number, "99999")
        self.assertEqual(result.org_id, "tenant-123")

    def test_extract_admin_user_jwt_token(self):
        """Test extracting an admin user JWT token."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "sub": "admin123",
            "preferred_username": "admin.user",
            "email": "admin@example.com",
            "organization_id": "org-456",
            "account_number": "54321",
            "groups": ["cost-management-admin", "administrators"],
            "is_org_admin": True
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)

        self.assertTrue(result.is_org_admin)
        self.assertEqual(result.username, "admin.user")
        self.assertEqual(result.org_id, "org-456")

    def test_extract_no_raw_token(self):
        """Test extraction fails when no raw token provided."""
        context = TokenExtractionContext(source_format="oauth-bearer")

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_invalid_jwt_format(self):
        """Test extraction fails with invalid JWT format."""
        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token="invalid.jwt"  # Missing third part
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_invalid_base64_in_jwt(self):
        """Test extraction fails with invalid base64 in JWT."""
        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token="invalid_b64.invalid_b64.signature"
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_missing_username_claims(self):
        """Test extraction fails when no username claims found."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "account_number": "12345",
            "org_id": "67890"
            # No username-related claims
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        with self.assertRaises(TokenExtractionError):
            self.extractor.extract(context)

    def test_extract_fallback_account_and_org(self):
        """Test extraction with fallback account and org values."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "preferred_username": "test_user"
            # No account_number or org_id
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)

        # Should use fallback values
        self.assertEqual(result.account_number, "oauth-account")
        self.assertEqual(result.org_id, "oauth-org")

    def test_entitlement_detection_from_scopes(self):
        """Test entitlement detection from OAuth scopes."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "preferred_username": "test_user",
            "account_number": "12345",
            "org_id": "67890",
            "scope": "cost-management:read cost-management:write"
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)
        self.assertTrue(result.is_cost_management_entitled)

    def test_admin_detection_from_groups(self):
        """Test admin detection from groups/roles."""
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "preferred_username": "test_user",
            "account_number": "12345",
            "org_id": "67890",
            "groups": ["cost-management-admin"]
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token=jwt_token
        )

        result = self.extractor.extract(context)
        self.assertTrue(result.is_org_admin)


class TestMockTokenExtractor(unittest.TestCase):
    """Test MockTokenExtractor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.extractor = MockTokenExtractor()

    def test_can_extract_mock(self):
        """Test extractor can handle mock format."""
        context = TokenExtractionContext(source_format="mock")
        self.assertTrue(self.extractor.can_extract(context))

    def test_cannot_extract_other_formats(self):
        """Test extractor rejects other formats."""
        context = TokenExtractionContext(source_format="oauth-bearer")
        self.assertFalse(self.extractor.can_extract(context))

    def test_extract_mock_token(self):
        """Test extracting a mock token."""
        context = TokenExtractionContext(source_format="mock")

        result = self.extractor.extract(context)

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.account_number, "10001")
        self.assertEqual(result.org_id, "1234567")
        self.assertEqual(result.username, "user_dev")
        self.assertEqual(result.email, "user_dev@example.com")
        self.assertEqual(result.identity_type, IdentityType.USER)
        self.assertFalse(result.is_org_admin)
        self.assertTrue(result.is_cost_management_entitled)
        self.assertEqual(result.auth_type, "mock")


class TestExtractorIntegration(unittest.TestCase):
    """Integration tests for extractors."""

    def test_extractor_selection_by_format(self):
        """Test that extractors properly select based on format."""
        xrh_extractor = XRHIdentityExtractor()
        oauth_extractor = OAuthBearerExtractor()
        mock_extractor = MockTokenExtractor()

        xrh_context = TokenExtractionContext(source_format="x-rh-identity")
        oauth_context = TokenExtractionContext(source_format="oauth-bearer")
        mock_context = TokenExtractionContext(source_format="mock")

        # Each extractor should only handle its own format
        self.assertTrue(xrh_extractor.can_extract(xrh_context))
        self.assertFalse(xrh_extractor.can_extract(oauth_context))
        self.assertFalse(xrh_extractor.can_extract(mock_context))

        self.assertFalse(oauth_extractor.can_extract(xrh_context))
        self.assertTrue(oauth_extractor.can_extract(oauth_context))
        self.assertFalse(oauth_extractor.can_extract(mock_context))

        self.assertFalse(mock_extractor.can_extract(xrh_context))
        self.assertFalse(mock_extractor.can_extract(oauth_context))
        self.assertTrue(mock_extractor.can_extract(mock_context))


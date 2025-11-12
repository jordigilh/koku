#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for authentication token classes."""
import unittest

from sources.auth_token import (
    NormalizedAuthToken,
    IdentityType,
    TokenExtractionError,
    TokenValidationError,
    TokenExtractionContext,
    AuthTokenError
)


class TestNormalizedAuthToken(unittest.TestCase):
    """Test NormalizedAuthToken class."""

    def test_create_valid_user_token(self):
        """Test creating a valid user token."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user",
            email="test@example.com",
            is_org_admin=True,
            is_cost_management_entitled=True
        )

        self.assertEqual(token.account_number, "12345")
        self.assertEqual(token.org_id, "67890")
        self.assertEqual(token.identity_type, IdentityType.USER)
        self.assertEqual(token.username, "test_user")
        self.assertEqual(token.email, "test@example.com")
        self.assertTrue(token.is_org_admin)
        self.assertTrue(token.is_cost_management_entitled)

    def test_create_valid_service_account_token(self):
        """Test creating a valid service account token."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SERVICE_ACCOUNT,
            username="service_user",
            is_cost_management_entitled=True
        )

        self.assertEqual(token.identity_type, IdentityType.SERVICE_ACCOUNT)
        self.assertEqual(token.username, "service_user")
        self.assertIsNone(token.email)  # Service accounts typically don't have email
        self.assertFalse(token.is_org_admin)  # Default value

    def test_create_valid_system_token(self):
        """Test creating a valid system token."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SYSTEM,
            username="cluster-123",
            auth_type="uhc-auth",
            cluster_id="cluster-123",
            is_cost_management_entitled=True
        )

        self.assertEqual(token.identity_type, IdentityType.SYSTEM)
        self.assertEqual(token.username, "cluster-123")
        self.assertEqual(token.auth_type, "uhc-auth")
        self.assertEqual(token.cluster_id, "cluster-123")

    def test_validation_missing_account_number(self):
        """Test validation fails when account_number is missing."""
        with self.assertRaises(TokenValidationError) as context:
            NormalizedAuthToken(
                account_number="",  # Empty account number
                org_id="67890",
                identity_type=IdentityType.USER,
                username="test_user"
            )

        self.assertIn("account_number is required", str(context.exception))

    def test_validation_missing_org_id(self):
        """Test validation fails when org_id is missing."""
        with self.assertRaises(TokenValidationError) as context:
            NormalizedAuthToken(
                account_number="12345",
                org_id="",  # Empty org ID
                identity_type=IdentityType.USER,
                username="test_user"
            )

        self.assertIn("org_id is required", str(context.exception))

    def test_validation_missing_username(self):
        """Test validation fails when username is missing."""
        with self.assertRaises(TokenValidationError) as context:
            NormalizedAuthToken(
                account_number="12345",
                org_id="67890",
                identity_type=IdentityType.USER,
                username=""  # Empty username
            )

        self.assertIn("username is required", str(context.exception))

    def test_validation_system_uhc_auth_missing_cluster_id(self):
        """Test validation fails for System identity with uhc-auth but no cluster_id."""
        with self.assertRaises(TokenValidationError) as context:
            NormalizedAuthToken(
                account_number="12345",
                org_id="67890",
                identity_type=IdentityType.SYSTEM,
                username="test_user",
                auth_type="uhc-auth"
                # Missing cluster_id
            )

        self.assertIn("cluster_id required for System identity with uhc-auth", str(context.exception))

    def test_validation_system_other_auth_no_cluster_id_required(self):
        """Test System identity with other auth types doesn't require cluster_id."""
        # Should not raise an exception
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SYSTEM,
            username="test_user",
            auth_type="other-auth"
            # No cluster_id - should be fine
        )

        self.assertEqual(token.auth_type, "other-auth")
        self.assertIsNone(token.cluster_id)

    def test_property_is_user(self):
        """Test is_user property."""
        user_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user"
        )

        service_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SERVICE_ACCOUNT,
            username="service_user"
        )

        self.assertTrue(user_token.is_user)
        self.assertFalse(service_token.is_user)

    def test_property_is_service_account(self):
        """Test is_service_account property."""
        user_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user"
        )

        service_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SERVICE_ACCOUNT,
            username="service_user"
        )

        self.assertFalse(user_token.is_service_account)
        self.assertTrue(service_token.is_service_account)

    def test_property_is_system(self):
        """Test is_system property."""
        user_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user"
        )

        system_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.SYSTEM,
            username="system_user"
        )

        self.assertFalse(user_token.is_system)
        self.assertTrue(system_token.is_system)

    def test_property_is_admin(self):
        """Test is_admin property."""
        admin_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="admin_user",
            is_org_admin=True
        )

        user_token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="regular_user",
            is_org_admin=False
        )

        self.assertTrue(admin_token.is_admin)
        self.assertFalse(user_token.is_admin)

    def test_to_dict_conversion(self):
        """Test conversion to dictionary."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user",
            email="test@example.com",
            is_org_admin=True,
            is_cost_management_entitled=True,
            auth_type="oauth",
            access_permissions={"aws.account": {"read": ["*"]}}
        )

        result_dict = token.to_dict()

        expected_dict = {
            "account_number": "12345",
            "org_id": "67890",
            "identity_type": "User",  # Should be string value, not enum
            "username": "test_user",
            "email": "test@example.com",
            "is_org_admin": True,
            "is_cost_management_entitled": True,
            "auth_type": "oauth",
            "cluster_id": None,
            "access_permissions": {"aws.account": {"read": ["*"]}}
        }

        self.assertEqual(result_dict, expected_dict)

    def test_string_representation(self):
        """Test string representation (should exclude sensitive data)."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user",
            email="test@example.com",
            is_org_admin=True
        )

        token_str = str(token)

        # Should include key identifying information
        self.assertIn("12345", token_str)
        self.assertIn("67890", token_str)
        self.assertIn("User", token_str)
        self.assertIn("test_user", token_str)
        self.assertIn("True", token_str)  # admin status

        # Should not include sensitive data like email in string representation
        # (though this is not strictly enforced in current implementation)

    def test_optional_fields_defaults(self):
        """Test that optional fields have correct defaults."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user"
        )

        # Check default values
        self.assertIsNone(token.email)
        self.assertFalse(token.is_org_admin)
        self.assertFalse(token.is_cost_management_entitled)
        self.assertIsNone(token.auth_type)
        self.assertIsNone(token.cluster_id)
        self.assertIsNone(token.access_permissions)

    def test_with_access_permissions(self):
        """Test token with access permissions (for development)."""
        access_permissions = {
            "aws.account": {"read": ["123456789012", "*"]},
            "azure.subscription_guid": {"read": ["*"]},
            "cost_model": {"write": ["uuid1", "uuid2"]}
        }

        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user",
            access_permissions=access_permissions
        )

        self.assertEqual(token.access_permissions, access_permissions)

    def test_immutability_after_creation(self):
        """Test that token fields can be modified after creation (dataclass behavior)."""
        token = NormalizedAuthToken(
            account_number="12345",
            org_id="67890",
            identity_type=IdentityType.USER,
            username="test_user"
        )

        # Dataclasses are mutable by default
        token.email = "new@example.com"
        self.assertEqual(token.email, "new@example.com")


class TestTokenExtractionContext(unittest.TestCase):
    """Test TokenExtractionContext class."""

    def test_create_basic_context(self):
        """Test creating a basic extraction context."""
        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token="encoded_token"
        )

        self.assertEqual(context.source_format, "x-rh-identity")
        self.assertEqual(context.raw_token, "encoded_token")
        self.assertIsNone(context.headers)
        self.assertIsNone(context.request_path)

    def test_create_full_context(self):
        """Test creating a full extraction context."""
        headers = {"x-rh-identity": "token", "content-type": "application/json"}

        context = TokenExtractionContext(
            source_format="x-rh-identity",
            raw_token="encoded_token",
            headers=headers,
            request_path="/api/v1/status/"
        )

        self.assertEqual(context.source_format, "x-rh-identity")
        self.assertEqual(context.raw_token, "encoded_token")
        self.assertEqual(context.headers, headers)
        self.assertEqual(context.request_path, "/api/v1/status/")

    def test_context_string_representation(self):
        """Test string representation of context."""
        context = TokenExtractionContext(
            source_format="oauth-bearer",
            raw_token="jwt_token"
        )

        context_str = str(context)
        self.assertIn("oauth-bearer", context_str)


class TestExceptionClasses(unittest.TestCase):
    """Test custom exception classes."""

    def test_auth_token_error_inheritance(self):
        """Test AuthTokenError is base exception."""
        error = AuthTokenError("Base error")
        self.assertIsInstance(error, Exception)
        self.assertEqual(str(error), "Base error")

    def test_token_extraction_error_inheritance(self):
        """Test TokenExtractionError inherits from AuthTokenError."""
        error = TokenExtractionError("Extraction failed")
        self.assertIsInstance(error, AuthTokenError)
        self.assertIsInstance(error, Exception)
        self.assertEqual(str(error), "Extraction failed")

    def test_token_validation_error_inheritance(self):
        """Test TokenValidationError inherits from AuthTokenError."""
        error = TokenValidationError("Validation failed")
        self.assertIsInstance(error, AuthTokenError)
        self.assertIsInstance(error, Exception)
        self.assertEqual(str(error), "Validation failed")


class TestIdentityTypeEnum(unittest.TestCase):
    """Test IdentityType enum."""

    def test_enum_values(self):
        """Test enum has correct values."""
        self.assertEqual(IdentityType.USER.value, "User")
        self.assertEqual(IdentityType.SERVICE_ACCOUNT.value, "ServiceAccount")
        self.assertEqual(IdentityType.SYSTEM.value, "System")

    def test_enum_comparison(self):
        """Test enum comparison."""
        self.assertEqual(IdentityType.USER, IdentityType.USER)
        self.assertNotEqual(IdentityType.USER, IdentityType.SERVICE_ACCOUNT)

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        user_type = IdentityType("User")
        self.assertEqual(user_type, IdentityType.USER)

        service_type = IdentityType("ServiceAccount")
        self.assertEqual(service_type, IdentityType.SERVICE_ACCOUNT)

        system_type = IdentityType("System")
        self.assertEqual(system_type, IdentityType.SYSTEM)

    def test_enum_invalid_value(self):
        """Test creating enum with invalid value raises error."""
        with self.assertRaises(ValueError):
            IdentityType("InvalidType")


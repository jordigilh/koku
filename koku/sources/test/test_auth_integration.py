#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Integration tests for authentication token abstraction system."""
import json
import unittest
from base64 import b64encode
from unittest.mock import Mock, patch, MagicMock

from sources.auth_config import AuthProvider, AuthConfig
from sources.auth_factory import AuthTokenFactory
from sources.auth_headers import AuthHeaderManager
from sources.auth_token import NormalizedAuthToken, IdentityType


class TestAuthSystemIntegration(unittest.TestCase):
    """Integration tests for the complete auth system."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_settings = Mock()
        self.mock_settings.AUTH_PROVIDER = 'rhsso'


    def test_end_to_end_rhsso_token_processing(self):
        """Test complete RHSSO token processing flow."""
        # Create X-RH-Identity token
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "integration_user",
                    "email": "integration@example.com",
                    "is_org_admin": True,
                    "access": {
                        "aws.account": {"read": ["*"]},
                        "cost_model": {"write": ["uuid1"]}
                    }
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()

        with patch('sources.auth_config.settings', self.mock_settings):
            # Test configuration
            config = AuthConfig()
            self.assertEqual(config.provider, AuthProvider.RHSSO)

            # Test header manager
            header_manager = AuthHeaderManager(config)
            self.assertEqual(header_manager.get_request_header_name(), "X-Rh-Identity")
            self.assertEqual(header_manager.get_lowercase_header_name(), "x-rh-identity")

            # Test token factory
            factory = AuthTokenFactory(config)
            result = factory.create_token_from_raw(encoded_token, "x-rh-identity")

            # Verify complete extraction
            self.assertIsInstance(result, NormalizedAuthToken)
            self.assertEqual(result.username, "integration_user")
            self.assertEqual(result.email, "integration@example.com")
            self.assertEqual(result.account_number, "12345")
            self.assertEqual(result.org_id, "67890")
            self.assertEqual(result.identity_type, IdentityType.USER)
            self.assertTrue(result.is_org_admin)
            self.assertTrue(result.is_cost_management_entitled)
            self.assertIsNotNone(result.access_permissions)

    def test_end_to_end_oauth_token_processing(self):
        """Test complete OAuth token processing flow."""
        # Create JWT-like token
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "sub": "oauth_user_123",
            "preferred_username": "oauth.user",
            "email": "oauth@example.com",
            "account_number": "54321",
            "org_id": "98765",
            "groups": ["cost-management-admin"],
            "scope": "cost-management:read cost-management:write",
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        header_b64 = b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        jwt_token = f"{header_b64}.{payload_b64}.fake_signature"

        # Set OAuth configuration
        self.mock_settings.AUTH_PROVIDER = 'oauth'

        with patch('sources.auth_config.settings', self.mock_settings):
            # Test configuration
            config = AuthConfig()
            self.assertEqual(config.provider, AuthProvider.OAUTH)

            # Test header manager
            header_manager = AuthHeaderManager(config)
            self.assertEqual(header_manager.get_request_header_name(), "Authorization")
            self.assertEqual(header_manager.get_lowercase_header_name(), "authorization")

            # Test token factory
            factory = AuthTokenFactory(config)
            result = factory.create_token_from_raw(jwt_token, "oauth-bearer")

            # Verify complete extraction
            self.assertIsInstance(result, NormalizedAuthToken)
            self.assertEqual(result.username, "oauth.user")
            self.assertEqual(result.email, "oauth@example.com")
            self.assertEqual(result.account_number, "54321")
            self.assertEqual(result.org_id, "98765")
            self.assertEqual(result.identity_type, IdentityType.USER)
            self.assertTrue(result.is_org_admin)  # From groups
            self.assertTrue(result.is_cost_management_entitled)  # From scopes
            self.assertEqual(result.auth_type, "oauth")

    def test_provider_switching_integration(self):
        """Test switching between auth providers."""
        with patch('sources.auth_config.settings', self.mock_settings):
            # Start with RHSSO
            config = AuthConfig()
            header_manager = AuthHeaderManager(config)
            factory = AuthTokenFactory(config)

            # Test RHSSO configuration
            self.assertEqual(config.provider, AuthProvider.RHSSO)
            self.assertEqual(header_manager.get_request_header_name(), "X-Rh-Identity")
            rhsso_formats = factory.get_supported_formats()

            # Switch to OAuth
            self.mock_settings.AUTH_PROVIDER = 'oauth'
            config.reload_settings()
            header_manager.reload_configuration()
            factory.reload_configuration()

            # Test OAuth configuration
            self.assertEqual(config.provider, AuthProvider.OAUTH)
            self.assertEqual(header_manager.get_request_header_name(), "Authorization")
            oauth_formats = factory.get_supported_formats()

            # Both should support the same basic formats but with different preferences
            self.assertIn("x-rh-identity", rhsso_formats)
            self.assertIn("oauth-bearer", oauth_formats)

    def test_header_consistency_across_components(self):
        """Test that all components return consistent header names."""
        with patch('sources.auth_config.settings', self.mock_settings):
            # Test with RHSSO
            config = AuthConfig()
            header_manager = AuthHeaderManager(config)

            # Import API functions
            from sources.api import get_auth_header_name, get_auth_header_lowercase_name
            from api.common import get_identity_header

            # All should return consistent values
            request_header = header_manager.get_request_header_name()
            api_header = get_auth_header_name()
            common_identity = get_identity_header()
            lowercase_header = get_auth_header_lowercase_name()

            self.assertEqual(request_header, "X-Rh-Identity")
            self.assertEqual(api_header, "X-Rh-Identity")
            self.assertEqual(common_identity, "HTTP_X_RH_IDENTITY")
            self.assertEqual(lowercase_header, "x-rh-identity")

            # Switch to OAuth and test again
            self.mock_settings.AUTH_PROVIDER = 'oauth'
            config.reload_settings()
            header_manager.reload_configuration()

            request_header = header_manager.get_request_header_name()
            api_header = get_auth_header_name()
            common_identity = get_identity_header()
            lowercase_header = get_auth_header_lowercase_name()

            self.assertEqual(request_header, "Authorization")
            self.assertEqual(api_header, "Authorization")
            self.assertEqual(common_identity, "HTTP_AUTHORIZATION")
            self.assertEqual(lowercase_header, "authorization")

    def test_outgoing_headers_integration(self):
        """Test outgoing header creation consistency."""
        with patch('sources.auth_config.settings', self.mock_settings):
            config = AuthConfig()
            header_manager = AuthHeaderManager(config)

            # Test RHSSO outgoing headers
            self.assertEqual(config.provider, AuthProvider.RHSSO)
            rhsso_headers = header_manager.create_outgoing_headers("test_token")
            expected_rhsso = {"x-rh-identity": "test_token"}
            self.assertEqual(rhsso_headers, expected_rhsso)

            # Switch to OAuth
            self.mock_settings.AUTH_PROVIDER = 'oauth'
            config.reload_settings()
            header_manager.reload_configuration()

            oauth_headers = header_manager.create_outgoing_headers("test_token")
            expected_oauth = {"Authorization": "Bearer test_token"}
            self.assertEqual(oauth_headers, expected_oauth)

    def test_cors_headers_integration(self):
        """Test CORS headers consistency."""
        with patch('sources.auth_config.settings', self.mock_settings):
            config = AuthConfig()
            header_manager = AuthHeaderManager(config)

            # Test RHSSO CORS headers
            self.assertEqual(config.provider, AuthProvider.RHSSO)
            rhsso_cors = header_manager.get_cors_headers()
            self.assertIn("x-rh-identity", rhsso_cors)
            self.assertIn("HTTP_X_RH_IDENTITY", rhsso_cors)

            # Switch to OAuth
            self.mock_settings.AUTH_PROVIDER = 'oauth'
            config.reload_settings()
            header_manager.reload_configuration()

            oauth_cors = header_manager.get_cors_headers()
            self.assertIn("authorization", oauth_cors)
            self.assertIn("Authorization", oauth_cors)

    def test_auto_detection_integration(self):
        """Test auto-detection integration with different providers."""
        with patch('sources.auth_config.settings', self.mock_settings):
            # Enable auto-detection


            config = AuthConfig()
            factory = AuthTokenFactory(config)

            # Create mock request with X-RH-Identity header
            mock_request = Mock()
            mock_request.headers = {"X-Rh-Identity": "token"}

            with patch.object(factory, '_has_xrh_identity_header', return_value=True):
                detected_format = factory._detect_format_from_request(mock_request)
                self.assertEqual(detected_format, "x-rh-identity")

            # Create mock request with OAuth header
            mock_request.headers = {"Authorization": "Bearer token"}

            with patch.object(factory, '_has_xrh_identity_header', return_value=False):
                detected_format = factory._detect_format_from_request(mock_request)
                self.assertEqual(detected_format, "oauth-bearer")

    def test_error_handling_integration(self):
        """Test error handling across the system."""
        with patch('sources.auth_config.settings', self.mock_settings):
            config = AuthConfig()
            factory = AuthTokenFactory(config)

            # Test with malformed X-RH-Identity token
            with self.assertRaises(Exception):
                factory.create_token_from_raw("malformed_token", "x-rh-identity")

            # Test with unsupported format
            with self.assertRaises(Exception):
                factory.create_token_from_raw("token", "unsupported-format")

            # Test with no token
            with self.assertRaises(Exception):
                factory.create_token_from_raw("", "x-rh-identity")

    def test_development_mode_integration(self):
        """Test integration with development/mock mode."""
        self.mock_settings.AUTH_PROVIDER = 'mock'

        with patch('sources.auth_config.settings', self.mock_settings):
            config = AuthConfig()
            factory = AuthTokenFactory(config)

            # Test mock token creation
            result = factory.create_token_from_raw("mock-token", "mock")

            self.assertIsInstance(result, NormalizedAuthToken)
            self.assertEqual(result.username, "user_dev")
            self.assertEqual(result.account_number, "10001")
            self.assertEqual(result.org_id, "1234567")
            self.assertEqual(result.auth_type, "mock")
            self.assertTrue(result.is_cost_management_entitled)

    def test_legacy_compatibility_integration(self):
        """Test that legacy code still works with new abstraction."""
        with patch('sources.auth_config.settings', self.mock_settings):
            # Test that legacy constants work
            from api.common import RH_IDENTITY_HEADER, CACHE_RH_IDENTITY_HEADER

            # These should be callable functions now that return dynamic values
            self.assertTrue(callable(RH_IDENTITY_HEADER))
            self.assertTrue(callable(CACHE_RH_IDENTITY_HEADER))

            # Test getting values
            identity_header = RH_IDENTITY_HEADER()
            cache_header = CACHE_RH_IDENTITY_HEADER()

            self.assertEqual(identity_header, "HTTP_X_RH_IDENTITY")
            self.assertEqual(cache_header, "X_RH_IDENTITY")

            # Switch to OAuth and test again
            self.mock_settings.AUTH_PROVIDER = 'oauth'

            identity_header = RH_IDENTITY_HEADER()
            cache_header = CACHE_RH_IDENTITY_HEADER()

            self.assertEqual(identity_header, "HTTP_AUTHORIZATION")
            self.assertEqual(cache_header, "AUTHORIZATION")


class TestRealWorldScenarios(unittest.TestCase):
    """Test real-world usage scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_settings = Mock()

    def test_middleware_integration_scenario(self):
        """Test scenario simulating Django middleware usage."""
        # Simulate middleware processing a request
        self.mock_settings.AUTH_PROVIDER = 'rhsso'


        with patch('sources.auth_config.settings', self.mock_settings):
            # Create mock request with X-RH-Identity header
            identity_data = {
                "identity": {
                    "account_number": "12345",
                    "org_id": "67890",
                    "type": "User",
                    "user": {
                        "username": "middleware_user",
                        "email": "middleware@example.com",
                        "is_org_admin": False
                    }
                },
                "entitlements": {
                    "cost_management": {
                        "is_entitled": True
                    }
                }
            }

            encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
            mock_request = Mock()
            mock_request.headers = {"X-Rh-Identity": encoded_token}
            mock_request.META = {"HTTP_X_RH_IDENTITY": encoded_token}

            # Test that middleware would get the right header name
            from api.common import get_identity_header
            header_name = get_identity_header()
            self.assertEqual(header_name, "HTTP_X_RH_IDENTITY")

            # Test token extraction
            from sources.auth_factory import create_normalized_token_from_request

            with patch('sources.auth_factory.get_auth_header_value', return_value=encoded_token):
                token = create_normalized_token_from_request(mock_request)
                self.assertEqual(token.username, "middleware_user")

    def test_api_view_caching_scenario(self):
        """Test scenario simulating API view caching."""
        self.mock_settings.AUTH_PROVIDER = 'oauth'

        with patch('sources.auth_config.settings', self.mock_settings):
            # Test that API views get the right cache header
            from api.common import get_cache_identity_header
            cache_header = get_cache_identity_header()
            self.assertEqual(cache_header, "AUTHORIZATION")

            # Simulate decorator usage
            def mock_decorator(header_name):
                return lambda func: func

            # This simulates @method_decorator(vary_on_headers(get_cache_identity_header()))
            decorator = mock_decorator(cache_header)
            self.assertIsNotNone(decorator)

    def test_kafka_integration_scenario(self):
        """Test scenario simulating Kafka message processing."""
        self.mock_settings.AUTH_PROVIDER = 'rhsso'

        with patch('sources.auth_config.settings', self.mock_settings):
            # Test Kafka header name
            from sources.api import get_auth_header_lowercase_name
            kafka_header = get_auth_header_lowercase_name()
            self.assertEqual(kafka_header, "x-rh-identity")

            # Simulate Kafka message headers
            identity_data = {
                "identity": {
                    "account_number": "12345",
                    "org_id": "67890",
                    "type": "User",
                    "user": {"username": "kafka_user"}
                },
                "entitlements": {
                    "cost_management": {"is_entitled": True}
                }
            }

            encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
            kafka_headers = {kafka_header: encoded_token}

            # Test token extraction from Kafka headers
            from sources.auth_factory import AuthTokenFactory
            factory = AuthTokenFactory()
            token = factory.create_token_from_headers(kafka_headers, "x-rh-identity")
            self.assertEqual(token.username, "kafka_user")

    def test_outgoing_http_requests_scenario(self):
        """Test scenario for making outgoing HTTP requests."""
        self.mock_settings.AUTH_PROVIDER = 'oauth'

        with patch('sources.auth_config.settings', self.mock_settings):
            from sources.auth_headers import get_auth_header_manager

            header_manager = get_auth_header_manager()

            # Create headers for outgoing request
            outgoing_headers = header_manager.create_outgoing_headers("jwt_token_123")

            # Should use Bearer format for OAuth
            expected = {"Authorization": "Bearer jwt_token_123"}
            self.assertEqual(outgoing_headers, expected)

            # Simulate HTTP request
            import requests
            with patch('requests.get') as mock_get:
                mock_get.return_value.status_code = 200

                # This simulates making an authenticated request
                response = requests.get(
                    "https://api.example.com/data",
                    headers=outgoing_headers
                )

                mock_get.assert_called_with(
                    "https://api.example.com/data",
                    headers={"Authorization": "Bearer jwt_token_123"}
                )

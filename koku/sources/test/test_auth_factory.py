#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for authentication token factory."""
import json
import unittest
from base64 import b64encode
from unittest.mock import Mock, patch

from sources.auth_config import AuthProvider
from sources.auth_factory import (
    AuthTokenFactory,
    get_token_factory,
    create_normalized_token_from_request
)
from sources.auth_token import (
    NormalizedAuthToken,
    IdentityType,
    TokenExtractionError,
    TokenExtractionContext
)


class TestAuthTokenFactory(unittest.TestCase):
    """Test AuthTokenFactory class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.should_auto_detect_format.return_value = True
        self.mock_config.get_fallback_extractor_classes.return_value = [
            "XRHIdentityExtractor", "OAuthBearerExtractor", "MockTokenExtractor"
        ]
        self.mock_config.get_custom_extractor.return_value = None

    def test_factory_initialization_with_config(self):
        """Test factory initialization with custom config."""
        factory = AuthTokenFactory(self.mock_config)
        self.assertEqual(factory._config, self.mock_config)

    @patch('sources.auth_factory.get_auth_config')
    def test_factory_initialization_without_config(self, mock_get_config):
        """Test factory initialization without custom config uses global."""
        mock_get_config.return_value = self.mock_config
        factory = AuthTokenFactory()
        self.assertEqual(factory._config, self.mock_config)

    def test_extractor_initialization_auto_detect_mode(self):
        """Test extractor initialization in auto-detect mode."""
        self.mock_config.should_auto_detect_format.return_value = True
        self.mock_config.get_fallback_extractor_classes.return_value = [
            "XRHIdentityExtractor", "OAuthBearerExtractor", "MockTokenExtractor"
        ]

        factory = AuthTokenFactory(self.mock_config)

        # Should have all three extractors
        self.assertEqual(len(factory._extractors), 3)
        extractor_names = [e.__class__.__name__ for e in factory._extractors]
        self.assertIn("XRHIdentityExtractor", extractor_names)
        self.assertIn("OAuthBearerExtractor", extractor_names)
        self.assertIn("MockTokenExtractor", extractor_names)

    def test_extractor_initialization_strict_mode(self):
        """Test extractor initialization in strict mode."""
        self.mock_config.should_auto_detect_format.return_value = False
        self.mock_config.get_preferred_extractor_classes.return_value = [
            "OAuthBearerExtractor", "MockTokenExtractor"
        ]

        factory = AuthTokenFactory(self.mock_config)

        # Should only have preferred extractors
        self.assertEqual(len(factory._extractors), 2)
        extractor_names = [e.__class__.__name__ for e in factory._extractors]
        self.assertIn("OAuthBearerExtractor", extractor_names)
        self.assertIn("MockTokenExtractor", extractor_names)
        self.assertNotIn("XRHIdentityExtractor", extractor_names)

    def test_create_token_from_raw_x_rh_identity(self):
        """Test creating token from raw X-RH-Identity token."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
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
        factory = AuthTokenFactory(self.mock_config)

        result = factory.create_token_from_raw(encoded_token, "x-rh-identity")

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.username, "test_user")
        self.assertEqual(result.account_number, "12345")

    def test_create_token_from_raw_mock(self):
        """Test creating token from raw mock token."""
        factory = AuthTokenFactory(self.mock_config)

        result = factory.create_token_from_raw("mock-token", "mock")

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.username, "user_dev")
        self.assertEqual(result.auth_type, "mock")

    def test_create_token_from_headers_dict(self):
        """Test creating token from headers dictionary."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "test_user"
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()
        headers = {"x-rh-identity": encoded_token}

        factory = AuthTokenFactory(self.mock_config)
        result = factory.create_token_from_headers(headers, "x-rh-identity")

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.username, "test_user")

    def test_create_token_from_request(self):
        """Test creating token from Django request."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "test_user"
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

        # Mock the header detection
        with patch.object(AuthTokenFactory, '_has_xrh_identity_header', return_value=True):
            with patch.object(AuthTokenFactory, '_extract_raw_token', return_value=encoded_token):
                factory = AuthTokenFactory(self.mock_config)
                result = factory.create_token_from_request(mock_request, "x-rh-identity")

        self.assertIsInstance(result, NormalizedAuthToken)
        self.assertEqual(result.username, "test_user")

    def test_create_token_unsupported_format(self):
        """Test creation fails with unsupported format."""
        factory = AuthTokenFactory(self.mock_config)

        with self.assertRaises(TokenExtractionError):
            factory.create_token_from_raw("token", "unsupported-format")

    def test_format_detection_rhsso_preference(self):
        """Test format detection with RHSSO preference."""
        self.mock_config.provider = AuthProvider.RHSSO
        self.mock_config.should_auto_detect_format.return_value = True

        factory = AuthTokenFactory(self.mock_config)
        mock_request = Mock()
        mock_request.headers = {"X-Rh-Identity": "token"}

        with patch.object(factory, '_has_xrh_identity_header', return_value=True):
            result = factory._detect_format_from_request(mock_request)
            self.assertEqual(result, "x-rh-identity")

    def test_format_detection_oauth_preference(self):
        """Test format detection with OAuth preference."""
        self.mock_config.provider = AuthProvider.OAUTH
        self.mock_config.should_auto_detect_format.return_value = True

        factory = AuthTokenFactory(self.mock_config)
        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer token"}

        result = factory._detect_format_from_request(mock_request)
        self.assertEqual(result, "oauth-bearer")

    def test_format_detection_no_auto_detect(self):
        """Test format detection when auto-detect is disabled."""
        self.mock_config.should_auto_detect_format.return_value = False
        self.mock_config.get_default_format_for_provider.return_value = "oauth-bearer"

        factory = AuthTokenFactory(self.mock_config)
        mock_request = Mock()

        result = factory._detect_format_from_request(mock_request)
        self.assertEqual(result, "oauth-bearer")

    def test_format_detection_from_headers_dict(self):
        """Test format detection from headers dictionary."""
        factory = AuthTokenFactory(self.mock_config)

        # X-RH-Identity header
        headers_xrh = {"x-rh-identity": "token"}
        result = factory._detect_format_from_headers(headers_xrh)
        self.assertEqual(result, "x-rh-identity")

        # OAuth Bearer header
        headers_oauth = {"Authorization": "Bearer token"}
        result = factory._detect_format_from_headers(headers_oauth)
        self.assertEqual(result, "oauth-bearer")

    def test_extractor_finding(self):
        """Test finding appropriate extractor for context."""
        factory = AuthTokenFactory(self.mock_config)

        # Test X-RH-Identity context
        xrh_context = TokenExtractionContext(source_format="x-rh-identity")
        extractor = factory._find_extractor(xrh_context)
        self.assertIsNotNone(extractor)
        self.assertEqual(extractor.__class__.__name__, "XRHIdentityExtractor")

        # Test OAuth context
        oauth_context = TokenExtractionContext(source_format="oauth-bearer")
        extractor = factory._find_extractor(oauth_context)
        self.assertIsNotNone(extractor)
        self.assertEqual(extractor.__class__.__name__, "OAuthBearerExtractor")

        # Test unsupported context
        unsupported_context = TokenExtractionContext(source_format="unsupported")
        extractor = factory._find_extractor(unsupported_context)
        self.assertIsNone(extractor)

    def test_supported_formats(self):
        """Test getting supported formats."""
        factory = AuthTokenFactory(self.mock_config)
        formats = factory.get_supported_formats()

        self.assertIn("x-rh-identity", formats)
        self.assertIn("oauth-bearer", formats)
        self.assertIn("mock", formats)

    def test_configuration_reload(self):
        """Test configuration reloading."""
        factory = AuthTokenFactory(self.mock_config)
        initial_extractors = len(factory._extractors)

        # Change config to return different extractors
        self.mock_config.get_fallback_extractor_classes.return_value = ["MockTokenExtractor"]

        factory.reload_configuration()

        # Should have fewer extractors now
        self.assertEqual(len(factory._extractors), 1)
        self.assertEqual(factory._extractors[0].__class__.__name__, "MockTokenExtractor")

    def test_get_configuration(self):
        """Test getting current configuration."""
        factory = AuthTokenFactory(self.mock_config)
        config_str = factory.get_configuration()
        self.assertEqual(config_str, str(self.mock_config))

    def test_custom_extractor_initialization(self):
        """Test initialization with custom extractors."""
        # Mock a custom extractor
        mock_custom_extractor = Mock()
        mock_custom_extractor.return_value = Mock()

        self.mock_config.get_custom_extractor.side_effect = lambda provider: (
            mock_custom_extractor if provider == AuthProvider.OAUTH else None
        )

        factory = AuthTokenFactory(self.mock_config)

        # Should include the custom extractor
        self.mock_config.get_custom_extractor.assert_called()


class TestFactoryGlobalFunctions(unittest.TestCase):
    """Test global factory functions."""

    def test_get_token_factory(self):
        """Test get_token_factory returns global instance."""
        factory1 = get_token_factory()
        factory2 = get_token_factory()

        self.assertIsInstance(factory1, AuthTokenFactory)
        self.assertIs(factory1, factory2)  # Should be same instance

    @patch('sources.auth_factory.get_token_factory')
    def test_create_normalized_token_from_request(self, mock_get_factory):
        """Test convenience function for creating tokens from requests."""
        mock_factory = Mock()
        mock_token = Mock()
        mock_factory.create_token_from_request.return_value = mock_token
        mock_get_factory.return_value = mock_factory

        mock_request = Mock()
        result = create_normalized_token_from_request(mock_request, "x-rh-identity")

        self.assertEqual(result, mock_token)
        mock_factory.create_token_from_request.assert_called_once_with(mock_request, "x-rh-identity")


class TestFactoryIntegration(unittest.TestCase):
    """Integration tests for factory with real components."""

    def test_end_to_end_x_rh_identity_extraction(self):
        """Test end-to-end extraction of X-RH-Identity token."""
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "integration_user",
                    "email": "integration@example.com",
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

        # Use real factory with minimal mocking
        with patch('sources.auth_factory.get_auth_config') as mock_get_config:
            mock_config = Mock()
            mock_config.should_auto_detect_format.return_value = True
            mock_config.get_fallback_extractor_classes.return_value = [
                "XRHIdentityExtractor", "OAuthBearerExtractor", "MockTokenExtractor"
            ]
            mock_config.get_custom_extractor.return_value = None
            mock_get_config.return_value = mock_config

            factory = AuthTokenFactory()
            result = factory.create_token_from_raw(encoded_token, "x-rh-identity")

            # Verify complete extraction
            self.assertEqual(result.username, "integration_user")
            self.assertEqual(result.email, "integration@example.com")
            self.assertEqual(result.account_number, "12345")
            self.assertEqual(result.org_id, "67890")
            self.assertEqual(result.identity_type, IdentityType.USER)
            self.assertFalse(result.is_org_admin)
            self.assertTrue(result.is_cost_management_entitled)

    def test_factory_error_handling(self):
        """Test factory error handling with malformed tokens."""
        with patch('sources.auth_factory.get_auth_config') as mock_get_config:
            mock_config = Mock()
            mock_config.should_auto_detect_format.return_value = True
            mock_config.get_fallback_extractor_classes.return_value = ["XRHIdentityExtractor"]
            mock_config.get_custom_extractor.return_value = None
            mock_get_config.return_value = mock_config

            factory = AuthTokenFactory()

            # Test with malformed token
            with self.assertRaises(TokenExtractionError):
                factory.create_token_from_raw("malformed_token", "x-rh-identity")

            # Test with unsupported format
            with self.assertRaises(TokenExtractionError):
                factory.create_token_from_raw("token", "unsupported-format")


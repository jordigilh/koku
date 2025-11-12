#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for authentication header management."""
import unittest
from unittest.mock import Mock, patch

from sources.auth_config import AuthProvider
from sources.auth_headers import (
    AuthHeaderManager,
    get_auth_header_manager,
    get_request_header_name,
    get_django_meta_header_name,
    get_cache_header_name,
    get_lowercase_header_name,
    get_cors_headers,
    reload_header_configuration
)


class TestAuthHeaderManager(unittest.TestCase):
    """Test AuthHeaderManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.header_manager = AuthHeaderManager(self.mock_config)

    def test_rhsso_request_header_name(self):
        """Test RHSSO request header name."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.get_request_header_name()
        self.assertEqual(result, "X-Rh-Identity")

    def test_oauth_request_header_name(self):
        """Test OAuth request header name."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.get_request_header_name()
        self.assertEqual(result, "Authorization")

    def test_mock_request_header_name(self):
        """Test mock request header name."""
        self.mock_config.provider = AuthProvider.MOCK
        result = self.header_manager.get_request_header_name()
        self.assertEqual(result, "X-Rh-Identity")

    def test_rhsso_django_meta_header_name(self):
        """Test RHSSO Django META header name."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.get_django_meta_header_name()
        self.assertEqual(result, "HTTP_X_RH_IDENTITY")

    def test_oauth_django_meta_header_name(self):
        """Test OAuth Django META header name."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.get_django_meta_header_name()
        self.assertEqual(result, "HTTP_AUTHORIZATION")

    def test_rhsso_cache_header_name(self):
        """Test RHSSO cache header name."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.get_cache_header_name()
        self.assertEqual(result, "X_RH_IDENTITY")

    def test_oauth_cache_header_name(self):
        """Test OAuth cache header name."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.get_cache_header_name()
        self.assertEqual(result, "AUTHORIZATION")

    def test_rhsso_lowercase_header_name(self):
        """Test RHSSO lowercase header name."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.get_lowercase_header_name()
        self.assertEqual(result, "x-rh-identity")

    def test_oauth_lowercase_header_name(self):
        """Test OAuth lowercase header name."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.get_lowercase_header_name()
        self.assertEqual(result, "authorization")

    def test_rhsso_cors_headers(self):
        """Test RHSSO CORS headers."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.get_cors_headers()
        expected = ["x-rh-identity", "HTTP_X_RH_IDENTITY"]
        self.assertEqual(result, expected)

    def test_oauth_cors_headers(self):
        """Test OAuth CORS headers."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.get_cors_headers()
        expected = ["authorization", "Authorization"]
        self.assertEqual(result, expected)

    def test_unknown_provider_fallback(self):
        """Test unknown provider falls back to RHSSO."""
        self.mock_config.provider = "unknown"

        # All methods should fall back to RHSSO behavior
        self.assertEqual(self.header_manager.get_request_header_name(), "X-Rh-Identity")
        self.assertEqual(self.header_manager.get_django_meta_header_name(), "HTTP_X_RH_IDENTITY")
        self.assertEqual(self.header_manager.get_cache_header_name(), "X_RH_IDENTITY")
        self.assertEqual(self.header_manager.get_lowercase_header_name(), "x-rh-identity")

    def test_rhsso_outgoing_headers(self):
        """Test RHSSO outgoing headers creation."""
        self.mock_config.provider = AuthProvider.RHSSO
        result = self.header_manager.create_outgoing_headers("test_token")
        expected = {"x-rh-identity": "test_token"}
        self.assertEqual(result, expected)

    def test_oauth_outgoing_headers(self):
        """Test OAuth outgoing headers creation."""
        self.mock_config.provider = AuthProvider.OAUTH
        result = self.header_manager.create_outgoing_headers("test_token")
        expected = {"Authorization": "Bearer test_token"}
        self.assertEqual(result, expected)

    def test_header_value_extraction_oauth(self):
        """Test OAuth header value extraction."""
        self.mock_config.provider = AuthProvider.OAUTH

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer test_token"}

        with patch('sources.auth_headers.get_auth_header_value') as mock_get_value:
            mock_get_value.return_value = "Bearer test_token"

            result = self.header_manager.get_header_value_from_request(mock_request)
            self.assertEqual(result, "test_token")  # Should strip "Bearer " prefix

    def test_header_value_extraction_rhsso(self):
        """Test RHSSO header value extraction."""
        self.mock_config.provider = AuthProvider.RHSSO

        mock_request = Mock()
        mock_request.headers = {"X-Rh-Identity": "encoded_token"}

        with patch('sources.auth_headers.get_auth_header_value') as mock_get_value:
            mock_get_value.return_value = "encoded_token"

            result = self.header_manager.get_header_value_from_request(mock_request)
            self.assertEqual(result, "encoded_token")  # Should return full value

    def test_header_presence_check(self):
        """Test header presence checking."""
        mock_request = Mock()

        # Header present
        with patch.object(self.header_manager, 'get_header_value_from_request', return_value="token"):
            self.assertTrue(self.header_manager.is_header_present(mock_request))

        # Header not present
        with patch.object(self.header_manager, 'get_header_value_from_request', return_value=None):
            self.assertFalse(self.header_manager.is_header_present(mock_request))

    def test_reload_configuration(self):
        """Test configuration reloading."""
        mock_config = Mock()
        header_manager = AuthHeaderManager(mock_config)

        header_manager.reload_configuration()
        mock_config.reload_settings.assert_called_once()


class TestAuthHeaderGlobalFunctions(unittest.TestCase):
    """Test global auth header functions."""

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_get_request_header_name(self, mock_get_manager):
        """Test global get_request_header_name function."""
        mock_manager = Mock()
        mock_manager.get_request_header_name.return_value = "Authorization"
        mock_get_manager.return_value = mock_manager

        result = get_request_header_name()
        self.assertEqual(result, "Authorization")
        mock_manager.get_request_header_name.assert_called_once()

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_get_django_meta_header_name(self, mock_get_manager):
        """Test global get_django_meta_header_name function."""
        mock_manager = Mock()
        mock_manager.get_django_meta_header_name.return_value = "HTTP_AUTHORIZATION"
        mock_get_manager.return_value = mock_manager

        result = get_django_meta_header_name()
        self.assertEqual(result, "HTTP_AUTHORIZATION")

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_get_cache_header_name(self, mock_get_manager):
        """Test global get_cache_header_name function."""
        mock_manager = Mock()
        mock_manager.get_cache_header_name.return_value = "AUTHORIZATION"
        mock_get_manager.return_value = mock_manager

        result = get_cache_header_name()
        self.assertEqual(result, "AUTHORIZATION")

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_get_lowercase_header_name(self, mock_get_manager):
        """Test global get_lowercase_header_name function."""
        mock_manager = Mock()
        mock_manager.get_lowercase_header_name.return_value = "authorization"
        mock_get_manager.return_value = mock_manager

        result = get_lowercase_header_name()
        self.assertEqual(result, "authorization")

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_get_cors_headers(self, mock_get_manager):
        """Test global get_cors_headers function."""
        mock_manager = Mock()
        mock_manager.get_cors_headers.return_value = ["authorization", "Authorization"]
        mock_get_manager.return_value = mock_manager

        result = get_cors_headers()
        self.assertEqual(result, ["authorization", "Authorization"])

    @patch('sources.auth_headers.get_auth_header_manager')
    def test_reload_header_configuration(self, mock_get_manager):
        """Test global reload_header_configuration function."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        reload_header_configuration()
        mock_manager.reload_configuration.assert_called_once()

    def test_global_manager_instance(self):
        """Test that global manager instance is properly initialized."""
        manager = get_auth_header_manager()
        self.assertIsInstance(manager, AuthHeaderManager)

        # Should return the same instance on subsequent calls
        manager2 = get_auth_header_manager()
        self.assertIs(manager, manager2)


class TestAuthHeaderManagerIntegration(unittest.TestCase):
    """Integration tests for AuthHeaderManager with real config."""

    def test_provider_switching_integration(self):
        """Test header manager with actual config switching."""
        with patch('sources.auth_headers.get_auth_config') as mock_get_config:
            # Create a real config mock that can switch providers
            mock_config = Mock()
            mock_config.provider = AuthProvider.RHSSO
            mock_get_config.return_value = mock_config

            manager = AuthHeaderManager()

            # Test RHSSO
            self.assertEqual(manager.get_request_header_name(), "X-Rh-Identity")
            self.assertEqual(manager.get_lowercase_header_name(), "x-rh-identity")

            # Switch to OAuth
            mock_config.provider = AuthProvider.OAUTH

            # Test OAuth
            self.assertEqual(manager.get_request_header_name(), "Authorization")
            self.assertEqual(manager.get_lowercase_header_name(), "authorization")

    def test_outgoing_headers_consistency(self):
        """Test that outgoing headers are consistent with header names."""
        mock_config = Mock()
        manager = AuthHeaderManager(mock_config)

        # RHSSO consistency
        mock_config.provider = AuthProvider.RHSSO
        outgoing = manager.create_outgoing_headers("token")
        lowercase = manager.get_lowercase_header_name()
        self.assertIn(lowercase, outgoing)

        # OAuth consistency
        mock_config.provider = AuthProvider.OAUTH
        outgoing = manager.create_outgoing_headers("token")
        request_header = manager.get_request_header_name()
        self.assertIn(request_header, outgoing)


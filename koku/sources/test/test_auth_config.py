#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Tests for authentication configuration."""
import unittest
from unittest.mock import Mock, patch

from sources.auth_config import AuthConfig, AuthProvider, get_auth_config, reload_auth_config


class TestAuthConfig(unittest.TestCase):
    """Test AuthConfig class."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = AuthConfig()

    @patch('sources.auth_config.settings')
    def test_default_provider(self, mock_settings):
        """Test default auth provider is RHSSO."""
        mock_settings.AUTH_PROVIDER = 'rhsso'


        config = AuthConfig()
        self.assertEqual(config.provider, AuthProvider.RHSSO)

    @patch('sources.auth_config.settings')
    def test_oauth_provider(self, mock_settings):
        """Test OAuth provider configuration."""
        mock_settings.AUTH_PROVIDER = 'oauth'


        config = AuthConfig()
        self.assertEqual(config.provider, AuthProvider.OAUTH)

    @patch('sources.auth_config.settings')
    def test_mock_provider(self, mock_settings):
        """Test mock provider configuration."""
        mock_settings.AUTH_PROVIDER = 'mock'


        config = AuthConfig()
        self.assertEqual(config.provider, AuthProvider.MOCK)

    @patch('sources.auth_config.settings')
    def test_invalid_provider_fallback(self, mock_settings):
        """Test invalid provider falls back to default."""
        mock_settings.AUTH_PROVIDER = 'invalid_provider'


        config = AuthConfig()
        self.assertEqual(config.provider, AuthProvider.RHSSO)  # Should fallback to default

    def test_provider_preferences_rhsso(self):
        """Test RHSSO provider extractor preferences."""
        with patch.object(self.config, 'provider', AuthProvider.RHSSO):
            extractors = self.config.get_preferred_extractor_classes()
            self.assertEqual(extractors, ["XRHIdentityExtractor", "MockTokenExtractor"])

    def test_provider_preferences_oauth(self):
        """Test OAuth provider extractor preferences."""
        with patch.object(self.config, 'provider', AuthProvider.OAUTH):
            extractors = self.config.get_preferred_extractor_classes()
            self.assertEqual(extractors, ["OAuthBearerExtractor", "MockTokenExtractor"])

    def test_provider_preferences_mock(self):
        """Test mock provider extractor preferences."""
        with patch.object(self.config, 'provider', AuthProvider.MOCK):
            extractors = self.config.get_preferred_extractor_classes()
            self.assertEqual(extractors, ["MockTokenExtractor", "XRHIdentityExtractor"])

    def test_default_formats(self):
        """Test default formats for each provider."""
        with patch.object(self.config, 'provider', AuthProvider.RHSSO):
            self.assertEqual(self.config.get_default_format_for_provider(), "x-rh-identity")

        with patch.object(self.config, 'provider', AuthProvider.OAUTH):
            self.assertEqual(self.config.get_default_format_for_provider(), "oauth-bearer")

        with patch.object(self.config, 'provider', AuthProvider.MOCK):
            self.assertEqual(self.config.get_default_format_for_provider(), "mock")

    def test_fallback_extractors_strict_mode(self):
        """Test fallback extractors in strict mode (no auto-detection)."""
        with patch.object(self.config, 'provider', AuthProvider.OAUTH):
            extractors = self.config.get_fallback_extractor_classes()
            expected = ["OAuthBearerExtractor", "MockTokenExtractor"]
            self.assertEqual(extractors, expected)

        with patch.object(self.config, 'provider', AuthProvider.RHSSO):
            extractors = self.config.get_fallback_extractor_classes()
            expected = ["XRHIdentityExtractor", "MockTokenExtractor"]
            self.assertEqual(extractors, expected)

    @patch('sources.auth_config.settings')
    def test_reload_settings(self, mock_settings):
        """Test configuration reloading."""
        # Start with RHSSO
        mock_settings.AUTH_PROVIDER = 'rhsso'
        config = AuthConfig()
        self.assertEqual(config.provider, AuthProvider.RHSSO)

        # Change to OAuth
        mock_settings.AUTH_PROVIDER = 'oauth'
        config.reload_settings()
        self.assertEqual(config.provider, AuthProvider.OAUTH)

    def test_custom_extractor_registration(self):
        """Test registering custom extractors."""
        mock_extractor = Mock()

        self.config.register_custom_extractor(AuthProvider.OAUTH, mock_extractor)
        retrieved = self.config.get_custom_extractor(AuthProvider.OAUTH)

        self.assertEqual(retrieved, mock_extractor)

    def test_global_config_instance(self):
        """Test global configuration instance functions."""
        global_config = get_auth_config()
        self.assertIsInstance(global_config, AuthConfig)

        # Test reload function
        with patch.object(global_config, 'reload_settings') as mock_reload:
            reload_auth_config()
            mock_reload.assert_called_once()

    def test_string_representation(self):
        """Test string representation of config."""
        with patch.object(self.config, 'provider', AuthProvider.OAUTH):
                config_str = str(self.config)
                self.assertIn('oauth', config_str)
                self.assertIn('strict_mode=True', config_str)

    @patch('sources.auth_config.LOG')
    def test_logging_on_invalid_provider(self, mock_log):
        """Test logging when invalid provider is configured."""
        with patch('sources.auth_config.settings') as mock_settings:
            mock_settings.AUTH_PROVIDER = 'invalid'

            config = AuthConfig()
            config._get_provider_from_settings()

            # Should log a warning
            mock_log.warning.assert_called()

    def test_django_not_available_fallback(self):
        """Test behavior when Django is not available."""
        with patch('sources.auth_config.settings', side_effect=ImportError):
            config = AuthConfig()
            # Should use default values
            self.assertEqual(config.provider, AuthProvider.RHSSO)

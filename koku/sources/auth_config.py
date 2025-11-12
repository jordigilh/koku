#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Authentication Configuration

This module manages authentication provider configuration and provides
a centralized way to control which authentication extractors are used.
"""
import logging
from enum import Enum
from typing import Dict, List, Type

LOG = logging.getLogger(__name__)


class AuthProvider(Enum):
    """Supported authentication providers."""
    RHSSO = "rhsso"      # Red Hat SSO (X-RH-Identity tokens)
    OAUTH = "oauth"      # OAuth Bearer tokens (JWT)
    MOCK = "mock"        # Mock tokens for development/testing


class AuthConfig:
    """
    Authentication configuration manager.

    This class manages the authentication provider configuration and
    provides methods to get the appropriate extractors based on settings.
    """

    # Default configuration
    DEFAULT_PROVIDER = AuthProvider.RHSSO

    def __init__(self):
        """Initialize auth configuration."""
        self._provider = None
        self._custom_extractors = {}

    @property
    def provider(self) -> AuthProvider:
        """Get the configured authentication provider."""
        if self._provider is None:
            self._provider = self._get_provider_from_settings()
        return self._provider



    def _get_provider_from_settings(self) -> AuthProvider:
        """Get the auth provider from Django settings."""
        try:
            from django.conf import settings
            provider_str = getattr(settings, 'AUTH_PROVIDER', self.DEFAULT_PROVIDER.value)

            try:
                return AuthProvider(provider_str.lower())
            except ValueError:
                LOG.warning(
                    f"Invalid AUTH_PROVIDER setting: '{provider_str}'. "
                    f"Valid options: {[p.value for p in AuthProvider]}. "
                    f"Using default: {self.DEFAULT_PROVIDER.value}"
                )
                return self.DEFAULT_PROVIDER

        except ImportError:
            # Django not available (e.g., in tests)
            LOG.debug("Django not available, using default auth provider")
            return self.DEFAULT_PROVIDER



    def get_preferred_extractor_classes(self) -> List[str]:
        """
        Get the preferred extractor classes based on configuration.

        Returns:
            List of extractor class names in order of preference
        """
        if self.provider == AuthProvider.RHSSO:
            return ["XRHIdentityExtractor", "MockTokenExtractor"]
        elif self.provider == AuthProvider.OAUTH:
            return ["OAuthBearerExtractor", "MockTokenExtractor"]
        elif self.provider == AuthProvider.MOCK:
            return ["MockTokenExtractor", "XRHIdentityExtractor"]
        else:
            # Fallback to all extractors if unknown provider
            return ["XRHIdentityExtractor", "OAuthBearerExtractor", "MockTokenExtractor"]

    def get_fallback_extractor_classes(self) -> List[str]:
        """
        Get fallback extractor classes (same as preferred - no auto-detection).

        Returns:
            List of preferred extractor class names for the configured provider
        """
        # No auto-detection: always use only preferred extractors
        return self.get_preferred_extractor_classes()



    def get_default_format_for_provider(self) -> str:
        """
        Get the default token format for the configured provider.

        Returns:
            Default token format string
        """
        if self.provider == AuthProvider.RHSSO:
            return "x-rh-identity"
        elif self.provider == AuthProvider.OAUTH:
            return "oauth-bearer"
        elif self.provider == AuthProvider.MOCK:
            return "mock"
        else:
            return "x-rh-identity"  # Safe fallback

    def register_custom_extractor(self, provider: AuthProvider, extractor_class: Type):
        """
        Register a custom extractor for a specific provider.

        Args:
            provider: The auth provider this extractor handles
            extractor_class: The extractor class to register
        """
        self._custom_extractors[provider] = extractor_class
        LOG.info(f"Registered custom extractor {extractor_class.__name__} for provider {provider.value}")

    def get_custom_extractor(self, provider: AuthProvider) -> Type:
        """Get custom extractor for a provider if registered."""
        return self._custom_extractors.get(provider)

    def reload_settings(self):
        """Reload configuration from Django settings."""
        self._provider = None
        # Force re-evaluation of settings
        self._provider = self._get_provider_from_settings()
        LOG.info(f"Auth configuration reloaded from settings: {self}")

    def __str__(self) -> str:
        """String representation of configuration."""
        return f"AuthConfig(provider={self.provider.value}, strict_mode=True)"


# Global configuration instance
_auth_config = AuthConfig()


def get_auth_config() -> AuthConfig:
    """Get the global authentication configuration instance."""
    return _auth_config


def reload_auth_config():
    """Reload the global authentication configuration."""
    get_auth_config().reload_settings()

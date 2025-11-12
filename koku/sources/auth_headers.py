#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Authentication Header Management

This module provides dynamic header name resolution based on the configured
authentication provider. This ensures that switching auth providers requires
zero code changes in the rest of the application.
"""
import logging
from typing import List, Dict, Any

from .auth_config import get_auth_config, AuthProvider

LOG = logging.getLogger(__name__)


class AuthHeaderManager:
    """
    Manages authentication headers dynamically based on configuration.

    This class provides a unified interface for header names across different
    authentication providers, eliminating hardcoded header references.
    """

    def __init__(self, auth_config=None):
        """Initialize with auth configuration."""
        self._config = auth_config or get_auth_config()

    def get_request_header_name(self) -> str:
        """
        Get the header name for incoming HTTP requests.

        Returns:
            str: Header name for request.headers access (e.g., "Authorization", "X-Rh-Identity")
        """
        if self._config.provider == AuthProvider.OAUTH:
            return "Authorization"
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return "X-Rh-Identity"
        else:
            # Fallback to X-RH-Identity for unknown providers
            return "X-Rh-Identity"

    def get_django_meta_header_name(self) -> str:
        """
        Get the header name for Django request.META access.

        Django automatically converts headers to META keys by:
        1. Converting to uppercase
        2. Replacing dashes with underscores
        3. Prefixing with 'HTTP_'

        Returns:
            str: Header name for request.META access (e.g., "HTTP_AUTHORIZATION", "HTTP_X_RH_IDENTITY")
        """
        if self._config.provider == AuthProvider.OAUTH:
            return "HTTP_AUTHORIZATION"
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return "HTTP_X_RH_IDENTITY"
        else:
            # Fallback
            return "HTTP_X_RH_IDENTITY"

    def get_cache_header_name(self) -> str:
        """
        Get the header name for HTTP caching (vary_on_headers).

        This is used for HTTP response caching to ensure responses
        vary based on the authentication header.

        Returns:
            str: Header name for caching (e.g., "AUTHORIZATION", "X_RH_IDENTITY")
        """
        if self._config.provider == AuthProvider.OAUTH:
            return "AUTHORIZATION"
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return "X_RH_IDENTITY"
        else:
            # Fallback
            return "X_RH_IDENTITY"

    def get_lowercase_header_name(self) -> str:
        """
        Get the lowercase header name for Kafka/dict access.

        Returns:
            str: Lowercase header name (e.g., "authorization", "x-rh-identity")
        """
        if self._config.provider == AuthProvider.OAUTH:
            return "authorization"
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return "x-rh-identity"
        else:
            # Fallback
            return "x-rh-identity"

    def get_cors_headers(self) -> List[str]:
        """
        Get the list of headers to allow in CORS configuration.

        Returns:
            List[str]: List of header names for CORS
        """
        if self._config.provider == AuthProvider.OAUTH:
            return ["authorization", "Authorization"]
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return ["x-rh-identity", "HTTP_X_RH_IDENTITY"]
        else:
            # Include both for compatibility during transition
            return ["x-rh-identity", "HTTP_X_RH_IDENTITY", "authorization", "Authorization"]

    def get_header_value_from_request(self, request) -> str:
        """
        Extract auth header value from Django request.

        Args:
            request: Django request object

        Returns:
            str: Header value or None if not found
        """
        # Use our existing abstraction
        from .api import get_auth_header_value

        if self._config.provider == AuthProvider.OAUTH:
            # For OAuth, we need to extract just the token part from "Bearer <token>"
            auth_value = get_auth_header_value(request, "standard")
            if auth_value and auth_value.startswith("Bearer "):
                return auth_value[7:]  # Remove "Bearer " prefix
            return auth_value
        else:
            # For X-RH-Identity, return the full value
            return get_auth_header_value(request, "standard")

    def get_header_value_from_meta(self, request) -> str:
        """
        Extract auth header value from Django request.META.

        Args:
            request: Django request object

        Returns:
            str: Header value or None if not found
        """
        from .api import get_auth_header_value

        if self._config.provider == AuthProvider.OAUTH:
            # For OAuth, extract from Authorization header in META
            auth_value = get_auth_header_value(request, "meta")
            if auth_value and auth_value.startswith("Bearer "):
                return auth_value[7:]  # Remove "Bearer " prefix
            return auth_value
        else:
            # For X-RH-Identity, return the full value
            return get_auth_header_value(request, "meta")

    def create_outgoing_headers(self, auth_token: str) -> Dict[str, str]:
        """
        Create headers for outgoing HTTP requests.

        Args:
            auth_token: The auth token value

        Returns:
            Dict[str, str]: Headers dictionary for outgoing requests
        """
        if self._config.provider == AuthProvider.OAUTH:
            return {"Authorization": f"Bearer {auth_token}"}
        elif self._config.provider in [AuthProvider.RHSSO, AuthProvider.MOCK]:
            return {"x-rh-identity": auth_token}
        else:
            # Fallback
            return {"x-rh-identity": auth_token}

    def is_header_present(self, request) -> bool:
        """
        Check if the auth header is present in the request.

        Args:
            request: Django request object

        Returns:
            bool: True if auth header is present
        """
        header_value = self.get_header_value_from_request(request)
        return header_value is not None

    def reload_configuration(self):
        """Reload configuration from settings."""
        self._config.reload_settings()
        LOG.info(f"Auth header manager reloaded: {self._config}")


# Global header manager instance
_header_manager = AuthHeaderManager()


def get_auth_header_manager() -> AuthHeaderManager:
    """Get the global auth header manager instance."""
    return _header_manager


def get_request_header_name() -> str:
    """Get the current auth header name for HTTP requests."""
    return get_auth_header_manager().get_request_header_name()


def get_django_meta_header_name() -> str:
    """Get the current auth header name for Django META access."""
    return get_auth_header_manager().get_django_meta_header_name()


def get_cache_header_name() -> str:
    """Get the current auth header name for HTTP caching."""
    return get_auth_header_manager().get_cache_header_name()


def get_lowercase_header_name() -> str:
    """Get the current auth header name in lowercase."""
    return get_auth_header_manager().get_lowercase_header_name()


def get_cors_headers() -> List[str]:
    """Get the list of headers for CORS configuration."""
    return get_auth_header_manager().get_cors_headers()


def reload_header_configuration():
    """Reload header configuration from settings."""
    get_auth_header_manager().reload_configuration()

#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Authentication Token Factory

This module provides the main factory for creating normalized authentication tokens
from various sources. It acts as the central coordinator for token extraction.
"""
import logging
from typing import List, Optional, Dict, Any, Union

from .auth_token import NormalizedAuthToken, TokenExtractionError, TokenExtractionContext
from .auth_extractors import (
    BaseTokenExtractor,
    XRHIdentityExtractor,
    OAuthBearerExtractor,
    MockTokenExtractor
)
from .auth_config import get_auth_config, AuthProvider
from .api import get_auth_header_value

LOG = logging.getLogger(__name__)


class AuthTokenFactory:
    """
    Factory for creating normalized authentication tokens from various sources.

    This factory:
    - Uses configuration to determine preferred auth provider
    - Automatically detects token format (when enabled)
    - Routes to appropriate extractor based on configuration
    - Provides unified error handling
    - Supports multiple auth providers
    """

    def __init__(self, auth_config=None):
        """
        Initialize the factory with configured extractors.

        Args:
            auth_config: Optional AuthConfig instance. If None, uses global config.
        """
        self._config = auth_config or get_auth_config()
        self._extractors: List[BaseTokenExtractor] = []
        self._extractor_map: Dict[str, BaseTokenExtractor] = {}
        self._initialize_extractors()

    def _initialize_extractors(self):
        """Initialize extractors based on configuration."""
        # Available extractor classes
        available_extractors = {
            "XRHIdentityExtractor": XRHIdentityExtractor,
            "OAuthBearerExtractor": OAuthBearerExtractor,
            "MockTokenExtractor": MockTokenExtractor,
        }

        # Get preferred extractors based on configuration (strict mode only)
        extractor_classes = self._config.get_preferred_extractor_classes()

        # Instantiate extractors in order of preference
        for extractor_name in extractor_classes:
            if extractor_name in available_extractors:
                extractor = available_extractors[extractor_name]()
                self._extractors.append(extractor)
                self._extractor_map[extractor_name] = extractor

        # Add any custom extractors
        for provider in AuthProvider:
            custom_extractor_class = self._config.get_custom_extractor(provider)
            if custom_extractor_class:
                custom_extractor = custom_extractor_class()
                self._extractors.append(custom_extractor)
                self._extractor_map[custom_extractor_class.__name__] = custom_extractor

        LOG.debug(f"Initialized auth factory with extractors: {[e.__class__.__name__ for e in self._extractors]}")
        LOG.info(f"Auth factory configuration: {self._config}")

    def create_token_from_request(self, request, source_format: Optional[str] = None) -> NormalizedAuthToken:
        """
        Create a normalized token from a Django request object.

        Args:
            request: Django request object
            source_format: Optional format hint ("x-rh-identity", "oauth-bearer", "mock")
                          If not provided, will attempt auto-detection

        Returns:
            NormalizedAuthToken: The normalized token

        Raises:
            TokenExtractionError: If token extraction fails
        """
        # Auto-detect format if not provided
        if not source_format:
            source_format = self._detect_format_from_request(request)

        # Extract raw token based on format
        raw_token = self._extract_raw_token(request, source_format)

        # Create extraction context
        context = TokenExtractionContext(
            source_format=source_format,
            raw_token=raw_token,
            headers=getattr(request, 'headers', None),
            request_path=getattr(request, 'path', None),
        )

        return self.create_token_from_context(context)

    def create_token_from_headers(self, headers: Dict[str, str], source_format: Optional[str] = None) -> NormalizedAuthToken:
        """
        Create a normalized token from HTTP headers.

        Args:
            headers: Dictionary of HTTP headers
            source_format: Optional format hint

        Returns:
            NormalizedAuthToken: The normalized token

        Raises:
            TokenExtractionError: If token extraction fails
        """
        # Auto-detect format if not provided
        if not source_format:
            source_format = self._detect_format_from_headers(headers)

        # Extract raw token
        raw_token = self._extract_raw_token_from_headers(headers, source_format)

        # Create extraction context
        context = TokenExtractionContext(
            source_format=source_format,
            raw_token=raw_token,
            headers=headers,
        )

        return self.create_token_from_context(context)

    def create_token_from_raw(self, raw_token: str, source_format: str) -> NormalizedAuthToken:
        """
        Create a normalized token from a raw token string.

        Args:
            raw_token: The raw token string
            source_format: Token format ("x-rh-identity", "oauth-bearer", etc.)

        Returns:
            NormalizedAuthToken: The normalized token

        Raises:
            TokenExtractionError: If token extraction fails
        """
        context = TokenExtractionContext(
            source_format=source_format,
            raw_token=raw_token,
        )

        return self.create_token_from_context(context)

    def create_token_from_context(self, context: TokenExtractionContext) -> NormalizedAuthToken:
        """
        Create a normalized token from an extraction context.

        Args:
            context: TokenExtractionContext with all necessary information

        Returns:
            NormalizedAuthToken: The normalized token

        Raises:
            TokenExtractionError: If no suitable extractor found or extraction fails
        """
        # Find suitable extractor
        extractor = self._find_extractor(context)
        if not extractor:
            raise TokenExtractionError(
                f"No extractor available for format: {context.source_format}"
            )

        try:
            # Extract the token
            LOG.debug(f"Extracting token using {extractor.__class__.__name__}: {context}")
            token = extractor.extract(context)
            LOG.debug(f"Successfully extracted token: {token}")
            return token

        except Exception as error:
            LOG.error(f"Token extraction failed with {extractor.__class__.__name__}: {error}")
            raise TokenExtractionError(f"Token extraction failed: {error}") from error

    def _find_extractor(self, context: TokenExtractionContext) -> Optional[BaseTokenExtractor]:
        """Find the appropriate extractor for the given context."""
        for extractor in self._extractors:
            if extractor.can_extract(context):
                return extractor
        return None

    def _detect_format_from_request(self, request) -> str:
        """Get token format from configured provider (strict mode - no auto-detection)."""
        return self._config.get_default_format_for_provider()

    def _detect_format_from_headers(self, headers: Dict[str, str]) -> str:
        """Get token format from configured provider (strict mode - no auto-detection)."""
        return self._config.get_default_format_for_provider()

    def _has_xrh_identity_header(self, request) -> bool:
        """Check if request has X-RH-Identity header."""
        try:
            # Try different access methods
            header_value = get_auth_header_value(request, "standard")
            if header_value:
                return True

            header_value = get_auth_header_value(request, "meta")
            if header_value:
                return True

            return False
        except Exception:
            return False

    def _extract_raw_token(self, request, source_format: str) -> Optional[str]:
        """Extract raw token from Django request based on format."""
        if source_format == "x-rh-identity":
            # Try standard headers first, then META
            token = get_auth_header_value(request, "standard")
            if not token:
                token = get_auth_header_value(request, "meta")
            return token

        elif source_format == "oauth-bearer":
            auth_header = getattr(request, 'headers', {}).get('Authorization', '')
            if auth_header.startswith('Bearer '):
                return auth_header[7:]  # Remove "Bearer " prefix
            return None

        elif source_format == "mock":
            return "mock-token"  # Mock token for development

        return None

    def _extract_raw_token_from_headers(self, headers: Dict[str, str], source_format: str) -> Optional[str]:
        """Extract raw token from headers dictionary based on format."""
        if source_format == "x-rh-identity":
            # Look for X-RH-Identity header (case insensitive)
            for key, value in headers.items():
                if key.lower() == 'x-rh-identity':
                    return value
            return None

        elif source_format == "oauth-bearer":
            auth_header = headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                return auth_header[7:]  # Remove "Bearer " prefix
            return None

        elif source_format == "mock":
            return "mock-token"

        return None

    def _is_development_mode(self) -> bool:
        """Check if we're in development mode."""
        try:
            from django.conf import settings
            return getattr(settings, 'DEVELOPMENT_IDENTITY', None) is not None
        except ImportError:
            return False

    def add_extractor(self, extractor: BaseTokenExtractor):
        """Add a custom extractor to the factory."""
        self._extractors.append(extractor)

    def get_supported_formats(self) -> List[str]:
        """Get list of supported token formats."""
        formats = []
        for extractor in self._extractors:
            # This is a simple way to identify formats - could be enhanced
            class_name = extractor.__class__.__name__.lower()
            if 'xrh' in class_name:
                formats.append('x-rh-identity')
            elif 'oauth' in class_name:
                formats.append('oauth-bearer')
            elif 'mock' in class_name:
                formats.append('mock')
        return list(set(formats))

    def get_configuration(self) -> str:
        """Get current factory configuration as a string."""
        return str(self._config)

    def reload_configuration(self):
        """Reload configuration and reinitialize extractors."""
        self._config.reload_settings()
        self._extractors.clear()
        self._extractor_map.clear()
        self._initialize_extractors()
        LOG.info(f"Auth factory configuration reloaded: {self._config}")


# Global factory instance
_token_factory = AuthTokenFactory()


def get_token_factory() -> AuthTokenFactory:
    """Get the global token factory instance."""
    return _token_factory


def create_normalized_token_from_request(request, source_format: Optional[str] = None) -> NormalizedAuthToken:
    """
    Convenience function to create a normalized token from a request.

    This is the main entry point for most application code.
    """
    return get_token_factory().create_token_from_request(request, source_format)

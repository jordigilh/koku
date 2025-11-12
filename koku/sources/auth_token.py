#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Authentication Token Abstraction

This module provides a token-agnostic abstraction layer that normalizes
authentication tokens from different providers (X-RH-Identity, OAuth, etc.)
into a consistent structure containing only the fields used by Koku.

This abstraction:
- Reduces coupling to specific auth token formats
- Simplifies auth provider migration
- Isolates the impact of auth token format changes
- Provides type safety and validation
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

LOG = logging.getLogger(__name__)


class IdentityType(Enum):
    """Supported identity types."""
    USER = "User"
    SERVICE_ACCOUNT = "ServiceAccount"
    SYSTEM = "System"


class AuthTokenError(Exception):
    """Base exception for auth token operations."""
    pass


class TokenExtractionError(AuthTokenError):
    """Exception raised when token extraction fails."""
    pass


class TokenValidationError(AuthTokenError):
    """Exception raised when token validation fails."""
    pass


@dataclass
class NormalizedAuthToken:
    """
    Normalized authentication token containing only fields used by Koku.

    This structure is agnostic to the underlying auth provider and contains
    a minimal set of fields extracted from various token formats.
    """
    # Core identity fields - always required
    account_number: str
    org_id: str
    identity_type: IdentityType
    username: str

    # User information - optional depending on identity type
    email: Optional[str] = None
    is_org_admin: bool = False

    # Entitlements
    is_cost_management_entitled: bool = False

    # Auth provider metadata - optional
    auth_type: Optional[str] = None

    # Special fields for specific identity types
    cluster_id: Optional[str] = None  # For System type with cluster auth

    # Development/testing - not used in production
    access_permissions: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Validate the token after initialization."""
        self._validate()

    def _validate(self):
        """Validate the normalized token data."""
        if not self.account_number:
            raise TokenValidationError("account_number is required")

        if not self.org_id:
            raise TokenValidationError("org_id is required")

        if not self.username:
            raise TokenValidationError("username is required")

        # Validate identity type specific requirements
        if self.identity_type == IdentityType.SYSTEM:
            if self.auth_type == "uhc-auth" and not self.cluster_id:
                raise TokenValidationError("cluster_id required for System identity with uhc-auth")

    @property
    def is_user(self) -> bool:
        """Check if this is a user identity."""
        return self.identity_type == IdentityType.USER

    @property
    def is_service_account(self) -> bool:
        """Check if this is a service account identity."""
        return self.identity_type == IdentityType.SERVICE_ACCOUNT

    @property
    def is_system(self) -> bool:
        """Check if this is a system identity."""
        return self.identity_type == IdentityType.SYSTEM

    @property
    def is_admin(self) -> bool:
        """Check if this identity has admin privileges."""
        return self.is_org_admin

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "account_number": self.account_number,
            "org_id": self.org_id,
            "identity_type": self.identity_type.value,
            "username": self.username,
            "email": self.email,
            "is_org_admin": self.is_org_admin,
            "is_cost_management_entitled": self.is_cost_management_entitled,
            "auth_type": self.auth_type,
            "cluster_id": self.cluster_id,
            "access_permissions": self.access_permissions,
        }

    def __str__(self) -> str:
        """String representation for logging (excludes sensitive data)."""
        return (
            f"NormalizedAuthToken(account={self.account_number}, "
            f"org_id={self.org_id}, type={self.identity_type.value}, "
            f"username={self.username}, admin={self.is_org_admin})"
        )


@dataclass
class TokenExtractionContext:
    """Context information for token extraction operations."""
    source_format: str  # e.g., "x-rh-identity", "oauth-bearer"
    raw_token: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    request_path: Optional[str] = None

    def __str__(self) -> str:
        return f"TokenExtractionContext(format={self.source_format})"

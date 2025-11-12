#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Authentication Token Extractors

This module contains extractors that parse different authentication token formats
and convert them into normalized NormalizedAuthToken instances.
"""
import json
import logging
import binascii
from abc import ABC, abstractmethod
from base64 import b64decode
from json.decoder import JSONDecodeError
from typing import Dict, Any, Optional

from .auth_token import (
    NormalizedAuthToken,
    IdentityType,
    TokenExtractionError,
    TokenExtractionContext
)

LOG = logging.getLogger(__name__)


class BaseTokenExtractor(ABC):
    """Base class for all token extractors."""

    @abstractmethod
    def can_extract(self, context: TokenExtractionContext) -> bool:
        """Check if this extractor can handle the given context."""
        pass

    @abstractmethod
    def extract(self, context: TokenExtractionContext) -> NormalizedAuthToken:
        """Extract and return a normalized token from the context."""
        pass


class XRHIdentityExtractor(BaseTokenExtractor):
    """Extractor for X-RH-Identity tokens (Red Hat's current format)."""

    def can_extract(self, context: TokenExtractionContext) -> bool:
        """Check if this is an X-RH-Identity token."""
        return context.source_format == "x-rh-identity"

    def extract(self, context: TokenExtractionContext) -> NormalizedAuthToken:
        """Extract normalized token from X-RH-Identity format."""
        if not context.raw_token:
            raise TokenExtractionError("No raw token provided for X-RH-Identity extraction")

        try:
            # Decode the base64 JSON token
            decoded_token = b64decode(context.raw_token)
            json_token = json.loads(decoded_token)

            LOG.debug(f"Extracted X-RH-Identity token for processing: {context}")

            return self._parse_xrh_token(json_token)

        except (binascii.Error, JSONDecodeError) as error:
            raise TokenExtractionError(f"Failed to decode X-RH-Identity token: {error}") from error
        except KeyError as error:
            raise TokenExtractionError(f"Missing required field in X-RH-Identity token: {error}") from error

    def _parse_xrh_token(self, json_token: Dict[str, Any]) -> NormalizedAuthToken:
        """Parse the decoded X-RH-Identity JSON into normalized format."""
        # Extract entitlements
        is_entitled = (
            json_token.get("entitlements", {})
            .get("cost_management", {})
            .get("is_entitled", False)
        )

        # Extract identity section
        identity = json_token.get("identity", {})
        if not identity:
            raise TokenExtractionError("Missing 'identity' section in X-RH-Identity token")

        # Core fields
        account_number = identity.get("account_number")
        org_id = identity.get("org_id")
        identity_type_str = identity.get("type", "User")
        auth_type = identity.get("auth_type")

        if not account_number:
            raise TokenExtractionError("Missing account_number in X-RH-Identity token")
        if not org_id:
            raise TokenExtractionError("Missing org_id in X-RH-Identity token")

        # Parse identity type
        try:
            identity_type = IdentityType(identity_type_str)
        except ValueError:
            LOG.warning(f"Unknown identity type '{identity_type_str}', defaulting to User")
            identity_type = IdentityType.USER

        # Extract user information based on identity type
        username, email, is_org_admin, cluster_id, access_permissions = self._extract_user_info(
            identity, identity_type, auth_type
        )

        return NormalizedAuthToken(
            account_number=account_number,
            org_id=org_id,
            identity_type=identity_type,
            username=username,
            email=email,
            is_org_admin=is_org_admin,
            is_cost_management_entitled=is_entitled,
            auth_type=auth_type,
            cluster_id=cluster_id,
            access_permissions=access_permissions,
        )

    def _extract_user_info(self, identity: Dict[str, Any], identity_type: IdentityType, auth_type: Optional[str]):
        """Extract user-specific information based on identity type."""
        username = None
        email = None
        is_org_admin = False
        cluster_id = None
        access_permissions = None

        if identity_type == IdentityType.USER:
            user_info = identity.get("user", {})
            username = user_info.get("username")
            email = user_info.get("email")
            is_org_admin = user_info.get("is_org_admin", False)
            access_permissions = user_info.get("access")  # For development mode

        elif identity_type == IdentityType.SERVICE_ACCOUNT:
            service_account = identity.get("service_account", {})
            username = service_account.get("username")
            email = ""  # Service accounts don't have email

        elif identity_type == IdentityType.SYSTEM:
            if auth_type == "uhc-auth":
                system_info = identity.get("system", {})
                cluster_id = system_info.get("cluster_id")
                username = cluster_id  # Use cluster_id as username for system accounts
                email = ""  # System accounts don't have email
            else:
                # Handle other system auth types if needed
                username = identity.get("username", "system")
                email = ""

        if not username:
            raise TokenExtractionError(f"Could not extract username for identity type {identity_type.value}")

        return username, email, is_org_admin, cluster_id, access_permissions


class OAuthBearerExtractor(BaseTokenExtractor):
    """Extractor for OAuth Bearer tokens (JWT format)."""

    def can_extract(self, context: TokenExtractionContext) -> bool:
        """Check if this is an OAuth Bearer token."""
        return context.source_format == "oauth-bearer"

    def extract(self, context: TokenExtractionContext) -> NormalizedAuthToken:
        """Extract normalized token from OAuth Bearer format."""
        if not context.raw_token:
            raise TokenExtractionError("No raw token provided for OAuth extraction")

        try:
            LOG.debug(f"Extracting OAuth Bearer token: {context}")
            return self._parse_oauth_token(context.raw_token)

        except Exception as error:
            raise TokenExtractionError(f"Failed to extract OAuth Bearer token: {error}") from error

    def _parse_oauth_token(self, token: str) -> NormalizedAuthToken:
        """Parse OAuth JWT token into normalized format."""
        try:
            # Parse JWT token (without signature verification for now)
            # In production, you would verify the signature using the provider's public key
            header, payload, signature = self._decode_jwt_parts(token)

            # Extract standard OAuth claims
            claims = payload

            # Map OAuth claims to normalized token fields
            return self._map_claims_to_normalized_token(claims)

        except Exception as error:
            raise TokenExtractionError(f"Failed to parse OAuth JWT token: {error}") from error

    def _decode_jwt_parts(self, token: str):
        """Decode JWT token parts without signature verification."""
        import base64
        import json

        try:
            # Split JWT into parts
            parts = token.split('.')
            if len(parts) != 3:
                raise TokenExtractionError(f"Invalid JWT format: expected 3 parts, got {len(parts)}")

            header_b64, payload_b64, signature_b64 = parts

            # Decode header and payload (add padding if needed)
            header_json = self._base64url_decode(header_b64)
            payload_json = self._base64url_decode(payload_b64)

            header = json.loads(header_json)
            payload = json.loads(payload_json)

            return header, payload, signature_b64

        except (ValueError, json.JSONDecodeError) as error:
            raise TokenExtractionError(f"Failed to decode JWT parts: {error}") from error

    def _base64url_decode(self, data: str) -> str:
        """Decode base64url data with proper padding."""
        import base64

        # Add padding if needed
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)

        # Replace URL-safe characters
        data = data.replace('-', '+').replace('_', '/')

        try:
            decoded = base64.b64decode(data)
            return decoded.decode('utf-8')
        except Exception as error:
            raise TokenExtractionError(f"Base64 decode failed: {error}") from error

    def _map_claims_to_normalized_token(self, claims: Dict[str, Any]) -> NormalizedAuthToken:
        """Map OAuth claims to normalized token format."""
        try:
            # Standard OAuth/OIDC claims mapping
            # These mappings can be customized based on your OAuth provider

            # Required fields - extract with fallbacks
            username = self._extract_username(claims)
            account_number = self._extract_account_number(claims)
            org_id = self._extract_org_id(claims)

            # Optional fields
            email = claims.get("email")
            is_org_admin = self._extract_admin_status(claims)
            is_entitled = self._extract_entitlement(claims)

            # Identity type (most OAuth tokens are for users)
            identity_type = self._extract_identity_type(claims)

            return NormalizedAuthToken(
                account_number=account_number,
                org_id=org_id,
                identity_type=identity_type,
                username=username,
                email=email,
                is_org_admin=is_org_admin,
                is_cost_management_entitled=is_entitled,
                auth_type="oauth",
            )

        except Exception as error:
            raise TokenExtractionError(f"Failed to map OAuth claims: {error}") from error

    def _extract_username(self, claims: Dict[str, Any]) -> str:
        """Extract username from OAuth claims."""
        # Try different common username claims
        username_candidates = [
            claims.get("preferred_username"),  # OIDC standard
            claims.get("username"),           # Common custom claim
            claims.get("sub"),                # Subject - fallback
            claims.get("user_id"),            # Some providers use this
            claims.get("name"),               # Display name fallback
        ]

        for candidate in username_candidates:
            if candidate and isinstance(candidate, str):
                return candidate

        raise TokenExtractionError("Could not extract username from OAuth token")

    def _extract_account_number(self, claims: Dict[str, Any]) -> str:
        """Extract account number from OAuth claims."""
        # Try different possible account number claims
        account_candidates = [
            claims.get("account_number"),     # Direct mapping
            claims.get("account_id"),         # Alternative name
            claims.get("tenant_id"),          # Some providers use tenant
            claims.get("organization_id"),    # Organization-based
            claims.get("custom_account"),     # Custom claim
        ]

        for candidate in account_candidates:
            if candidate:
                return str(candidate)

        # If no account number found, you might need to:
        # 1. Use a default value
        # 2. Extract from other claims
        # 3. Make an API call to get account info
        # For now, we'll use a placeholder
        LOG.warning("No account_number found in OAuth token, using default")
        return "oauth-account"

    def _extract_org_id(self, claims: Dict[str, Any]) -> str:
        """Extract organization ID from OAuth claims."""
        # Try different possible org ID claims
        org_candidates = [
            claims.get("org_id"),            # Direct mapping
            claims.get("organization_id"),   # Alternative name
            claims.get("tenant_id"),         # Tenant-based
            claims.get("realm"),             # Keycloak realm
            claims.get("iss"),               # Issuer as org (last resort)
        ]

        for candidate in org_candidates:
            if candidate:
                return str(candidate)

        # Similar to account_number, might need custom logic
        LOG.warning("No org_id found in OAuth token, using default")
        return "oauth-org"

    def _extract_admin_status(self, claims: Dict[str, Any]) -> bool:
        """Extract admin status from OAuth claims."""
        # Try different ways to determine admin status

        # Check for direct admin claim
        if claims.get("is_admin") or claims.get("is_org_admin"):
            return bool(claims.get("is_admin") or claims.get("is_org_admin"))

        # Check groups/roles for admin indicators
        groups = claims.get("groups", [])
        roles = claims.get("roles", [])
        realm_roles = claims.get("realm_access", {}).get("roles", [])

        admin_indicators = [
            "admin", "administrator", "org-admin", "cost-management-admin",
            "superuser", "owner", "manager"
        ]

        all_roles = groups + roles + realm_roles
        for role in all_roles:
            if any(indicator in str(role).lower() for indicator in admin_indicators):
                return True

        return False

    def _extract_entitlement(self, claims: Dict[str, Any]) -> bool:
        """Extract cost management entitlement from OAuth claims."""
        # Check for direct entitlement claim
        entitlements = claims.get("entitlements", {})
        if isinstance(entitlements, dict):
            cost_mgmt = entitlements.get("cost_management", {})
            if isinstance(cost_mgmt, dict):
                return bool(cost_mgmt.get("is_entitled", False))

        # Check scopes for cost management access
        scopes = claims.get("scope", "").split() if claims.get("scope") else []
        cost_mgmt_scopes = ["cost-management", "cost_management", "cost:read", "cost:write"]

        for scope in scopes:
            if any(cm_scope in scope.lower() for cm_scope in cost_mgmt_scopes):
                return True

        # Check groups/roles for cost management access
        groups = claims.get("groups", [])
        roles = claims.get("roles", [])

        cost_mgmt_indicators = ["cost-management", "cost_management", "billing"]
        all_roles = groups + roles

        for role in all_roles:
            if any(indicator in str(role).lower() for indicator in cost_mgmt_indicators):
                return True

        # Default to entitled for OAuth tokens (can be configured)
        return True

    def _extract_identity_type(self, claims: Dict[str, Any]) -> IdentityType:
        """Extract identity type from OAuth claims."""
        # Check for explicit identity type claims
        token_type = claims.get("token_type", "").lower()
        subject_type = claims.get("sub_type", "").lower()

        if any(term in token_type or term in subject_type for term in ["service", "client", "application"]):
            return IdentityType.SERVICE_ACCOUNT

        if any(term in token_type or term in subject_type for term in ["system", "machine"]):
            return IdentityType.SYSTEM

        # Check client_id vs user patterns
        client_id = claims.get("client_id", "")
        if client_id and not claims.get("preferred_username"):
            # Likely a client credentials token
            return IdentityType.SERVICE_ACCOUNT

        # Default to user for most OAuth tokens
        return IdentityType.USER


class MockTokenExtractor(BaseTokenExtractor):
    """Extractor for development/testing mock tokens."""

    def can_extract(self, context: TokenExtractionContext) -> bool:
        """Check if this is a mock/development token."""
        return context.source_format == "mock"

    def extract(self, context: TokenExtractionContext) -> NormalizedAuthToken:
        """Extract normalized token from mock format."""
        # For development/testing - create a basic token
        return NormalizedAuthToken(
            account_number="10001",
            org_id="1234567",
            identity_type=IdentityType.USER,
            username="user_dev",
            email="user_dev@example.com",
            is_org_admin=False,
            is_cost_management_entitled=True,
            auth_type="mock",
        )

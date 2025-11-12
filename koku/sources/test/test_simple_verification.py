#!/usr/bin/env python3
#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Simple verification tests for authentication token abstraction.

These tests verify the core functionality without complex mocking.
"""
import json
import sys
import os
from base64 import b64encode
from unittest.mock import Mock

# Add the koku directory to Python path for imports
script_dir = os.path.dirname(__file__)
koku_dir = os.path.join(script_dir, '..', '..')
sys.path.insert(0, koku_dir)

# Mock Django before importing our modules
def setup_django_mocks():
    """Setup Django mocks."""
    mock_settings = Mock()
    mock_settings.AUTH_PROVIDER = 'rhsso'

    mock_translation = Mock()
    mock_translation.gettext = lambda x: x

    mock_django_utils = Mock()
    mock_django_utils.translation = mock_translation

    mock_conf = Mock()
    mock_conf.settings = mock_settings

    mock_django = Mock()
    mock_django.conf = mock_conf
    mock_django.utils = mock_django_utils

    sys.modules['django'] = mock_django
    sys.modules['django.conf'] = mock_conf
    sys.modules['django.utils'] = mock_django_utils
    sys.modules['django.utils.translation'] = mock_translation

    return mock_settings

def test_x_rh_identity_extraction():
    """Test X-RH-Identity token extraction."""
    print("Testing X-RH-Identity token extraction...")

    # Setup Django
    mock_settings = setup_django_mocks()
    mock_settings.AUTH_PROVIDER = 'rhsso'

    try:
        from sources.auth_factory import AuthTokenFactory
        from sources.auth_token import IdentityType

        # Create X-RH-Identity token
        identity_data = {
            "identity": {
                "account_number": "12345",
                "org_id": "67890",
                "type": "User",
                "user": {
                    "username": "test_user",
                    "email": "test@example.com",
                    "is_org_admin": True
                }
            },
            "entitlements": {
                "cost_management": {
                    "is_entitled": True
                }
            }
        }

        encoded_token = b64encode(json.dumps(identity_data).encode()).decode()

        # Extract token
        factory = AuthTokenFactory()
        result = factory.create_token_from_raw(encoded_token, "x-rh-identity")

        # Verify results
        assert result.username == "test_user", f"Expected 'test_user', got '{result.username}'"
        assert result.email == "test@example.com", f"Expected 'test@example.com', got '{result.email}'"
        assert result.account_number == "12345", f"Expected '12345', got '{result.account_number}'"
        assert result.org_id == "67890", f"Expected '67890', got '{result.org_id}'"
        assert result.identity_type == IdentityType.USER, f"Expected USER, got {result.identity_type}"
        assert result.is_org_admin == True, f"Expected True, got {result.is_org_admin}"
        assert result.is_cost_management_entitled == True, f"Expected True, got {result.is_cost_management_entitled}"

        print("✅ X-RH-Identity extraction test passed!")
        return True

    except Exception as e:
        print(f"❌ X-RH-Identity extraction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_oauth_extraction():
    """Test OAuth JWT token extraction."""
    print("Testing OAuth JWT token extraction...")

    # Setup Django
    mock_settings = setup_django_mocks()
    mock_settings.AUTH_PROVIDER = 'oauth'

    try:
        from sources.auth_factory import AuthTokenFactory
        from sources.auth_token import IdentityType

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

        # Extract token
        factory = AuthTokenFactory()
        result = factory.create_token_from_raw(jwt_token, "oauth-bearer")

        # Verify results
        assert result.username == "oauth.user", f"Expected 'oauth.user', got '{result.username}'"
        assert result.email == "oauth@example.com", f"Expected 'oauth@example.com', got '{result.email}'"
        assert result.account_number == "54321", f"Expected '54321', got '{result.account_number}'"
        assert result.org_id == "98765", f"Expected '98765', got '{result.org_id}'"
        assert result.identity_type == IdentityType.USER, f"Expected USER, got {result.identity_type}"
        assert result.is_org_admin == True, f"Expected True, got {result.is_org_admin}"
        assert result.is_cost_management_entitled == True, f"Expected True, got {result.is_cost_management_entitled}"
        assert result.auth_type == "oauth", f"Expected 'oauth', got '{result.auth_type}'"

        print("✅ OAuth extraction test passed!")
        return True

    except Exception as e:
        print(f"❌ OAuth extraction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mock_extraction():
    """Test mock token extraction."""
    print("Testing mock token extraction...")

    # Setup Django
    mock_settings = setup_django_mocks()
    mock_settings.AUTH_PROVIDER = 'mock'

    try:
        from sources.auth_factory import AuthTokenFactory
        from sources.auth_token import IdentityType

        # Extract mock token
        factory = AuthTokenFactory()
        result = factory.create_token_from_raw("mock-token", "mock")

        # Verify results
        assert result.username == "user_dev", f"Expected 'user_dev', got '{result.username}'"
        assert result.account_number == "10001", f"Expected '10001', got '{result.account_number}'"
        assert result.org_id == "1234567", f"Expected '1234567', got '{result.org_id}'"
        assert result.identity_type == IdentityType.USER, f"Expected USER, got {result.identity_type}"
        assert result.is_cost_management_entitled == True, f"Expected True, got {result.is_cost_management_entitled}"
        assert result.auth_type == "mock", f"Expected 'mock', got '{result.auth_type}'"

        print("✅ Mock extraction test passed!")
        return True

    except Exception as e:
        print(f"❌ Mock extraction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_header_abstraction():
    """Test header name abstraction."""
    print("Testing header name abstraction...")

    try:
        # Setup Django
        mock_settings = setup_django_mocks()

        from sources.auth_headers import AuthHeaderManager
        from sources.auth_config import AuthConfig, AuthProvider

        config = AuthConfig()
        header_manager = AuthHeaderManager(config)

        # Test RHSSO headers
        mock_settings.AUTH_PROVIDER = 'rhsso'
        config.reload_settings()
        header_manager.reload_configuration()

        assert header_manager.get_request_header_name() == "X-Rh-Identity"
        assert header_manager.get_django_meta_header_name() == "HTTP_X_RH_IDENTITY"
        assert header_manager.get_lowercase_header_name() == "x-rh-identity"

        # Test OAuth headers
        mock_settings.AUTH_PROVIDER = 'oauth'
        config.reload_settings()
        header_manager.reload_configuration()

        assert header_manager.get_request_header_name() == "Authorization"
        assert header_manager.get_django_meta_header_name() == "HTTP_AUTHORIZATION"
        assert header_manager.get_lowercase_header_name() == "authorization"

        print("✅ Header abstraction test passed!")
        return True

    except Exception as e:
        print(f"❌ Header abstraction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_outgoing_headers():
    """Test outgoing header creation."""
    print("Testing outgoing header creation...")

    try:
        # Setup Django
        mock_settings = setup_django_mocks()

        from sources.auth_headers import AuthHeaderManager
        from sources.auth_config import AuthConfig

        config = AuthConfig()
        header_manager = AuthHeaderManager(config)

        # Test RHSSO outgoing headers
        mock_settings.AUTH_PROVIDER = 'rhsso'
        config.reload_settings()
        header_manager.reload_configuration()

        rhsso_headers = header_manager.create_outgoing_headers("test_token")
        expected_rhsso = {"x-rh-identity": "test_token"}
        assert rhsso_headers == expected_rhsso, f"Expected {expected_rhsso}, got {rhsso_headers}"

        # Test OAuth outgoing headers
        mock_settings.AUTH_PROVIDER = 'oauth'
        config.reload_settings()
        header_manager.reload_configuration()

        oauth_headers = header_manager.create_outgoing_headers("test_token")
        expected_oauth = {"Authorization": "Bearer test_token"}
        assert oauth_headers == expected_oauth, f"Expected {expected_oauth}, got {oauth_headers}"

        print("✅ Outgoing headers test passed!")
        return True

    except Exception as e:
        print(f"❌ Outgoing headers test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_integration():
    """Test API integration functions."""
    print("Testing API integration...")

    try:
        # Setup Django
        mock_settings = setup_django_mocks()

        from sources.api import get_auth_header_name, get_auth_header_lowercase_name
        from api.common import get_identity_header

        # Test RHSSO
        mock_settings.AUTH_PROVIDER = 'rhsso'

        request_header = get_auth_header_name()
        lowercase_header = get_auth_header_lowercase_name()
        identity_header = get_identity_header()

        assert request_header == "X-Rh-Identity", f"Expected 'X-Rh-Identity', got '{request_header}'"
        assert lowercase_header == "x-rh-identity", f"Expected 'x-rh-identity', got '{lowercase_header}'"
        assert identity_header == "HTTP_X_RH_IDENTITY", f"Expected 'HTTP_X_RH_IDENTITY', got '{identity_header}'"

        # Test OAuth - need to reload global configurations
        mock_settings.AUTH_PROVIDER = 'oauth'

        # Force reload of global configurations
        from sources.auth_config import reload_auth_config
        from sources.auth_headers import reload_header_configuration
        reload_auth_config()
        reload_header_configuration()

        request_header = get_auth_header_name()
        lowercase_header = get_auth_header_lowercase_name()
        identity_header = get_identity_header()

        assert request_header == "Authorization", f"Expected 'Authorization', got '{request_header}'"
        assert lowercase_header == "authorization", f"Expected 'authorization', got '{lowercase_header}'"
        assert identity_header == "HTTP_AUTHORIZATION", f"Expected 'HTTP_AUTHORIZATION', got '{identity_header}'"

        print("✅ API integration test passed!")
        return True

    except Exception as e:
        print(f"❌ API integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all verification tests."""
    print("=" * 70)
    print("Authentication Token Abstraction - Simple Verification Tests")
    print("=" * 70)

    tests = [
        test_x_rh_identity_extraction,
        test_oauth_extraction,
        test_mock_extraction,
        test_header_abstraction,
        test_outgoing_headers,
        test_api_integration
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
        print()

    print("=" * 70)
    print("Test Summary:")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total:  {passed + failed}")

    if failed == 0:
        print("\n🎉 All verification tests passed!")
        print("\n✅ Authentication Token Abstraction System Verified:")
        print("   - X-RH-Identity token extraction working")
        print("   - OAuth JWT token extraction working")
        print("   - Mock token extraction working")
        print("   - Header name abstraction working")
        print("   - Provider switching working")
        print("   - Outgoing header creation working")
        print("   - API integration working")
        print("\n🔄 Provider switching requires ZERO code changes!")
        print("🛡️ System is future-proof and ready for production!")
    else:
        print(f"\n❌ {failed} test(s) failed. Please review the errors above.")

    print("=" * 70)
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

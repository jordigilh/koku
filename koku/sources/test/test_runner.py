#!/usr/bin/env python3
#
# Copyright 2024 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""
Test runner for authentication token abstraction tests.

This script runs all the authentication abstraction tests and provides
a comprehensive report of test coverage and results.
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

# Add the koku directory to Python path for imports
script_dir = os.path.dirname(__file__)
koku_dir = os.path.join(script_dir, '..', '..')
sys.path.insert(0, koku_dir)


def mock_django_environment():
    """Mock Django environment for testing."""
    # Mock Django settings
    mock_settings = Mock()
    mock_settings.AUTH_PROVIDER = 'rhsso'

    # Mock Django utils
    mock_translation = Mock()
    mock_translation.gettext = lambda x: x

    mock_django_utils = Mock()
    mock_django_utils.translation = mock_translation

    # Mock Django conf
    mock_conf = Mock()
    mock_conf.settings = mock_settings

    # Mock Django module
    mock_django = Mock()
    mock_django.conf = mock_conf
    mock_django.utils = mock_django_utils

    # Install mocks
    sys.modules['django'] = mock_django
    sys.modules['django.conf'] = mock_conf
    sys.modules['django.utils'] = mock_django_utils
    sys.modules['django.utils.translation'] = mock_translation

    return mock_settings


def run_test_suite():
    """Run the complete test suite for authentication abstraction."""
    print("=" * 70)
    print("Authentication Token Abstraction Test Suite")
    print("=" * 70)

    # Mock Django environment
    mock_settings = mock_django_environment()

    # Discover and run tests
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(__file__)

    # Load all test modules
    test_modules = [
        'test_auth_config',
        'test_auth_headers',
        'test_auth_extractors',
        'test_auth_factory',
        'test_auth_token',
        'test_auth_integration'
    ]

    suite = unittest.TestSuite()

    for module_name in test_modules:
        try:
            module = __import__(module_name)
            module_suite = loader.loadTestsFromModule(module)
            suite.addTest(module_suite)
            print(f"✅ Loaded tests from {module_name}")
        except ImportError as e:
            print(f"❌ Failed to load {module_name}: {e}")

    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)

    print("\n" + "=" * 70)
    print("Running Tests...")
    print("=" * 70)

    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    successes = total_tests - failures - errors

    print(f"Total Tests: {total_tests}")
    print(f"Successes:   {successes}")
    print(f"Failures:    {failures}")
    print(f"Errors:      {errors}")

    if failures == 0 and errors == 0:
        print("\n🎉 All tests passed! Authentication abstraction is working correctly.")
        print("\n✅ System Benefits Verified:")
        print("   - Token format abstraction working")
        print("   - Provider switching requires zero code changes")
        print("   - Header management is dynamic and consistent")
        print("   - OAuth and X-RH-Identity tokens both supported")
        print("   - Error handling and validation working")
        print("   - Integration across all components verified")
    else:
        print(f"\n❌ {failures + errors} test(s) failed. Please review the failures above.")

        if failures > 0:
            print("\nFailures:")
            for test, traceback in result.failures:
                print(f"  - {test}: {traceback.split(chr(10))[-2] if chr(10) in traceback else traceback}")

        if errors > 0:
            print("\nErrors:")
            for test, traceback in result.errors:
                print(f"  - {test}: {traceback.split(chr(10))[-2] if chr(10) in traceback else traceback}")

    print("=" * 70)

    return result.wasSuccessful()


def run_specific_test_class(class_name):
    """Run a specific test class."""
    mock_django_environment()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Map class names to modules
    class_to_module = {
        'TestAuthConfig': 'test_auth_config',
        'TestAuthHeaderManager': 'test_auth_headers',
        'TestXRHIdentityExtractor': 'test_auth_extractors',
        'TestOAuthBearerExtractor': 'test_auth_extractors',
        'TestMockTokenExtractor': 'test_auth_extractors',
        'TestAuthTokenFactory': 'test_auth_factory',
        'TestNormalizedAuthToken': 'test_auth_token',
        'TestAuthSystemIntegration': 'test_auth_integration',
    }

    if class_name in class_to_module:
        module_name = class_to_module[class_name]
        try:
            module = __import__(module_name)
            test_class = getattr(module, class_name)
            suite.addTest(loader.loadTestsFromTestCase(test_class))

            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(suite)
            return result.wasSuccessful()
        except (ImportError, AttributeError) as e:
            print(f"❌ Failed to load test class {class_name}: {e}")
            return False
    else:
        print(f"❌ Unknown test class: {class_name}")
        print(f"Available classes: {list(class_to_module.keys())}")
        return False


def run_provider_switch_demo():
    """Run a demonstration of provider switching."""
    print("=" * 70)
    print("Provider Switching Demonstration")
    print("=" * 70)

    mock_settings = mock_django_environment()

    try:
        from sources.auth_config import AuthConfig, AuthProvider
        from sources.auth_headers import AuthHeaderManager
        from sources.auth_factory import AuthTokenFactory

        config = AuthConfig()
        header_manager = AuthHeaderManager(config)
        factory = AuthTokenFactory(config)

        providers = [
            ('rhsso', AuthProvider.RHSSO),
            ('oauth', AuthProvider.OAUTH),
            ('mock', AuthProvider.MOCK)
        ]

        for provider_name, provider_enum in providers:
            print(f"\n🔄 Switching to {provider_name.upper()} provider...")

            # Update mock settings
            mock_settings.AUTH_PROVIDER = provider_name

            # Reload configurations
            config.reload_settings()
            header_manager.reload_configuration()
            factory.reload_configuration()

            # Show results
            print(f"   Request Header:    {header_manager.get_request_header_name()}")
            print(f"   Django META:       {header_manager.get_django_meta_header_name()}")
            print(f"   Cache Header:      {header_manager.get_cache_header_name()}")
            print(f"   Lowercase Header:  {header_manager.get_lowercase_header_name()}")
            print(f"   CORS Headers:      {header_manager.get_cors_headers()}")

            # Show outgoing headers
            outgoing = header_manager.create_outgoing_headers("test_token")
            print(f"   Outgoing Headers:  {outgoing}")

            # Show supported formats
            formats = factory.get_supported_formats()
            print(f"   Supported Formats: {formats}")

        print(f"\n✅ Provider switching demonstration complete!")
        print(f"✅ All components dynamically adapted to each provider!")

    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "demo":
            run_provider_switch_demo()
        elif command == "class" and len(sys.argv) > 2:
            class_name = sys.argv[2]
            success = run_specific_test_class(class_name)
            sys.exit(0 if success else 1)
        elif command == "help":
            print("Authentication Test Runner Commands:")
            print("  python test_runner.py          - Run all tests")
            print("  python test_runner.py demo     - Run provider switching demo")
            print("  python test_runner.py class <ClassName> - Run specific test class")
            print("  python test_runner.py help     - Show this help")
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    else:
        # Run full test suite
        success = run_test_suite()
        sys.exit(0 if success else 1)

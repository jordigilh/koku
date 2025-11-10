#
# Copyright 2021 Red Hat Inc.
# SPDX-License-Identifier: Apache-2.0
#
"""Create Unleash Client."""
import logging

from django.conf import settings
from UnleashClient import UnleashClient
from UnleashClient.periodic_tasks import aggregate_and_send_metrics

from .env import ENVIRONMENT

LOG = logging.getLogger(__name__)

log_level = getattr(logging, "WARNING")
if isinstance(getattr(logging, settings.UNLEASH_LOGGING_LEVEL), int):
    log_level = getattr(logging, settings.UNLEASH_LOGGING_LEVEL)
else:
    LOG.info(f"invalid UNLEASH_LOG_LEVEL: {settings.UNLEASH_LOGGING_LEVEL}. using default: `WARNING`")


def fallback_true(feature_name: str, context: dict) -> bool:
    return True


def fallback_development_true(feature_name: str, context: dict) -> bool:
    return context.get("environment", "").lower() == "development"


class DisabledUnleashClient:
    """Mock Unleash client that never makes network calls - for onprem deployments"""
    
    def __init__(self):
        # Add attributes that gunicorn_conf.py and other code expects
        self.unleash_instance_id = "disabled-unleash-client"
    
    def is_enabled(self, feature_name: str, context: dict = None, fallback_function=None):
        # Always use fallback function when disabled (no network calls)
        if fallback_function:
            return fallback_function(feature_name, context or {})
        return False  # Safe default when no fallback provided
    
    def initialize_client(self):
        # No-op for disabled client (no network calls)
        pass

    def destroy(self):
        pass  # No cleanup needed for mock client


class KokuUnleashClient(UnleashClient):
    """Koku Unleash Client."""

    def destroy(self):
        """Override destroy so that cache is not deleted."""
        self.fl_job.remove()
        if self.metric_job:
            self.metric_job.remove()

            # Flush metrics before shutting down.
            aggregate_and_send_metrics(
                url=self.unleash_url,
                app_name=self.unleash_app_name,
                connection_id=self.connection_id,
                instance_id=self.unleash_instance_id,
                headers=self.metrics_headers,
                custom_options=self.unleash_custom_options,
                request_timeout=self.unleash_request_timeout,
                engine=self.engine,
            )

        self.unleash_scheduler.shutdown()


# Check if Unleash should be disabled for onprem deployments
UNLEASH_DISABLED = ENVIRONMENT.bool("UNLEASH_DISABLED", default=False)

# Conditional client creation for onprem vs SaaS
if UNLEASH_DISABLED:
    # Create mock client that makes ZERO network calls
    UNLEASH_CLIENT = DisabledUnleashClient()
    LOG.info("Unleash disabled for onprem deployment - using mock client with zero network calls")
else:
    # Normal SaaS client with existing defaults
headers = {}
if settings.UNLEASH_TOKEN:
    headers["Authorization"] = settings.UNLEASH_TOKEN

UNLEASH_CLIENT = KokuUnleashClient(
    url=settings.UNLEASH_URL,
    app_name="Cost Management",
    environment=ENVIRONMENT.get_value("KOKU_SENTRY_ENVIRONMENT", default="development"),
    instance_id=ENVIRONMENT.get_value("APP_POD_NAME", default="unleash-client-python"),
    custom_headers=headers,
    cache_directory=settings.UNLEASH_CACHE_DIR,
    verbose_log_level=log_level,
)
    LOG.debug("Unleash client initialized for SaaS deployment")

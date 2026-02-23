"""Shared pytest fixtures used across all test modules."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure required env vars are set for test imports
os.environ.setdefault("GCP_PROJECT_ID", "test-project-id")
os.environ.setdefault("CURRENCY_CODE", "USD")
os.environ.setdefault("VERTEX_AI_MONTHLY_BUDGET", "100")
os.environ.setdefault("BIGQUERY_MONTHLY_BUDGET", "100")
os.environ.setdefault("FIRESTORE_MONTHLY_BUDGET", "100")
os.environ.setdefault("MONTHLY_BUDGET_AMOUNT", "300")
os.environ.setdefault("DRY_RUN_MODE", "True")
os.environ.setdefault("DEBUG_MODE", "True")
os.environ.setdefault("LAB_MODE", "False")
os.environ.setdefault("PRICE_SOURCE", "billing")
os.environ.setdefault("WARNING_THRESHOLD_PCT", "80")
os.environ.setdefault("CRITICAL_THRESHOLD_PCT", "100")
os.environ.setdefault("SMTP_EMAIL", "")
os.environ.setdefault("SMTP_APP_PASSWORD", "")
os.environ.setdefault("ALERT_RECEIVER_EMAILS", "")
os.environ.setdefault("BUDGET_STATE_PATH", "/tmp/budget_guard_test_state.json")
os.environ.setdefault("BUDGET_STATE_BUCKET", "")  # force local-file backend in tests


# Mock Pub/Sub at module level to avoid slow gRPC channel creation in tests.
# This prevents each NotificationService() from spending ~30s on PublisherClient()
_mock_pubsub_module = MagicMock()
_mock_publisher = MagicMock()
_mock_publisher.topic_path.return_value = "projects/test-project-id/topics/budget-guard-alerts"
_mock_pubsub_module.PublisherClient.return_value = _mock_publisher
# Force-insert so it overrides even if the real module is installed
sys.modules["google.cloud.pubsub_v1"] = _mock_pubsub_module

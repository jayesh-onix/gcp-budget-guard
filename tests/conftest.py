"""Shared pytest fixtures used across all test modules."""

import os
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
os.environ.setdefault("WARNING_THRESHOLD_PCT", "80")
os.environ.setdefault("CRITICAL_THRESHOLD_PCT", "100")
os.environ.setdefault("ALERT_COOLDOWN_SECONDS", "0")
os.environ.setdefault("SMTP_EMAIL", "")
os.environ.setdefault("SMTP_APP_PASSWORD", "")
os.environ.setdefault("ALERT_RECEIVER_EMAILS", "")

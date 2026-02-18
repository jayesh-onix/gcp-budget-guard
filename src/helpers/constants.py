"""Centralised constants and environment configuration.

All environment variables are validated at import time so that
the application fails fast on startup if critical config is missing.
"""

import os
from typing import Any

from helpers.logger import GCPLogger

# ---------------------------------------------------------------------------
# Boolean helpers
# ---------------------------------------------------------------------------
TRUE_VALUES = ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
DEBUG_MODE = os.environ.get("DEBUG_MODE", "False").lower() in TRUE_VALUES
APP_LOGGER = GCPLogger(debug=DEBUG_MODE)
APP_LOGGER.info(msg="GCP Budget Guard starting up …")

# Dry-run mode – logs actions but never actually disables services
DRY_RUN_MODE = os.environ.get("DRY_RUN_MODE", "False").lower() in TRUE_VALUES
if DRY_RUN_MODE:
    APP_LOGGER.warning(msg="DRY RUN MODE enabled – no services will be disabled")

# ---------------------------------------------------------------------------
# GCP Project
# ---------------------------------------------------------------------------
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
if not PROJECT_ID:
    raise EnvironmentError("GCP_PROJECT_ID environment variable is required")

# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------
CURRENCY_CODE = os.environ.get("CURRENCY_CODE", "USD")

# ---------------------------------------------------------------------------
# Per-service monthly budgets (in CURRENCY_CODE)
# ---------------------------------------------------------------------------
VERTEX_AI_MONTHLY_BUDGET = float(os.environ.get("VERTEX_AI_MONTHLY_BUDGET", "100"))
BIGQUERY_MONTHLY_BUDGET = float(os.environ.get("BIGQUERY_MONTHLY_BUDGET", "100"))
FIRESTORE_MONTHLY_BUDGET = float(os.environ.get("FIRESTORE_MONTHLY_BUDGET", "100"))

# ---------------------------------------------------------------------------
# Overall project monthly budget (optional safety-net, default sum of all)
# ---------------------------------------------------------------------------
MONTHLY_BUDGET_AMOUNT = float(
    os.environ.get(
        "MONTHLY_BUDGET_AMOUNT",
        str(VERTEX_AI_MONTHLY_BUDGET + BIGQUERY_MONTHLY_BUDGET + FIRESTORE_MONTHLY_BUDGET),
    )
)

# ---------------------------------------------------------------------------
# Notification / Email
# ---------------------------------------------------------------------------
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")

# Comma-separated list of recipient email addresses
ALERT_RECEIVER_EMAILS = [
    e.strip()
    for e in os.environ.get("ALERT_RECEIVER_EMAILS", "").split(",")
    if e.strip()
]

# Threshold percentages
WARNING_THRESHOLD_PCT = float(os.environ.get("WARNING_THRESHOLD_PCT", "80"))
CRITICAL_THRESHOLD_PCT = float(os.environ.get("CRITICAL_THRESHOLD_PCT", "100"))

# ---------------------------------------------------------------------------
# Pub/Sub topic for budget alerts (created by deploy.sh)
# ---------------------------------------------------------------------------
PUBSUB_TOPIC_NAME = os.environ.get("PUBSUB_TOPIC_NAME", "budget-guard-alerts")

# ---------------------------------------------------------------------------
# Scheduler interval hint (informational – actual cron is set in deploy.sh)
# ---------------------------------------------------------------------------
SCHEDULER_INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", "10"))

# ---------------------------------------------------------------------------
# Service API names (the ones we monitor and can disable)
# ---------------------------------------------------------------------------
MONITORED_API_SERVICES = {
    "vertex_ai": "aiplatform.googleapis.com",
    "bigquery": "bigquery.googleapis.com",
    "firestore": "firestore.googleapis.com",
}

# ---------------------------------------------------------------------------
# App config summary (for health-check / startup log)
# ---------------------------------------------------------------------------
APP_CONFIG: dict[str, Any] = {
    "project_id": PROJECT_ID,
    "currency": CURRENCY_CODE,
    "vertex_ai_budget": VERTEX_AI_MONTHLY_BUDGET,
    "bigquery_budget": BIGQUERY_MONTHLY_BUDGET,
    "firestore_budget": FIRESTORE_MONTHLY_BUDGET,
    "monthly_budget_total": MONTHLY_BUDGET_AMOUNT,
    "warning_threshold_pct": WARNING_THRESHOLD_PCT,
    "critical_threshold_pct": CRITICAL_THRESHOLD_PCT,
    "dry_run": DRY_RUN_MODE,
    "debug": DEBUG_MODE,
    "scheduler_interval_min": SCHEDULER_INTERVAL_MINUTES,
}

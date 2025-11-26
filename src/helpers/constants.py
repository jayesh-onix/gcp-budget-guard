"""Manage all constants / shared ressources."""

import os

from helpers.logger import GCPLogger

# Generic Global Env Variables
TRUE_VALUES = ("true", "1", "yes")

# Debug Mode / Level for the Logger
DEBUG_MODE = os.environ.get("DEBUG_MODE", default="False").lower() in TRUE_VALUES
GCP_LOGGER = GCPLogger(debug=DEBUG_MODE)
GCP_LOGGER.info(msg="Debugger Up&Ready!")

# GCP Project ID (name) | Raise if not set
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCP_LOGGER.debug(msg=f"GCP Project ID: {PROJECT_ID}")

# GCP API List which will be disabled in case of budget reached
API_LIST = [
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "firestore.googleapis.com",
]

# Nuke Project APIs
NUKE_MODE = os.environ.get("NUKE_MODE", default="False").lower() in TRUE_VALUES

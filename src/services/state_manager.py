"""Persistent state management for budget baselines, alert tracking, and audit history.

Supports two storage backends:

* **GCS (default in production)** – state is stored as a JSON blob in a
  Google Cloud Storage bucket.  Survives Cloud Run container restarts,
  scale-to-zero, and redeployments.  GCS is *not* a monitored service,
  so NoBBomb will never disable its own storage backend.
* **Local file (fallback / testing)** – used when ``BUDGET_STATE_BUCKET``
  is empty.  State lives on the local filesystem (``/tmp`` by default)
  and is lost when the container restarts.

Thread-safe via a threading.Lock so concurrent FastAPI requests sharing
a single BudgetMonitorService singleton do not corrupt state.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from helpers.constants import APP_LOGGER


class StateManager:
    """Thread-safe persistent state for budget guard operations.

    Manages:
    * **Cost baselines** – saved when admin calls ``/reset``, subtracted
      from cumulative monitoring data on each check cycle so that the
      service is not immediately re-disabled.
    * **Last known costs** – cumulative cost recorded during each check,
      used as the baseline value during reset.
    * **Alert tracking** – which alert levels (WARNING / CRITICAL) have
      been sent per service, persisted to survive container restarts.
    * **Action history** – audit log of resets / disables.
    """

    def __init__(
        self,
        state_path: str | None = None,
        bucket_name: str | None = None,
        blob_name: str | None = None,
    ) -> None:
        from helpers.constants import (
            BUDGET_STATE_BUCKET,
            BUDGET_STATE_BLOB,
            BUDGET_STATE_PATH,
        )

        self._lock = threading.Lock()

        # ── Determine storage backend ─────────────────────────────────
        self._bucket_name: str = bucket_name or BUDGET_STATE_BUCKET
        self._blob_name: str = blob_name or BUDGET_STATE_BLOB
        self._gcs_bucket = None  # lazy-initialised on first use

        if self._bucket_name:
            self._use_gcs = True
            self._path = ""  # not used when GCS is active
            APP_LOGGER.info(
                msg=(
                    f"StateManager using GCS: "
                    f"gs://{self._bucket_name}/{self._blob_name}"
                )
            )
        else:
            self._use_gcs = False
            self._path = state_path or BUDGET_STATE_PATH
            APP_LOGGER.info(
                msg=f"StateManager using local file: {self._path}"
            )

        self._state: dict[str, Any] = self._load()
        backend = (
            f"gs://{self._bucket_name}/{self._blob_name}"
            if self._use_gcs
            else self._path
        )
        APP_LOGGER.info(msg=f"StateManager initialised (backend={backend})")

    # ── Baselines ─────────────────────────────────────────────────────────

    def get_baseline(self, service_key: str) -> float:
        """Return the cost baseline for a service (0.0 if not set)."""
        with self._lock:
            return float(self._state.get("baselines", {}).get(service_key, 0.0))

    def set_baseline(self, service_key: str, cost: float) -> None:
        """Save a cost baseline for a service (used during /reset)."""
        with self._lock:
            self._state.setdefault("baselines", {})[service_key] = round(cost, 6)
            self._save()
        APP_LOGGER.info(msg=f"Baseline set for {service_key}: ${cost:.4f}")

    # ── Last Known Costs ──────────────────────────────────────────────────

    def get_last_known_cost(self, service_key: str) -> float | None:
        """Return the last cumulative cost recorded during a check cycle."""
        with self._lock:
            val = self._state.get("last_known_costs", {}).get(service_key)
            return float(val) if val is not None else None

    def set_last_known_cost(self, service_key: str, cost: float) -> None:
        """Save the cumulative cost from the latest check cycle."""
        with self._lock:
            self._state.setdefault("last_known_costs", {})[service_key] = round(cost, 6)
            self._save()

    # ── Alert Tracking ────────────────────────────────────────────────────

    def get_alerts_sent(self) -> dict[str, list[str]]:
        """Return the full alerts-sent tracking dict."""
        with self._lock:
            return {
                k: list(v)
                for k, v in self._state.get("alerts_sent", {}).items()
            }

    def set_alert_sent(self, service_key: str, level: str) -> None:
        """Record that an alert of a given level was sent for a service."""
        with self._lock:
            alerts = self._state.setdefault("alerts_sent", {})
            levels = alerts.setdefault(service_key, [])
            if level not in levels:
                levels.append(level)
            self._save()

    def reset_alerts(self, service_key: str) -> None:
        """Clear alert tracking for a service (allows new alerts)."""
        with self._lock:
            self._state.get("alerts_sent", {}).pop(service_key, None)
            self._save()
        APP_LOGGER.info(msg=f"Alert tracking cleared for {service_key}")

    # ── Action History ────────────────────────────────────────────────────

    def record_action(self, action: str, details: dict[str, Any]) -> None:
        """Append an entry to the action history log (audit trail)."""
        with self._lock:
            history = self._state.setdefault("action_history", [])
            history.append(
                {
                    "action": action,
                    "details": details,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            # Keep last 200 entries to bound file size
            if len(history) > 200:
                self._state["action_history"] = history[-200:]
            self._save()

    def get_action_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent action history entries."""
        with self._lock:
            return list(self._state.get("action_history", [])[-limit:])

    # ── Month Boundary ────────────────────────────────────────────────────

    def check_month_rollover(self) -> bool:
        """Clear baselines and alerts when a new billing month starts.

        Cloud Monitoring cumulative data resets on the 1st of each month.
        Old baselines would make effective cost go negative, so we clear
        everything.

        Returns True if a rollover was detected and state was cleared.
        """
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self._lock:
            stored_month = self._state.get("current_month", "")
            if stored_month == current_month:
                return False

            APP_LOGGER.info(
                msg=(
                    f"Month rollover detected: {stored_month or '(none)'} → "
                    f"{current_month}. Clearing baselines and alert counters."
                )
            )
            self._state["baselines"] = {}
            self._state["alerts_sent"] = {}
            self._state["last_known_costs"] = {}
            self._state["current_month"] = current_month
            self._save()
            return True

    # ── Serialisation ─────────────────────────────────────────────────────

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of the full state (for /status endpoints)."""
        with self._lock:
            return dict(self._state)

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_gcs_bucket(self):
        """Lazy-initialise the GCS bucket handle (avoids import at module level)."""
        if self._gcs_bucket is None:
            from google.cloud import storage

            client = storage.Client()
            self._gcs_bucket = client.bucket(self._bucket_name)
        return self._gcs_bucket

    def _load(self) -> dict[str, Any]:
        """Load state from the configured backend.  Returns empty dict on any failure."""
        if self._use_gcs:
            return self._load_from_gcs()
        return self._load_from_file()

    def _save(self) -> None:
        """Persist state to the configured backend.  Fails silently (logged)."""
        if self._use_gcs:
            self._save_to_gcs()
        else:
            self._save_to_file()

    # ── GCS backend ───────────────────────────────────────────────────

    def _load_from_gcs(self) -> dict[str, Any]:
        """Download state JSON from a GCS blob."""
        try:
            bucket = self._get_gcs_bucket()
            blob = bucket.blob(self._blob_name)
            raw = blob.download_as_text()
            data = json.loads(raw)
            APP_LOGGER.info(
                msg=f"State loaded from gs://{self._bucket_name}/{self._blob_name}"
            )
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            APP_LOGGER.info(
                msg=(
                    f"Could not load state from GCS "
                    f"(gs://{self._bucket_name}/{self._blob_name}): {exc} "
                    f"— starting fresh"
                )
            )
            return {}

    def _save_to_gcs(self) -> None:
        """Upload state JSON to a GCS blob."""
        try:
            bucket = self._get_gcs_bucket()
            blob = bucket.blob(self._blob_name)
            blob.upload_from_string(
                json.dumps(self._state, indent=2, default=str),
                content_type="application/json",
            )
        except Exception as exc:
            APP_LOGGER.error(
                msg=(
                    f"Failed to save state to GCS "
                    f"(gs://{self._bucket_name}/{self._blob_name}): {exc}"
                )
            )

    # ── Local-file backend ────────────────────────────────────────────

    def _load_from_file(self) -> dict[str, Any]:
        """Load state from a local JSON file."""
        if not self._path:
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            APP_LOGGER.info(msg=f"State loaded from {self._path}")
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            APP_LOGGER.info(
                msg=f"No existing state file at {self._path} — starting fresh"
            )
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            APP_LOGGER.warning(
                msg=f"Could not load state from {self._path}: {exc} — starting fresh"
            )
            return {}

    def _save_to_file(self) -> None:
        """Persist state to a local JSON file."""
        if not self._path:
            return
        try:
            dir_path = os.path.dirname(self._path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, default=str)
        except OSError as exc:
            APP_LOGGER.error(msg=f"Failed to save state to {self._path}: {exc}")

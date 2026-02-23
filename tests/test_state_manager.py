"""Unit tests for the StateManager (persistent state)."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from services.state_manager import StateManager


class TestStateManager:
    """Tests for StateManager file-based persistence."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a StateManager with a temporary file for each test."""
        self.state_path = str(tmp_path / "test_state.json")
        self.mgr = StateManager(state_path=self.state_path)

    # ── Baselines ─────────────────────────────────────────────────────

    def test_default_baseline_is_zero(self):
        assert self.mgr.get_baseline("vertex_ai") == 0.0

    def test_set_and_get_baseline(self):
        self.mgr.set_baseline("vertex_ai", 105.5)
        assert self.mgr.get_baseline("vertex_ai") == pytest.approx(105.5, abs=0.001)

    def test_baseline_persists_to_file(self):
        self.mgr.set_baseline("bigquery", 42.0)
        # Create a new manager from the same file
        mgr2 = StateManager(state_path=self.state_path)
        assert mgr2.get_baseline("bigquery") == pytest.approx(42.0, abs=0.001)

    def test_baselines_independent_per_service(self):
        self.mgr.set_baseline("vertex_ai", 100.0)
        self.mgr.set_baseline("bigquery", 200.0)
        assert self.mgr.get_baseline("vertex_ai") == pytest.approx(100.0)
        assert self.mgr.get_baseline("bigquery") == pytest.approx(200.0)
        assert self.mgr.get_baseline("firestore") == 0.0

    # ── Last Known Costs ──────────────────────────────────────────────

    def test_last_known_cost_default_none(self):
        assert self.mgr.get_last_known_cost("vertex_ai") is None

    def test_set_and_get_last_known_cost(self):
        self.mgr.set_last_known_cost("vertex_ai", 55.5)
        assert self.mgr.get_last_known_cost("vertex_ai") == pytest.approx(55.5)

    def test_last_known_cost_persists(self):
        self.mgr.set_last_known_cost("firestore", 12.0)
        mgr2 = StateManager(state_path=self.state_path)
        assert mgr2.get_last_known_cost("firestore") == pytest.approx(12.0)

    # ── Alert Tracking ────────────────────────────────────────────────

    def test_alerts_empty_by_default(self):
        assert self.mgr.get_alerts_sent() == {}

    def test_set_alert_sent(self):
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        alerts = self.mgr.get_alerts_sent()
        assert "WARNING" in alerts["vertex_ai"]

    def test_alert_deduplication(self):
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        alerts = self.mgr.get_alerts_sent()
        assert alerts["vertex_ai"].count("WARNING") == 1

    def test_multiple_alert_levels(self):
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        self.mgr.set_alert_sent("vertex_ai", "CRITICAL")
        alerts = self.mgr.get_alerts_sent()
        assert set(alerts["vertex_ai"]) == {"WARNING", "CRITICAL"}

    def test_reset_alerts_clears_service(self):
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        self.mgr.set_alert_sent("vertex_ai", "CRITICAL")
        self.mgr.reset_alerts("vertex_ai")
        alerts = self.mgr.get_alerts_sent()
        assert "vertex_ai" not in alerts

    def test_reset_alerts_does_not_affect_other_services(self):
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        self.mgr.set_alert_sent("bigquery", "WARNING")
        self.mgr.reset_alerts("vertex_ai")
        alerts = self.mgr.get_alerts_sent()
        assert "vertex_ai" not in alerts
        assert "WARNING" in alerts["bigquery"]

    def test_alerts_persist(self):
        self.mgr.set_alert_sent("vertex_ai", "CRITICAL")
        mgr2 = StateManager(state_path=self.state_path)
        assert "CRITICAL" in mgr2.get_alerts_sent()["vertex_ai"]

    # ── Action History ────────────────────────────────────────────────

    def test_action_history_empty_by_default(self):
        assert self.mgr.get_action_history() == []

    def test_record_action(self):
        self.mgr.record_action("reset_service", {"service_key": "vertex_ai"})
        history = self.mgr.get_action_history()
        assert len(history) == 1
        assert history[0]["action"] == "reset_service"
        assert "timestamp" in history[0]

    def test_action_history_limit(self):
        for i in range(210):
            self.mgr.record_action("test", {"i": i})
        history = self.mgr.get_action_history(limit=300)
        assert len(history) <= 200

    # ── Month Rollover ────────────────────────────────────────────────

    def test_month_rollover_clears_state(self):
        self.mgr.set_baseline("vertex_ai", 100.0)
        self.mgr.set_alert_sent("vertex_ai", "WARNING")
        self.mgr.set_last_known_cost("vertex_ai", 100.0)

        # Simulate a different month
        self.mgr._state["current_month"] = "1999-01"
        result = self.mgr.check_month_rollover()

        assert result is True
        assert self.mgr.get_baseline("vertex_ai") == 0.0
        assert self.mgr.get_alerts_sent() == {}
        assert self.mgr.get_last_known_cost("vertex_ai") is None

    def test_same_month_no_rollover(self):
        self.mgr.check_month_rollover()  # set current month
        self.mgr.set_baseline("vertex_ai", 100.0)

        result = self.mgr.check_month_rollover()
        assert result is False
        assert self.mgr.get_baseline("vertex_ai") == pytest.approx(100.0)

    # ── File resilience ───────────────────────────────────────────────

    def test_missing_file_starts_empty(self):
        mgr = StateManager(state_path="/tmp/nonexistent_test_xyz.json")
        assert mgr.get_baseline("vertex_ai") == 0.0
        # Clean up
        try:
            os.remove("/tmp/nonexistent_test_xyz.json")
        except OSError:
            pass

    def test_corrupt_file_starts_empty(self):
        with open(self.state_path, "w") as f:
            f.write("NOT VALID JSON {{{")
        mgr = StateManager(state_path=self.state_path)
        assert mgr.get_baseline("vertex_ai") == 0.0

    def test_as_dict_returns_copy(self):
        self.mgr.set_baseline("vertex_ai", 50.0)
        d = self.mgr.as_dict()
        assert d["baselines"]["vertex_ai"] == pytest.approx(50.0)


class TestStateManagerGCS:
    """Tests for StateManager with GCS backend (mocked)."""

    def _make_mock_bucket(self, existing_data: dict | None = None):
        """Create a mock GCS bucket with optional pre-existing blob data."""
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        if existing_data is not None:
            mock_blob.download_as_text.return_value = json.dumps(existing_data)
        else:
            # Simulate blob not found
            from google.api_core.exceptions import NotFound
            mock_blob.download_as_text.side_effect = NotFound("blob not found")

        mock_bucket.blob.return_value = mock_blob
        return mock_bucket, mock_blob

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_backend_selected_when_bucket_set(self, mock_get_bucket):
        """StateManager should use GCS when bucket_name is provided."""
        mock_bucket, _ = self._make_mock_bucket()
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")

        assert mgr._use_gcs is True
        assert mgr._bucket_name == "test-bucket"
        assert mgr._blob_name == "state.json"

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_load_existing_state(self, mock_get_bucket):
        """StateManager should load existing state from GCS."""
        existing = {"baselines": {"vertex_ai": 100.0}, "alerts_sent": {}}
        mock_bucket, _ = self._make_mock_bucket(existing_data=existing)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")

        assert mgr.get_baseline("vertex_ai") == pytest.approx(100.0)

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_load_empty_when_blob_missing(self, mock_get_bucket):
        """StateManager should start empty if the GCS blob doesn't exist."""
        mock_bucket, _ = self._make_mock_bucket(existing_data=None)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")

        assert mgr.get_baseline("vertex_ai") == 0.0
        assert mgr.get_alerts_sent() == {}

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_save_on_set_baseline(self, mock_get_bucket):
        """Setting a baseline should upload state to GCS."""
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=None)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        mgr.set_baseline("vertex_ai", 200.0)

        # upload_from_string should have been called
        mock_blob.upload_from_string.assert_called()
        uploaded = json.loads(mock_blob.upload_from_string.call_args[0][0])
        assert uploaded["baselines"]["vertex_ai"] == pytest.approx(200.0)

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_save_on_set_alert(self, mock_get_bucket):
        """Setting an alert should upload state to GCS."""
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=None)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        mgr.set_alert_sent("bigquery", "WARNING")

        mock_blob.upload_from_string.assert_called()
        uploaded = json.loads(mock_blob.upload_from_string.call_args[0][0])
        assert "WARNING" in uploaded["alerts_sent"]["bigquery"]

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_save_on_record_action(self, mock_get_bucket):
        """Recording an action should upload state to GCS."""
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=None)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        mgr.record_action("reset_service", {"service_key": "vertex_ai"})

        mock_blob.upload_from_string.assert_called()
        uploaded = json.loads(mock_blob.upload_from_string.call_args[0][0])
        assert len(uploaded["action_history"]) == 1
        assert uploaded["action_history"][0]["action"] == "reset_service"

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_month_rollover_clears_and_saves(self, mock_get_bucket):
        """Month rollover should clear baselines and persist to GCS."""
        existing = {
            "baselines": {"vertex_ai": 100.0},
            "alerts_sent": {"vertex_ai": ["WARNING"]},
            "last_known_costs": {"vertex_ai": 95.0},
            "current_month": "1999-01",
        }
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=existing)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        result = mgr.check_month_rollover()

        assert result is True
        assert mgr.get_baseline("vertex_ai") == 0.0
        assert mgr.get_alerts_sent() == {}
        mock_blob.upload_from_string.assert_called()

    def test_local_fallback_when_no_bucket(self, tmp_path):
        """StateManager should use local file when bucket_name is empty."""
        path = str(tmp_path / "fallback_state.json")
        mgr = StateManager(state_path=path, bucket_name="")

        assert mgr._use_gcs is False
        mgr.set_baseline("firestore", 77.0)

        # Verify it was written to local file
        with open(path) as f:
            data = json.load(f)
        assert data["baselines"]["firestore"] == pytest.approx(77.0)

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_save_failure_logged_not_raised(self, mock_get_bucket):
        """GCS save failure should be logged but not raise an exception."""
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=None)
        mock_blob.upload_from_string.side_effect = Exception("GCS write failed")
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        # Should not raise
        mgr.set_baseline("vertex_ai", 50.0)
        # In-memory state should still be updated
        assert mgr.get_baseline("vertex_ai") == pytest.approx(50.0)

    @patch("services.state_manager.StateManager._get_gcs_bucket")
    def test_gcs_last_known_cost_round_trip(self, mock_get_bucket):
        """Last known cost should round-trip through GCS."""
        mock_bucket, mock_blob = self._make_mock_bucket(existing_data=None)
        mock_get_bucket.return_value = mock_bucket

        mgr = StateManager(bucket_name="test-bucket", blob_name="state.json")
        mgr.set_last_known_cost("vertex_ai", 123.456)

        assert mgr.get_last_known_cost("vertex_ai") == pytest.approx(123.456)
        mock_blob.upload_from_string.assert_called()

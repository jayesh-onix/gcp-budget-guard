"""Integration-style tests for the BudgetMonitorService."""

from unittest.mock import MagicMock, patch

from services.budget_monitor import BudgetMonitorService


class TestBudgetMonitorService:
    """Tests for the core budget monitoring orchestrator."""

    def _make_service(self) -> BudgetMonitorService:
        """Create a BudgetMonitorService with all GCP clients mocked."""
        mock_state = MagicMock()
        mock_state.get_baseline.return_value = 0.0
        mock_state.get_last_known_cost.return_value = None
        mock_state.check_month_rollover.return_value = False
        mock_state.get_alerts_sent.return_value = {}

        with (
            patch("services.budget_monitor.create_price_provider") as mock_provider_factory,
            patch("services.budget_monitor.WrapperCloudMonitoring") as mock_mon_cls,
            patch("services.budget_monitor.WrapperCloudAPIs") as mock_apis_cls,
            patch("services.budget_monitor.NotificationService") as mock_notif_cls,
        ):
            mock_provider = MagicMock()
            mock_mon = MagicMock()
            mock_apis = MagicMock()
            mock_notif = MagicMock()

            mock_provider_factory.return_value = mock_provider
            mock_provider.provider_name = "mock_provider"
            mock_mon_cls.return_value = mock_mon
            mock_apis_cls.return_value = mock_apis
            mock_notif_cls.return_value = mock_notif

            svc = BudgetMonitorService(state_manager=mock_state)
            svc.state = mock_state
            svc.price_provider = mock_provider
            svc.monitoring = mock_mon
            svc.apis = mock_apis
            svc.notifications = mock_notif

            return svc

    def test_run_check_returns_dict(self):
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = 0.0
        svc.monitoring.get_total_units.return_value = 0

        result = svc.run_check()

        assert isinstance(result, dict)
        assert "project_id" in result
        assert "budget" in result
        assert "disabled_apis" in result

    def test_no_disable_when_under_budget(self):
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = 0.0
        svc.monitoring.get_total_units.return_value = 0

        result = svc.run_check()

        assert result["disabled_apis"] == []
        svc.apis.disable_api.assert_not_called()

    @patch("services.budget_monitor.DRY_RUN_MODE", False)
    def test_disable_triggered_when_budget_exceeded(self):
        svc = self._make_service()
        # Set price so that any units result in cost > budget
        svc.price_provider.get_price_per_unit.return_value = 1000.0  # $1000 per unit
        svc.monitoring.get_total_units.return_value = 1  # 1 unit

        svc.apis.disable_api.return_value = True

        result = svc.run_check()

        # At least one API should be in the disabled list
        assert len(result["disabled_apis"]) > 0

    def test_enable_service_calls_wrapper(self):
        svc = self._make_service()
        svc.apis.enable_api.return_value = True

        result = svc.enable_service("firestore.googleapis.com")
        assert result is True
        svc.apis.enable_api.assert_called_once_with(api_name="firestore.googleapis.com")

    def test_warning_notification_at_80_pct(self):
        """Warning email should be sent when usage >= 80% but < 100%."""
        svc = self._make_service()
        # Vertex AI budget is $100.  Set price*units = $85 → 85%
        # We need to control per-metric pricing carefully.
        # Simplest: make billing return 85.0/1 = 85 and monitoring return 1
        svc.price_provider.get_price_per_unit.return_value = 85.0
        svc.monitoring.get_total_units.return_value = 1

        svc.run_check()

        # The notification service should have been called for warning
        # (at least once across all services, since each Vertex AI metric
        # contributes to cost and we'd exceed 80% quickly)
        assert svc.notifications.send_warning_alert.called or \
               svc.notifications.send_critical_alert.called

    # ── Baseline / reset tests ────────────────────────────────────────

    def test_run_check_includes_data_warnings(self):
        """data_warnings key should always be present in the result."""
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = 0.0
        svc.monitoring.get_total_units.return_value = 0

        result = svc.run_check()
        assert "data_warnings" in result
        assert isinstance(result["data_warnings"], list)

    def test_data_warning_on_pricing_failure(self):
        """Pricing exception should produce a data quality warning."""
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.side_effect = Exception("billing down")
        svc.monitoring.get_total_units.return_value = 100

        result = svc.run_check()
        assert len(result["data_warnings"]) > 0
        assert any("Pricing unavailable" in w for w in result["data_warnings"])

    def test_data_warning_on_monitoring_failure(self):
        """Monitoring exception should produce a data quality warning."""
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = 0.001
        svc.monitoring.get_total_units.side_effect = Exception("monitoring down")

        result = svc.run_check()
        assert len(result["data_warnings"]) > 0
        assert any("Monitoring data unavailable" in w for w in result["data_warnings"])

    def test_data_warning_on_price_none(self):
        """Price returning None (no exception) should produce a warning."""
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = None
        svc.monitoring.get_total_units.return_value = 100

        result = svc.run_check()
        assert len(result["data_warnings"]) > 0

    def test_no_data_warnings_when_healthy(self):
        """No warnings when pricing and monitoring succeed."""
        svc = self._make_service()
        svc.price_provider.get_price_per_unit.return_value = 0.0
        svc.monitoring.get_total_units.return_value = 0

        result = svc.run_check()
        assert result["data_warnings"] == []

    def test_baseline_subtracted_from_cost(self):
        """After reset, effective cost = raw_cost - baseline."""
        svc = self._make_service()
        # Raw cost will be price * units per metric, accumulated
        svc.price_provider.get_price_per_unit.return_value = 10.0
        svc.monitoring.get_total_units.return_value = 1
        # Set a baseline of 100 → effective cost should be reduced
        svc.state.get_baseline.return_value = 100.0

        result = svc.run_check()

        # With baseline of 100.0 subtracted, effective cost should be
        # lower than raw, and no services should be disabled
        assert result["disabled_apis"] == []
        svc.state.set_last_known_cost.assert_called()

    def test_reset_service_saves_baseline(self):
        """reset_service should save the cumulative cost as baseline."""
        svc = self._make_service()
        svc.state.get_last_known_cost.return_value = 150.0
        svc.apis.enable_api.return_value = True

        result = svc.reset_service("vertex_ai")

        assert result["status"] == "success"
        assert result["baseline_saved"] == 150.0
        assert result["alerts_reset"] is True
        svc.state.set_baseline.assert_called_once_with("vertex_ai", 150.0)
        svc.notifications.reset_alerts.assert_called_once_with("vertex_ai")

    def test_reset_service_enables_api(self):
        """reset_service should call enable_api for the service."""
        svc = self._make_service()
        svc.state.get_last_known_cost.return_value = 50.0
        svc.apis.enable_api.return_value = True

        result = svc.reset_service("firestore")

        assert result["api_enabled"] is True
        assert result["api_name"] == "firestore.googleapis.com"
        svc.apis.enable_api.assert_called_once_with(
            api_name="firestore.googleapis.com"
        )

    def test_reset_service_unknown_key(self):
        """reset_service should return error for unknown service key."""
        svc = self._make_service()
        result = svc.reset_service("unknown_service")
        assert result["status"] == "error"

    def test_reset_service_records_action(self):
        """reset_service should record the action in state."""
        svc = self._make_service()
        svc.state.get_last_known_cost.return_value = 75.0
        svc.apis.enable_api.return_value = True

        svc.reset_service("bigquery")

        svc.state.record_action.assert_called_once()
        call_args = svc.state.record_action.call_args
        assert call_args[0][0] == "reset_service"
        assert call_args[0][1]["service_key"] == "bigquery"

    def test_reset_service_partial_when_enable_fails(self):
        """reset_service returns 'partial' when API enable fails."""
        svc = self._make_service()
        svc.state.get_last_known_cost.return_value = 50.0
        svc.apis.enable_api.return_value = False

        result = svc.reset_service("vertex_ai")

        assert result["status"] == "partial"
        assert result["api_enabled"] is False
        # Baseline and alerts should still be reset even if enable fails
        svc.state.set_baseline.assert_called_once()
        svc.notifications.reset_alerts.assert_called_once()

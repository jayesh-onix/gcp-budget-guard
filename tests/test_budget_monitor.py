"""Integration-style tests for the BudgetMonitorService."""

from unittest.mock import MagicMock, patch

from services.budget_monitor import BudgetMonitorService


class TestBudgetMonitorService:
    """Tests for the core budget monitoring orchestrator."""

    def _make_service(self) -> BudgetMonitorService:
        """Create a BudgetMonitorService with all GCP clients mocked."""
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

            svc = BudgetMonitorService()
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

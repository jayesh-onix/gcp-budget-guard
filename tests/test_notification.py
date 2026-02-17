"""Unit tests for the notification service (email sending with cooldown)."""

import time
from unittest.mock import MagicMock, patch

from config.budget import ServiceBudget
from services.notification import NotificationService


class TestNotificationService:
    """Tests for NotificationService."""

    def _make_svc(self, expense: float = 120.0, budget: float = 100.0) -> ServiceBudget:
        return ServiceBudget(
            service_key="vertex_ai",
            api_name="aiplatform.googleapis.com",
            monthly_budget=budget,
            current_expense=expense,
        )

    def test_disabled_when_no_smtp(self):
        """Service should be disabled when SMTP is not configured."""
        svc = NotificationService()
        assert svc._enabled is False

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_enabled_when_configured(self):
        svc = NotificationService()
        assert svc._enabled is True

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    @patch("services.notification.ALERT_COOLDOWN_SECONDS", 0)
    def test_send_warning_calls_smtp(self):
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_warning_alert(self._make_svc())
            assert result is True
            mock_send.assert_called_once()

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    @patch("services.notification.ALERT_COOLDOWN_SECONDS", 9999)
    def test_cooldown_prevents_duplicate(self):
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True):
            # First call should send
            result1 = svc.send_warning_alert(self._make_svc())
            assert result1 is True

            # Second call within cooldown should be suppressed
            result2 = svc.send_warning_alert(self._make_svc())
            assert result2 is False

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["a@b.com", "c@d.com"])
    @patch("services.notification.ALERT_COOLDOWN_SECONDS", 0)
    def test_critical_alert_includes_disabled_flag(self):
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            svc.send_critical_alert(self._make_svc(), disabled=True)
            call_args = mock_send.call_args
            body = call_args[0][1]
            assert "Service Disabled" in body

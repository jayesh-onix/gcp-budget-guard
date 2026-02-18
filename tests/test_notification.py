"""Unit tests for the notification service (email + Pub/Sub with per-service alert counter)."""

import json
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
        assert svc._email_enabled is False

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_enabled_when_configured(self):
        svc = NotificationService()
        assert svc._enabled is True
        assert svc._email_enabled is True

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_send_warning_calls_smtp(self):
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                result = svc.send_warning_alert(self._make_svc())
                assert result is True
                mock_send.assert_called_once()

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_warning_sent_only_once_per_service(self):
        """Second WARNING for the same service must be silently blocked."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                result1 = svc.send_warning_alert(self._make_svc())
                assert result1 is True
                assert svc.get_alert_count("vertex_ai") == 1

                result2 = svc.send_warning_alert(self._make_svc())
                assert result2 is False
                assert svc.get_alert_count("vertex_ai") == 1

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["a@b.com", "c@d.com"])
    def test_critical_alert_includes_disabled_flag(self):
        """CRITICAL email body must mention 'Service Disabled'."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc.send_critical_alert(self._make_svc(), disabled=True)
                call_args = mock_send.call_args
                body = call_args[0][1]
                assert "Service Disabled" in body

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_critical_only_sent_after_disablement(self):
        """CRITICAL alert must NOT fire when disabled=False."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                result = svc.send_critical_alert(self._make_svc(), disabled=False)
                assert result is False
                mock_send.assert_not_called()
                assert svc.get_alert_count("vertex_ai") == 0

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_max_two_alerts_per_service(self):
        """After WARNING + CRITICAL, no further alerts for that service."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc.send_warning_alert(self._make_svc(expense=85.0))
                svc.send_critical_alert(self._make_svc(), disabled=True)
                assert svc.get_alert_count("vertex_ai") == 2

                r1 = svc.send_warning_alert(self._make_svc(expense=85.0))
                r2 = svc.send_critical_alert(self._make_svc(), disabled=True)
                assert r1 is False
                assert r2 is False

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_reset_alerts_allows_resending(self):
        """After reset, alerts for the service can be sent again."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc.send_warning_alert(self._make_svc())
                assert svc.get_alert_count("vertex_ai") == 1

                svc.reset_alerts("vertex_ai")
                assert svc.get_alert_count("vertex_ai") == 0

                result = svc.send_warning_alert(self._make_svc())
                assert result is True
                assert svc.get_alert_count("vertex_ai") == 1

    @patch("services.notification.SMTP_EMAIL", "test@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "password123")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["admin@company.com"])
    def test_independent_counts_per_service(self):
        """Alert counts for different services must be independent."""
        svc = NotificationService()
        with patch.object(svc, "_send_email", return_value=True):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc_bq = ServiceBudget(
                    service_key="bigquery",
                    api_name="bigquery.googleapis.com",
                    monthly_budget=100.0,
                    current_expense=120.0,
                )
                svc.send_warning_alert(self._make_svc())
                assert svc.get_alert_count("vertex_ai") == 1
                assert svc.get_alert_count("bigquery") == 0

                svc.send_warning_alert(svc_bq)
                assert svc.get_alert_count("vertex_ai") == 1
                assert svc.get_alert_count("bigquery") == 1


class TestPubSubIntegration:
    """Tests for Pub/Sub alert publishing."""

    def _make_svc(self, expense: float = 120.0, budget: float = 100.0) -> ServiceBudget:
        return ServiceBudget(
            service_key="vertex_ai",
            api_name="aiplatform.googleapis.com",
            monthly_budget=budget,
            current_expense=expense,
        )

    def test_pubsub_publish_called_on_alert(self):
        """Pub/Sub publish should be called when sending an alert."""
        svc = NotificationService()
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-123"
        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = "projects/test/topics/budget-guard-alerts"

        svc._pubsub_enabled = True
        svc._publisher = mock_publisher
        svc._topic_path = "projects/test/topics/budget-guard-alerts"

        result = svc._publish_to_pubsub("CRITICAL", self._make_svc(), disabled=True)
        assert result is True
        mock_publisher.publish.assert_called_once()

        # Verify the published data is valid JSON with expected fields
        call_args = mock_publisher.publish.call_args
        # data is passed as keyword arg
        raw_data = call_args.kwargs.get("data") or call_args[1].get("data")
        if raw_data is None:
            # data may be passed as second positional arg
            raw_data = call_args[0][1]
        data = json.loads(raw_data.decode("utf-8"))
        assert data["alert_type"] == "CRITICAL"
        assert data["service_key"] == "vertex_ai"
        assert data["service_disabled"] is True
        assert "action_taken" in data
        assert "re_enable_endpoint" in data

    def test_pubsub_disabled_returns_false(self):
        """When Pub/Sub is not configured, publish should return False."""
        svc = NotificationService()
        svc._pubsub_enabled = False
        result = svc._publish_to_pubsub("WARNING", self._make_svc(), disabled=False)
        assert result is False

    def test_pubsub_error_returns_false(self):
        """When Pub/Sub publish fails, should return False gracefully."""
        svc = NotificationService()
        mock_publisher = MagicMock()
        mock_publisher.publish.side_effect = Exception("Network error")

        svc._pubsub_enabled = True
        svc._publisher = mock_publisher
        svc._topic_path = "projects/test/topics/test"

        result = svc._publish_to_pubsub("WARNING", self._make_svc(), disabled=False)
        assert result is False

    def test_warning_pubsub_payload_no_action_taken(self):
        """Warning alerts should not include action_taken field."""
        svc = NotificationService()
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-456"
        mock_publisher.publish.return_value = mock_future

        svc._pubsub_enabled = True
        svc._publisher = mock_publisher
        svc._topic_path = "projects/test/topics/test"

        svc._publish_to_pubsub("WARNING", self._make_svc(expense=85.0), disabled=False)

        call_args = mock_publisher.publish.call_args
        raw_data = call_args.kwargs.get("data") or call_args[1].get("data")
        if raw_data is None:
            raw_data = call_args[0][1]
        data = json.loads(raw_data.decode("utf-8"))
        assert data["alert_type"] == "WARNING"
        assert data["service_disabled"] is False
        assert "action_taken" not in data

    def test_alert_sent_via_pubsub_even_without_email(self):
        """Alerts should be sent via Pub/Sub even if email is not configured."""
        svc = NotificationService()
        assert svc._email_enabled is False  # no SMTP configured

        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-789"
        mock_publisher.publish.return_value = mock_future

        svc._pubsub_enabled = True
        svc._publisher = mock_publisher
        svc._topic_path = "projects/test/topics/test"

        result = svc.send_warning_alert(self._make_svc(expense=85.0))
        assert result is True
        mock_publisher.publish.assert_called_once()

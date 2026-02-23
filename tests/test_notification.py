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


class TestMultipleEmailRecipients:
    """Verify that all addresses in ALERT_RECEIVER_EMAILS receive the alert.

    The Python code already passes the full list to server.sendmail().
    These tests guard against regressions where only the first address
    would get the message (e.g. if the list were accidentally joined into
    a single string before being passed to sendmail).
    """

    def _make_svc(self, expense: float = 120.0, budget: float = 100.0) -> ServiceBudget:
        return ServiceBudget(
            service_key="vertex_ai",
            api_name="aiplatform.googleapis.com",
            monthly_budget=budget,
            current_expense=expense,
        )

    def _smtp_mock(self):
        """Return (mock_ssl_class, mock_server_instance) pre-wired as context manager."""
        mock_server = MagicMock()
        mock_ssl_class = MagicMock()
        mock_ssl_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_ssl_class.return_value.__exit__ = MagicMock(return_value=False)
        return mock_ssl_class, mock_server

    @patch("services.notification.SMTP_EMAIL", "sender@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "app-password")
    @patch("services.notification.ALERT_RECEIVER_EMAILS",
           ["admin1@company.com", "admin2@company.com", "manager@company.com"])
    def test_sendmail_receives_all_recipients(self):
        """server.sendmail() must be called with the full recipient list, not just the first."""
        mock_ssl_class, mock_server = self._smtp_mock()
        svc = NotificationService()

        with patch("services.notification.smtplib.SMTP_SSL", mock_ssl_class):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc.send_warning_alert(self._make_svc(expense=85.0))

        mock_server.sendmail.assert_called_once()
        # second positional arg to sendmail() is the to_addrs list
        to_addrs = mock_server.sendmail.call_args[0][1]
        assert "admin1@company.com" in to_addrs
        assert "admin2@company.com" in to_addrs
        assert "manager@company.com" in to_addrs
        assert len(to_addrs) == 3

    @patch("services.notification.SMTP_EMAIL", "sender@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "app-password")
    @patch("services.notification.ALERT_RECEIVER_EMAILS",
           ["admin1@company.com", "admin2@company.com", "manager@company.com"])
    def test_to_header_lists_all_recipients(self):
        """The email To: header must show all recipient addresses, not just the first."""
        mock_ssl_class, mock_server = self._smtp_mock()
        svc = NotificationService()
        captured_message: list[str] = []

        def capture_sendmail(from_addr, to_addrs, msg_string):
            captured_message.append(msg_string)

        mock_server.sendmail.side_effect = capture_sendmail

        with patch("services.notification.smtplib.SMTP_SSL", mock_ssl_class):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                svc.send_warning_alert(self._make_svc(expense=85.0))

        assert captured_message, "sendmail was not called"
        raw_msg = captured_message[0]
        # The To: header is the joined list, e.g. "admin1@company.com, admin2@company.com, ..."
        assert "admin1@company.com" in raw_msg
        assert "admin2@company.com" in raw_msg
        assert "manager@company.com" in raw_msg

    @patch("services.notification.SMTP_EMAIL", "sender@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "app-password")
    @patch("services.notification.ALERT_RECEIVER_EMAILS",
           ["admin1@company.com", "admin2@company.com"])
    def test_critical_alert_delivered_to_all_recipients(self):
        """CRITICAL alert (service disabled) must also reach all recipients."""
        mock_ssl_class, mock_server = self._smtp_mock()
        svc = NotificationService()

        with patch("services.notification.smtplib.SMTP_SSL", mock_ssl_class):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                result = svc.send_critical_alert(self._make_svc(), disabled=True)

        assert result is True
        mock_server.sendmail.assert_called_once()
        to_addrs = mock_server.sendmail.call_args[0][1]
        assert "admin1@company.com" in to_addrs
        assert "admin2@company.com" in to_addrs
        assert len(to_addrs) == 2

    @patch("services.notification.SMTP_EMAIL", "sender@gmail.com")
    @patch("services.notification.SMTP_APP_PASSWORD", "app-password")
    @patch("services.notification.ALERT_RECEIVER_EMAILS", ["single@company.com"])
    def test_single_recipient_still_works(self):
        """Single recipient should continue to work after multi-recipient changes."""
        mock_ssl_class, mock_server = self._smtp_mock()
        svc = NotificationService()

        with patch("services.notification.smtplib.SMTP_SSL", mock_ssl_class):
            with patch.object(svc, "_publish_to_pubsub", return_value=False):
                result = svc.send_warning_alert(self._make_svc(expense=85.0))

        assert result is True
        to_addrs = mock_server.sendmail.call_args[0][1]
        assert to_addrs == ["single@company.com"]


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

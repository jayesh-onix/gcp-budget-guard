"""Email notification service with cooldown de-duplication.

Key design decisions
────────────────────
• Supports multiple recipient emails (comma-separated env var).
• Uses a per-(service, level) cooldown to prevent spamming the same
  alert every 10 minutes when the scheduler keeps firing.
• Sends via Gmail SMTP-SSL with retry logic.
• HTML emails with clear formatting for WARNING and CRITICAL levels.
"""

from __future__ import annotations

import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from config.budget import ServiceBudget
from helpers.constants import (
    ALERT_COOLDOWN_SECONDS,
    ALERT_RECEIVER_EMAILS,
    APP_LOGGER,
    PROJECT_ID,
    SMTP_APP_PASSWORD,
    SMTP_EMAIL,
    SMTP_PORT,
    SMTP_SERVER,
)


class NotificationService:
    """Send budget alert emails with cooldown de-duplication."""

    def __init__(self) -> None:
        self._enabled = bool(SMTP_EMAIL and SMTP_APP_PASSWORD and ALERT_RECEIVER_EMAILS)
        # Cooldown tracker: (service_key, level) → last-sent epoch
        self._last_sent: dict[tuple[str, str], float] = {}
        if not self._enabled:
            APP_LOGGER.warning(
                msg="Email notifications disabled – SMTP_EMAIL, SMTP_APP_PASSWORD or "
                "ALERT_RECEIVER_EMAILS not configured."
            )
        else:
            APP_LOGGER.info(
                msg=f"Notification service ready.  Recipients: {ALERT_RECEIVER_EMAILS}"
            )

    # ── public ────────────────────────────────────────────────────────────

    def send_warning_alert(self, svc: ServiceBudget) -> bool:
        """Send a WARNING email (e.g. 80 % threshold)."""
        return self._send_alert(svc, level="WARNING")

    def send_critical_alert(self, svc: ServiceBudget, disabled: bool = False) -> bool:
        """Send a CRITICAL email (100 % + service disabled)."""
        return self._send_alert(svc, level="CRITICAL", disabled=disabled)

    # ── internal ──────────────────────────────────────────────────────────

    def _send_alert(
        self, svc: ServiceBudget, level: str, disabled: bool = False
    ) -> bool:
        if not self._enabled:
            return False

        key = (svc.service_key, level)
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < ALERT_COOLDOWN_SECONDS:
            APP_LOGGER.info(
                msg=(
                    f"Skipping {level} email for {svc.service_key} "
                    f"(cooldown {ALERT_COOLDOWN_SECONDS}s not elapsed)"
                )
            )
            return False

        subject = self._subject(level, svc)
        body = self._html_body(level, svc, disabled)

        sent = self._send_email(subject, body)
        if sent:
            self._last_sent[key] = now
        return sent

    def _subject(self, level: str, svc: ServiceBudget) -> str:
        emoji = "⚠️" if level == "WARNING" else "🚨"
        return (
            f"{emoji} [{level}] GCP Budget Guard – "
            f"{svc.service_key} at {svc.usage_pct:.1f}% "
            f"(project: {PROJECT_ID})"
        )

    def _html_body(
        self, level: str, svc: ServiceBudget, disabled: bool
    ) -> str:
        colour = "#FFA500" if level == "WARNING" else "#DC3545"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        disabled_block = ""
        if disabled:
            disabled_block = f"""
            <div style="background:#DC3545;color:white;padding:12px;border-radius:4px;margin:16px 0;">
                <strong>⛔ Service Disabled:</strong> The API
                <code>{svc.api_name}</code> has been automatically disabled
                because it exceeded its monthly budget.
                <br><br>
                To re-enable, an admin can call:
                <code>POST /enable_service/{svc.api_name}</code>
            </div>
            """

        return f"""
        <html>
        <body style="font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#333;">
          <div style="max-width:600px;margin:0 auto;padding:20px;">
            <div style="background:{colour};color:white;padding:20px;text-align:center;border-radius:6px;">
              <h2 style="margin:0;">{level} – Budget Alert</h2>
              <p style="margin:4px 0 0;">GCP Budget Guard · Project <code>{PROJECT_ID}</code></p>
            </div>

            <div style="background:#f7f7f7;padding:20px;margin-top:16px;border-radius:6px;">
              <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;font-weight:bold;">Service</td>
                    <td style="padding:8px;">{svc.service_key}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">API</td>
                    <td style="padding:8px;">{svc.api_name}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Monthly Budget</td>
                    <td style="padding:8px;">${svc.monthly_budget:.2f}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Current Expense</td>
                    <td style="padding:8px;color:{colour};font-weight:bold;">
                        ${svc.current_expense:.4f}</td></tr>
                <tr><td style="padding:8px;font-weight:bold;">Usage</td>
                    <td style="padding:8px;color:{colour};font-weight:bold;">
                        {svc.usage_pct:.1f}%</td></tr>
              </table>

              {disabled_block}

              <p style="margin-top:16px;"><strong>Recommended actions:</strong></p>
              <ul>
                <li>Review active usage for <em>{svc.service_key}</em></li>
                <li>Check the GCP Billing console for details</li>
                <li>Scale down non-essential workloads if needed</li>
                <li>To re-enable a disabled service, call the <code>/enable_service</code> endpoint</li>
              </ul>
            </div>

            <p style="text-align:center;color:#999;font-size:12px;margin-top:16px;">
              Sent at {ts} by GCP Budget Guard · Do not reply
            </p>
          </div>
        </body>
        </html>
        """

    def _send_email(self, subject: str, body: str, max_retries: int = 3) -> bool:
        """Send HTML email to all recipients via SMTP-SSL with retries."""
        for attempt in range(1, max_retries + 1):
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = SMTP_EMAIL
                msg["To"] = ", ".join(ALERT_RECEIVER_EMAILS)
                msg.attach(MIMEText(body, "html"))

                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
                    server.sendmail(
                        SMTP_EMAIL, ALERT_RECEIVER_EMAILS, msg.as_string()
                    )

                APP_LOGGER.info(
                    msg=f"Email sent to {ALERT_RECEIVER_EMAILS}: {subject}"
                )
                return True

            except Exception as exc:
                APP_LOGGER.error(
                    msg=f"Email send attempt {attempt}/{max_retries} failed: {exc}"
                )
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        APP_LOGGER.error(msg=f"All email attempts failed for: {subject}")
        return False

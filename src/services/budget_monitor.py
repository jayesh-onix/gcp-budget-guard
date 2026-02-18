"""Core budget-monitoring orchestrator.

This module ties together:
  • Cloud Billing (pricing)
  • Cloud Monitoring (usage)
  • Service API control (disable / enable)
  • Email notifications

It is called by the FastAPI `/check` endpoint on every scheduler tick.
"""

from __future__ import annotations

from typing import Any

from config.budget import ProjectBudget
from config.monitored_services import MonitoredMetric
from config.monitored_services_list import SERVICE_METRICS
from helpers.constants import (
    APP_LOGGER,
    CRITICAL_THRESHOLD_PCT,
    DRY_RUN_MODE,
    PROJECT_ID,
    WARNING_THRESHOLD_PCT,
)
from services.notification import NotificationService
from wrappers.cloud_apis import WrapperCloudAPIs
from wrappers.cloud_billing import CloudBillingWrapper
from wrappers.cloud_monitoring import WrapperCloudMonitoring


class BudgetMonitorService:
    """Runs a full budget-check cycle for every monitored service."""

    def __init__(self) -> None:
        self.billing = CloudBillingWrapper()
        self.monitoring = WrapperCloudMonitoring()
        self.apis = WrapperCloudAPIs(project_id=PROJECT_ID)
        self.notifications = NotificationService()
        APP_LOGGER.info(msg="BudgetMonitorService initialised.")

    # ── public entry point ────────────────────────────────────────────────

    def run_check(self) -> dict[str, Any]:
        """Execute a full budget check cycle.  Returns a JSON-serialisable summary."""
        budget = ProjectBudget()
        disabled_apis: list[str] = []
        warnings_sent: list[str] = []
        metric_details: list[dict[str, Any]] = []

        APP_LOGGER.info(msg="=" * 72)
        APP_LOGGER.info(msg="Starting budget check cycle …")
        if DRY_RUN_MODE:
            APP_LOGGER.warning(msg="DRY RUN – no services will be disabled")
        APP_LOGGER.info(msg="=" * 72)

        for service_key, metrics in SERVICE_METRICS.items():
            svc_budget = budget.services.get(service_key)
            if svc_budget is None:
                continue

            APP_LOGGER.info(msg=f"── Checking service: {service_key} ──")

            # Compute cost for every metric that belongs to this service
            for metric in metrics:
                self._compute_metric_expense(metric)
                svc_budget.current_expense += metric.expense
                metric_details.append(metric.as_dict())

            APP_LOGGER.info(
                msg=(
                    f"  {service_key}: ${svc_budget.current_expense:.4f} "
                    f"/ ${svc_budget.monthly_budget:.2f} "
                    f"({svc_budget.usage_pct:.1f}%)"
                )
            )

            # ── Warning threshold (e.g. 80 %) ────────────────────────────
            if svc_budget.usage_pct >= WARNING_THRESHOLD_PCT and not svc_budget.is_exceeded:
                APP_LOGGER.warning(
                    msg=f"WARNING threshold reached for {service_key}: {svc_budget.usage_pct:.1f}%"
                )
                sent = self.notifications.send_warning_alert(svc_budget)
                if sent:
                    warnings_sent.append(service_key)

            # ── Critical / exceeded threshold (e.g. 100 %) ───────────────
            if svc_budget.is_exceeded:
                APP_LOGGER.warning(
                    msg=(
                        f"BUDGET EXCEEDED for {service_key}: "
                        f"${svc_budget.current_expense:.4f} >= ${svc_budget.monthly_budget:.2f}"
                    )
                )
                # Disable only this service's API
                success = self._disable_service(svc_budget.api_name)
                if success:
                    disabled_apis.append(svc_budget.api_name)

                # Send critical email
                self.notifications.send_critical_alert(svc_budget, disabled=success)

        # ── Summary ───────────────────────────────────────────────────────
        summary = {
            "project_id": PROJECT_ID,
            "dry_run": DRY_RUN_MODE,
            "budget": budget.as_dict(),
            "disabled_apis": disabled_apis,
            "warnings_sent": warnings_sent,
            "metric_details": metric_details,
        }

        APP_LOGGER.info(msg="=" * 72)
        APP_LOGGER.info(msg="Budget check cycle complete.")
        APP_LOGGER.info(msg=f"  Total project expense: ${budget.total_expense:.4f}")
        APP_LOGGER.info(msg=f"  APIs disabled this run: {disabled_apis}")
        APP_LOGGER.info(msg="=" * 72)

        return summary

    # ── helpers ────────────────────────────────────────────────────────────

    def _compute_metric_expense(self, metric: MonitoredMetric) -> None:
        """Fetch price and usage for a single metric, compute expense."""
        try:
            price = self.billing.get_sku_price_per_unit(
                service_id=metric.billing_service_id,
                sku_id=metric.billing_sku_id,
                price_tier=metric.billing_price_tier,
            )
            metric.price_per_unit = price
        except Exception as exc:
            APP_LOGGER.error(msg=f"Pricing error for {metric.label}: {exc}")
            metric.price_per_unit = None

        try:
            metric.unit_count = self.monitoring.get_total_units(
                metric_name=metric.metric_name,
                metric_filter=metric.metric_filter,
            )
        except Exception as exc:
            APP_LOGGER.error(msg=f"Monitoring error for {metric.label}: {exc}")
            metric.unit_count = 0

        if metric.price_per_unit is not None:
            metric.expense = metric.price_per_unit * metric.unit_count
        else:
            metric.expense = 0.0

        APP_LOGGER.debug(
            msg=(
                f"  {metric.label}: "
                f"units={metric.unit_count}  "
                f"price/unit={metric.price_per_unit}  "
                f"expense=${metric.expense:.6f}"
            )
        )

    def _disable_service(self, api_name: str) -> bool:
        """Disable a single API.  Respects DRY_RUN_MODE."""
        if DRY_RUN_MODE:
            APP_LOGGER.warning(msg=f"[DRY RUN] Would disable: {api_name}")
            return False
        return self.apis.disable_api(api_name=api_name)

    # ── manual re-enable ──────────────────────────────────────────────────

    def enable_service(self, api_name: str) -> bool:
        """Re-enable a service after an admin decides the budget issue is resolved."""
        APP_LOGGER.info(msg=f"Manual re-enable requested for: {api_name}")
        return self.apis.enable_api(api_name=api_name)

    def get_service_status(self, api_name: str) -> str | None:
        """Return the current API state (ENABLED / DISABLED)."""
        return self.apis.get_api_status(api_name=api_name)

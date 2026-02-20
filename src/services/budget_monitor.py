"""Core budget-monitoring orchestrator.

This module ties together:
  • Cloud Billing (pricing)  – via PriceProvider abstraction
  • Cloud Monitoring (usage)
  • Service API control (disable / enable)
  • Email notifications
  • Persistent state (baselines, alert tracking, audit)

It is called by the FastAPI ``/check`` endpoint on every scheduler tick.
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
    LAB_MODE,
    MONITORED_API_SERVICES,
    PRICE_SOURCE,
    PROJECT_ID,
    WARNING_THRESHOLD_PCT,
)
from services.notification import NotificationService
from services.price_provider import PriceProvider, create_price_provider
from services.state_manager import StateManager
from wrappers.cloud_apis import WrapperCloudAPIs
from wrappers.cloud_monitoring import WrapperCloudMonitoring


class BudgetMonitorService:
    """Runs a full budget-check cycle for every monitored service."""

    def __init__(
        self,
        price_provider: PriceProvider | None = None,
        state_manager: StateManager | None = None,
    ) -> None:
        self.state = state_manager or StateManager()
        self.price_provider = price_provider or create_price_provider()
        self.monitoring = WrapperCloudMonitoring()
        self.apis = WrapperCloudAPIs(project_id=PROJECT_ID)
        self.notifications = NotificationService(state_manager=self.state)

        # Clear baselines on month rollover (re-enable happens in run_check)
        self._pending_rollover = self.state.check_month_rollover()

        APP_LOGGER.info(msg="BudgetMonitorService initialised.")

    # ── public entry point ────────────────────────────────────────────────

    def run_check(self) -> dict[str, Any]:
        """Execute a full budget check cycle.  Returns a JSON-serialisable summary."""
        # ── Monthly rollover: clear baselines + re-enable disabled services
        rollover = self.state.check_month_rollover()
        if rollover or self._pending_rollover:
            self._pending_rollover = False
            re_enabled = self._re_enable_all_services()
            APP_LOGGER.info(
                msg=f"Monthly rollover: re-enabled services: {re_enabled}"
            )

        budget = ProjectBudget()
        disabled_apis: list[str] = []
        warnings_sent: list[str] = []
        metric_details: list[dict[str, Any]] = []
        data_warnings: list[str] = []

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
                if metric.is_catch_all:
                    cost, warns, details = self._compute_catch_all_expense(
                        metric, service_key
                    )
                    svc_budget.current_expense += cost
                    data_warnings.extend(warns)
                    metric_details.extend(details)
                else:
                    warning = self._compute_metric_expense(metric)
                    if warning:
                        data_warnings.append(warning)
                    svc_budget.current_expense += metric.expense
                    metric_details.append(metric.as_dict())

            # Save raw cumulative cost for reset-baseline tracking
            raw_cumulative_cost = svc_budget.current_expense
            self.state.set_last_known_cost(service_key, raw_cumulative_cost)

            # Subtract baseline (set during /reset) so the service is not
            # immediately re-disabled after an admin resets it.
            baseline = self.state.get_baseline(service_key)
            if baseline > 0:
                svc_budget.current_expense = max(0.0, raw_cumulative_cost - baseline)
                APP_LOGGER.info(
                    msg=(
                        f"  Baseline applied for {service_key}: "
                        f"${raw_cumulative_cost:.4f} - ${baseline:.4f} = "
                        f"${svc_budget.current_expense:.4f}"
                    )
                )

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
            "lab_mode": LAB_MODE,
            "pricing_provider": self.price_provider.provider_name,
            "budget": budget.as_dict(),
            "disabled_apis": disabled_apis,
            "warnings_sent": warnings_sent,
            "metric_details": metric_details,
            "data_warnings": data_warnings,
        }

        if data_warnings:
            APP_LOGGER.warning(
                msg=f"⚠ {len(data_warnings)} data quality warning(s) in this check cycle"
            )
            for dw in data_warnings:
                APP_LOGGER.warning(msg=f"  {dw}")

        APP_LOGGER.info(msg="=" * 72)
        APP_LOGGER.info(msg="Budget check cycle complete.")
        APP_LOGGER.info(msg=f"  Total project expense: ${budget.total_expense:.4f}")
        APP_LOGGER.info(msg=f"  APIs disabled this run: {disabled_apis}")
        APP_LOGGER.info(msg="=" * 72)

        return summary

    # ── helpers ────────────────────────────────────────────────────────────

    def _compute_metric_expense(self, metric: MonitoredMetric) -> str | None:
        """Fetch price and usage for a single metric, compute expense.

        Returns a warning string if a data quality issue was detected
        (e.g. pricing or monitoring API failure), otherwise ``None``.
        The expense calculation itself is unchanged — price failures
        still default to $0.00 (safe side: under-counting, not
        over-counting).
        """
        pricing_failed = False
        monitoring_failed = False

        try:
            price = self.price_provider.get_price_per_unit(
                service_id=metric.billing_service_id,
                sku_id=metric.billing_sku_id,
                price_tier=metric.billing_price_tier,
            )
            metric.price_per_unit = price
        except Exception as exc:
            APP_LOGGER.error(msg=f"Pricing error for {metric.label}: {exc}")
            metric.price_per_unit = None
            pricing_failed = True

        try:
            metric.unit_count = self.monitoring.get_total_units(
                metric_name=metric.metric_name,
                metric_filter=metric.metric_filter,
            )
        except Exception as exc:
            APP_LOGGER.error(msg=f"Monitoring error for {metric.label}: {exc}")
            metric.unit_count = 0
            monitoring_failed = True

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

        # ── Data quality warnings (visible in response + logs) ────────
        price_missing = pricing_failed or metric.price_per_unit is None
        if price_missing and monitoring_failed:
            return (
                f"⚠ {metric.label}: Both pricing and monitoring unavailable "
                f"— cost defaulted to $0.00"
            )
        if price_missing:
            return f"⚠ {metric.label}: Pricing unavailable — cost defaulted to $0.00"
        if monitoring_failed:
            return f"⚠ {metric.label}: Monitoring data unavailable — usage defaulted to 0"
        return None

    def _compute_catch_all_expense(
        self, metric: MonitoredMetric, service_key: str
    ) -> tuple[float, list[str], list[dict[str, Any]]]:
        """Process a catch-all metric by querying grouped usage.

        Returns ``(total_cost, warnings, detail_dicts)``.

        For each unique (model_user_id, type) group returned by Cloud
        Monitoring, model-specific pricing is applied.  Unknown models
        receive the default Vertex AI fallback price so that *no usage
        is ever ignored*.
        """
        warnings: list[str] = []
        details: list[dict[str, Any]] = []
        total_cost = 0.0

        try:
            grouped = self.monitoring.get_grouped_units(
                metric_name=metric.metric_name,
                metric_filter=metric.metric_filter,
                group_by_fields=metric.group_by_fields,
            )
        except Exception as exc:
            APP_LOGGER.error(
                msg=f"Monitoring error for catch-all {metric.label}: {exc}"
            )
            warnings.append(
                f"⚠ {metric.label}: Monitoring query failed — cost defaulted to $0.00"
            )
            return 0.0, warnings, details

        for group in grouped:
            labels = group.get("labels", {})
            model_id = labels.get("model_user_id", "unknown")
            token_type = labels.get("type", "input")
            units = group.get("units", 0)

            price: float | None = None
            pricing_source = "unknown"
            try:
                price = self.price_provider.get_vertex_ai_token_price(
                    model_id, token_type
                )
                pricing_source = "model_catalog"
            except Exception as exc:
                APP_LOGGER.error(
                    msg=f"Pricing error for {model_id}/{token_type}: {exc}"
                )

            if price is None:
                warnings.append(
                    f"⚠ {model_id}/{token_type}: No price available "
                    f"— cost defaulted to $0.00"
                )
                price = 0.0
                pricing_source = "none"

            expense = price * units
            total_cost += expense

            details.append(
                {
                    "label": f"{model_id} – {token_type} (catch-all)",
                    "metric_name": metric.metric_name,
                    "model_id": model_id,
                    "token_type": token_type,
                    "price_per_unit": price,
                    "unit_count": units,
                    "expense": round(expense, 6),
                    "pricing_source": pricing_source,
                    "is_catch_all": True,
                }
            )

            APP_LOGGER.debug(
                msg=(
                    f"  {model_id}/{token_type}: "
                    f"units={units}  price/token={price}  "
                    f"expense=${expense:.6f} ({pricing_source})"
                )
            )

        # Update the metric object for compatibility with summary logic
        metric.unit_count = sum(g.get("units", 0) for g in grouped)
        metric.expense = total_cost

        return total_cost, warnings, details

    def _re_enable_all_services(self) -> list[str]:
        """Re-enable all monitored service APIs (called on monthly rollover).

        Returns a list of API names that were successfully re-enabled.
        """
        re_enabled: list[str] = []
        for service_key, api_name in MONITORED_API_SERVICES.items():
            try:
                success = self.apis.enable_api(api_name=api_name)
                if success:
                    re_enabled.append(api_name)
                    APP_LOGGER.info(
                        msg=f"Monthly reset: re-enabled {api_name}"
                    )
            except Exception as exc:
                APP_LOGGER.error(
                    msg=f"Monthly reset: failed to re-enable {api_name}: {exc}"
                )
        if re_enabled:
            self.state.record_action(
                "monthly_reset_reenable",
                {"services_reenabled": re_enabled},
            )
        return re_enabled

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

    def reset_service(self, service_key: str) -> dict[str, Any]:
        """Full reset: save cost baseline + reset alerts + re-enable API.

        This is the proper way to recover a service after budget enforcement.
        The cost baseline ensures the next check cycle does not immediately
        re-disable the service (fixes the disable-loop problem).
        """
        api_name = MONITORED_API_SERVICES.get(service_key)
        if not api_name:
            return {
                "status": "error",
                "message": (
                    f"Unknown service key '{service_key}'. "
                    f"Valid keys: {list(MONITORED_API_SERVICES.keys())}"
                ),
            }

        # Determine the current cumulative cost to save as baseline.
        # Prefer the last value recorded during a check cycle (avoids
        # querying APIs again).  Fall back to a live query if needed.
        cumulative_cost = self.state.get_last_known_cost(service_key)
        if cumulative_cost is None:
            APP_LOGGER.info(
                msg=f"No cached cost for {service_key} — computing live"
            )
            cumulative_cost = self._get_current_cumulative_cost(service_key)
        if cumulative_cost is None:
            cumulative_cost = 0.0
            APP_LOGGER.warning(
                msg=f"No cost data available for {service_key} — baseline set to $0"
            )

        # Save baseline
        self.state.set_baseline(service_key, cumulative_cost)

        # Reset alert counters so new alerts can fire
        self.notifications.reset_alerts(service_key)

        # Re-enable the service API
        success = self.enable_service(api_name)

        # Audit trail
        self.state.record_action(
            "reset_service",
            {
                "service_key": service_key,
                "api_name": api_name,
                "baseline_saved": round(cumulative_cost, 4),
                "api_enabled": success,
            },
        )

        APP_LOGGER.info(
            msg=(
                f"Service {service_key} reset: "
                f"baseline=${cumulative_cost:.4f}, "
                f"API={'enabled' if success else 'FAILED TO ENABLE'}"
            )
        )

        return {
            "status": "success" if success else "partial",
            "service_key": service_key,
            "api_name": api_name,
            "api_enabled": success,
            "baseline_saved": round(cumulative_cost, 4),
            "alerts_reset": True,
        }

    def get_service_status(self, api_name: str) -> str | None:
        """Return the current API state (ENABLED / DISABLED)."""
        return self.apis.get_api_status(api_name=api_name)

    # ── private helpers ───────────────────────────────────────────────────

    def _get_current_cumulative_cost(self, service_key: str) -> float | None:
        """Query current month-to-date cost for a service (for baseline).

        Does NOT modify any MonitoredMetric objects.
        """
        metrics = SERVICE_METRICS.get(service_key, [])
        if not metrics:
            return None

        total = 0.0
        for metric in metrics:
            if metric.is_catch_all:
                # Use grouped query for catch-all metrics
                try:
                    grouped = self.monitoring.get_grouped_units(
                        metric_name=metric.metric_name,
                        metric_filter=metric.metric_filter,
                        group_by_fields=metric.group_by_fields,
                    )
                    for group in grouped:
                        labels = group.get("labels", {})
                        model_id = labels.get("model_user_id", "unknown")
                        token_type = labels.get("type", "input")
                        units = group.get("units", 0)
                        price = self.price_provider.get_vertex_ai_token_price(
                            model_id, token_type
                        )
                        if price is not None:
                            total += price * units
                except Exception:
                    pass
            else:
                try:
                    price = self.price_provider.get_price_per_unit(
                        service_id=metric.billing_service_id,
                        sku_id=metric.billing_sku_id,
                        price_tier=metric.billing_price_tier,
                    )
                except Exception:
                    price = None

                try:
                    units = self.monitoring.get_total_units(
                        metric_name=metric.metric_name,
                        metric_filter=metric.metric_filter,
                    )
                except Exception:
                    units = 0

                if price is not None:
                    total += price * units

        return total

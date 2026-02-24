"""Monitored service definition and SKU mapping for Cloud Billing API pricing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MonitoredMetric:
    """A single Cloud Monitoring metric that contributes to a service's cost."""

    # Human-readable label (e.g. "Gemini 2.5 Pro – input tokens")
    label: str

    # Cloud Monitoring metric type
    metric_name: str

    # Optional extra filter appended to the metric query
    metric_filter: str | None = None

    # Cloud Billing catalogue IDs for price lookup
    billing_service_id: str = ""
    billing_sku_id: str = ""
    billing_price_tier: int = 0

    # Catch-all monitoring: when True, usage is queried as a single
    # aggregated metric and then grouped by ``group_by_fields`` so that
    # per-model pricing can be applied at runtime.
    is_catch_all: bool = False
    group_by_fields: list[str] = field(default_factory=list)

    # Computed at runtime
    price_per_unit: float | None = None
    unit_count: int = 0
    expense: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.label,
            "metric_name": self.metric_name,
            "price_per_unit": self.price_per_unit,
            "unit_count": self.unit_count,
            "expense": round(self.expense, 6),
        }
        if self.is_catch_all:
            d["is_catch_all"] = True
        return d

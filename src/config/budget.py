"""Service-specific budget tracking and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helpers.constants import (
    APP_LOGGER,
    BIGQUERY_MONTHLY_BUDGET,
    FIRESTORE_MONTHLY_BUDGET,
    MONTHLY_BUDGET_AMOUNT,
    VERTEX_AI_MONTHLY_BUDGET,
)


@dataclass
class ServiceBudget:
    """Tracks budget vs. actual expense for a single service."""

    service_key: str  # e.g. "vertex_ai", "bigquery", "firestore"
    api_name: str  # e.g. "aiplatform.googleapis.com"
    monthly_budget: float = 0.0
    current_expense: float = 0.0

    @property
    def usage_pct(self) -> float:
        if self.monthly_budget <= 0:
            return 0.0
        return (self.current_expense / self.monthly_budget) * 100.0

    @property
    def is_exceeded(self) -> bool:
        return self.monthly_budget > 0 and self.current_expense >= self.monthly_budget

    def as_dict(self) -> dict[str, Any]:
        return {
            "service_key": self.service_key,
            "api_name": self.api_name,
            "monthly_budget": self.monthly_budget,
            "current_expense": round(self.current_expense, 4),
            "usage_pct": round(self.usage_pct, 2),
            "is_exceeded": self.is_exceeded,
        }


@dataclass
class ProjectBudget:
    """Aggregates per-service budgets and provides a project-level view."""

    monthly_limit: float = MONTHLY_BUDGET_AMOUNT
    services: dict[str, ServiceBudget] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Pre-populate the three monitored services
        if not self.services:
            self.services = {
                "vertex_ai": ServiceBudget(
                    service_key="vertex_ai",
                    api_name="aiplatform.googleapis.com",
                    monthly_budget=VERTEX_AI_MONTHLY_BUDGET,
                ),
                "bigquery": ServiceBudget(
                    service_key="bigquery",
                    api_name="bigquery.googleapis.com",
                    monthly_budget=BIGQUERY_MONTHLY_BUDGET,
                ),
                "firestore": ServiceBudget(
                    service_key="firestore",
                    api_name="firestore.googleapis.com",
                    monthly_budget=FIRESTORE_MONTHLY_BUDGET,
                ),
            }

    @property
    def total_expense(self) -> float:
        return sum(s.current_expense for s in self.services.values())

    @property
    def total_usage_pct(self) -> float:
        if self.monthly_limit <= 0:
            return 0.0
        return (self.total_expense / self.monthly_limit) * 100.0

    def check_overall_limit(self) -> bool:
        """Return True if the total project expense exceeds the overall limit."""
        exceeded = self.total_expense >= self.monthly_limit
        if exceeded:
            APP_LOGGER.warning(
                msg=(
                    f"Overall project budget exceeded: "
                    f"${self.total_expense:.2f} / ${self.monthly_limit:.2f}"
                )
            )
        return exceeded

    def get_exceeded_services(self) -> list[ServiceBudget]:
        """Return list of services whose expense has exceeded their budget."""
        return [s for s in self.services.values() if s.is_exceeded]

    def as_dict(self) -> dict[str, Any]:
        return {
            "monthly_limit": self.monthly_limit,
            "total_expense": round(self.total_expense, 4),
            "total_usage_pct": round(self.total_usage_pct, 2),
            "services": {k: v.as_dict() for k, v in self.services.items()},
        }

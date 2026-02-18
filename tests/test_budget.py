"""Unit tests for config.budget module."""

import pytest
from config.budget import ProjectBudget, ServiceBudget


class TestServiceBudget:
    """Tests for the ServiceBudget dataclass."""

    def test_usage_pct_zero_budget(self):
        """Zero budget should return 0 % usage (no division by zero)."""
        sb = ServiceBudget(
            service_key="test", api_name="test.googleapis.com",
            monthly_budget=0.0, current_expense=50.0,
        )
        assert sb.usage_pct == 0.0

    def test_usage_pct_normal(self):
        sb = ServiceBudget(
            service_key="test", api_name="test.googleapis.com",
            monthly_budget=100.0, current_expense=80.0,
        )
        assert sb.usage_pct == pytest.approx(80.0)

    def test_is_exceeded_true(self):
        sb = ServiceBudget(
            service_key="test", api_name="test.googleapis.com",
            monthly_budget=100.0, current_expense=100.0,
        )
        assert sb.is_exceeded is True

    def test_is_exceeded_false(self):
        sb = ServiceBudget(
            service_key="test", api_name="test.googleapis.com",
            monthly_budget=100.0, current_expense=99.99,
        )
        assert sb.is_exceeded is False

    def test_as_dict_keys(self):
        sb = ServiceBudget(
            service_key="vertex_ai", api_name="aiplatform.googleapis.com",
            monthly_budget=100.0, current_expense=50.0,
        )
        d = sb.as_dict()
        assert set(d.keys()) == {
            "service_key", "api_name", "monthly_budget",
            "current_expense", "usage_pct", "is_exceeded",
        }


class TestProjectBudget:
    """Tests for the ProjectBudget dataclass."""

    def test_default_services_created(self):
        pb = ProjectBudget()
        assert "vertex_ai" in pb.services
        assert "bigquery" in pb.services
        assert "firestore" in pb.services

    def test_total_expense(self):
        pb = ProjectBudget()
        pb.services["vertex_ai"].current_expense = 10.0
        pb.services["bigquery"].current_expense = 20.0
        pb.services["firestore"].current_expense = 30.0
        assert pb.total_expense == pytest.approx(60.0)

    def test_get_exceeded_services(self):
        pb = ProjectBudget()
        pb.services["vertex_ai"].current_expense = 200.0  # exceeds 100 budget
        pb.services["bigquery"].current_expense = 1.0
        exceeded = pb.get_exceeded_services()
        assert len(exceeded) == 1
        assert exceeded[0].service_key == "vertex_ai"

    def test_check_overall_limit_not_exceeded(self):
        pb = ProjectBudget()
        pb.services["vertex_ai"].current_expense = 1.0
        assert pb.check_overall_limit() is False

    def test_check_overall_limit_exceeded(self):
        pb = ProjectBudget(monthly_limit=10.0)
        pb.services["vertex_ai"].current_expense = 11.0
        assert pb.check_overall_limit() is True

    def test_as_dict_structure(self):
        pb = ProjectBudget()
        d = pb.as_dict()
        assert "monthly_limit" in d
        assert "total_expense" in d
        assert "services" in d
        assert "vertex_ai" in d["services"]

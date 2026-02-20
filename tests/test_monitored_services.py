"""Unit tests for config.monitored_services and config.monitored_services_list."""

from config.monitored_services import MonitoredMetric
from config.monitored_services_list import (
    BIGQUERY_METRICS,
    FIRESTORE_METRICS,
    SERVICE_METRICS,
    VERTEX_AI_METRICS,
)


class TestMonitoredMetric:
    def test_as_dict(self):
        m = MonitoredMetric(label="test", metric_name="test.metric")
        d = m.as_dict()
        assert d["label"] == "test"
        assert d["expense"] == 0.0

    def test_default_values(self):
        m = MonitoredMetric(label="x", metric_name="y")
        assert m.price_per_unit is None
        assert m.unit_count == 0
        assert m.expense == 0.0
        assert m.is_catch_all is False
        assert m.group_by_fields == []

    def test_catch_all_flag_in_as_dict(self):
        m = MonitoredMetric(label="ca", metric_name="m", is_catch_all=True)
        d = m.as_dict()
        assert d["is_catch_all"] is True

    def test_non_catch_all_omits_flag(self):
        m = MonitoredMetric(label="x", metric_name="y")
        d = m.as_dict()
        assert "is_catch_all" not in d


class TestServiceMetricsRegistry:
    def test_all_service_keys_present(self):
        assert "vertex_ai" in SERVICE_METRICS
        assert "bigquery" in SERVICE_METRICS
        assert "firestore" in SERVICE_METRICS

    def test_vertex_ai_has_metrics(self):
        assert len(VERTEX_AI_METRICS) >= 1

    def test_bigquery_has_metrics(self):
        assert len(BIGQUERY_METRICS) >= 1

    def test_firestore_has_metrics(self):
        assert len(FIRESTORE_METRICS) >= 4  # read, write, delete, ttl_delete

    def test_non_catch_all_metrics_have_billing_ids(self):
        """Every non-catch-all metric must have billing service + SKU IDs."""
        for key, metrics in SERVICE_METRICS.items():
            for m in metrics:
                if m.is_catch_all:
                    continue
                assert m.billing_service_id, f"{m.label} missing billing_service_id"
                assert m.billing_sku_id, f"{m.label} missing billing_sku_id"

    def test_vertex_ai_has_catch_all_metric(self):
        """Vertex AI should have at least one catch-all metric."""
        catch_all = [m for m in VERTEX_AI_METRICS if m.is_catch_all]
        assert len(catch_all) >= 1
        m = catch_all[0]
        assert "resource.label.model_user_id" in m.group_by_fields
        assert "metric.label.type" in m.group_by_fields

    def test_catch_all_has_service_id(self):
        """Catch-all metric should still have a billing_service_id."""
        for m in VERTEX_AI_METRICS:
            if m.is_catch_all:
                assert m.billing_service_id == "C7E2-9256-1C43"

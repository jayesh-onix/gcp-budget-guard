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


class TestServiceMetricsRegistry:
    def test_all_service_keys_present(self):
        assert "vertex_ai" in SERVICE_METRICS
        assert "bigquery" in SERVICE_METRICS
        assert "firestore" in SERVICE_METRICS

    def test_vertex_ai_has_metrics(self):
        assert len(VERTEX_AI_METRICS) >= 2  # at least input+output for one model

    def test_bigquery_has_metrics(self):
        assert len(BIGQUERY_METRICS) >= 1

    def test_firestore_has_metrics(self):
        assert len(FIRESTORE_METRICS) >= 4  # read, write, delete, ttl_delete

    def test_all_metrics_have_billing_ids(self):
        for key, metrics in SERVICE_METRICS.items():
            for m in metrics:
                assert m.billing_service_id, f"{m.label} missing billing_service_id"
                assert m.billing_sku_id, f"{m.label} missing billing_sku_id"

    def test_vertex_ai_filters(self):
        """Every Vertex AI metric should have a metric_filter for model selection."""
        for m in VERTEX_AI_METRICS:
            assert m.metric_filter is not None, f"{m.label} missing metric_filter"
            assert "model_user_id" in m.metric_filter

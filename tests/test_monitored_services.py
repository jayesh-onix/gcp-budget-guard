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


class TestVertexAISubServiceMetrics:
    """Tests for the 7 non-catch-all Vertex AI sub-service metrics."""

    EXPECTED_VERTEX_AI_SUB_SKUS = [
        "VAIP-ENDPOINT-N1S4",
        "VAIP-BATCH-PRED-ITEMS",
        "VAIP-TRAINING-N1S8",
        "VAIP-PIPELINE-STEP",
        "VAIP-FEATURESTORE-READ",
        "VAIP-VECTOR-SEARCH-QUERY",
        "VAIP-MODEL-MONITORING-PRED",
    ]

    def test_vertex_ai_has_8_metrics(self):
        """Vertex AI should have 8 metrics: 1 catch-all + 7 sub-services."""
        assert len(VERTEX_AI_METRICS) == 8

    def test_vertex_ai_has_exactly_one_catch_all(self):
        catch_all = [m for m in VERTEX_AI_METRICS if m.is_catch_all]
        assert len(catch_all) == 1

    def test_all_sub_service_skus_present(self):
        """Each expected sub-service SKU should be in VERTEX_AI_METRICS."""
        non_catch_all = [m for m in VERTEX_AI_METRICS if not m.is_catch_all]
        sku_ids = {m.billing_sku_id for m in non_catch_all}
        for expected_sku in self.EXPECTED_VERTEX_AI_SUB_SKUS:
            assert expected_sku in sku_ids, f"Missing SKU in VERTEX_AI_METRICS: {expected_sku}"

    def test_sub_services_not_catch_all(self):
        """All 7 sub-service metrics should NOT be catch-all."""
        non_catch_all = [m for m in VERTEX_AI_METRICS if not m.is_catch_all]
        assert len(non_catch_all) == 7
        for m in non_catch_all:
            assert m.is_catch_all is False
            assert m.group_by_fields == []

    def test_sub_services_have_billing_ids(self):
        """Every sub-service metric must have billing_service_id and billing_sku_id."""
        for m in VERTEX_AI_METRICS:
            if m.is_catch_all:
                continue
            assert m.billing_service_id == "C7E2-9256-1C43", f"{m.label} wrong service_id"
            assert m.billing_sku_id, f"{m.label} missing billing_sku_id"

    def test_sub_services_have_aiplatform_metric_name(self):
        """All Vertex AI metric names should start with aiplatform.googleapis.com/."""
        for m in VERTEX_AI_METRICS:
            assert m.metric_name.startswith("aiplatform.googleapis.com/"), (
                f"{m.label}: metric_name '{m.metric_name}' does not start with "
                f"'aiplatform.googleapis.com/'"
            )

    def test_sub_services_have_resource_type_filter(self):
        """All non-catch-all metrics should have a resource.type filter."""
        for m in VERTEX_AI_METRICS:
            if m.is_catch_all:
                continue
            assert "resource.type" in (m.metric_filter or ""), (
                f"{m.label}: metric_filter should contain resource.type"
            )

    def test_endpoint_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-ENDPOINT-N1S4"][0]
        assert "Endpoint" in m.metric_filter
        assert "prediction" in m.metric_name or "accelerator" in m.metric_name

    def test_batch_prediction_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-BATCH-PRED-ITEMS"][0]
        assert "BatchPrediction" in m.metric_filter
        assert "batch" in m.metric_name or "prediction" in m.metric_name

    def test_training_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-TRAINING-N1S8"][0]
        assert "CustomJob" in m.metric_filter
        assert "training" in m.metric_name

    def test_pipeline_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-PIPELINE-STEP"][0]
        assert "PipelineJob" in m.metric_filter
        assert "pipeline" in m.metric_name

    def test_featurestore_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-FEATURESTORE-READ"][0]
        assert "Featurestore" in m.metric_filter
        assert "featurestore" in m.metric_name

    def test_vector_search_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-VECTOR-SEARCH-QUERY"][0]
        assert "IndexEndpoint" in m.metric_filter
        assert "matching_engine" in m.metric_name

    def test_model_monitoring_metric(self):
        m = [m for m in VERTEX_AI_METRICS if m.billing_sku_id == "VAIP-MODEL-MONITORING-PRED"][0]
        assert "ModelDeploymentMonitoring" in m.metric_filter
        assert "model_monitoring" in m.metric_name

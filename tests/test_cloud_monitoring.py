"""Unit tests for wrappers.cloud_monitoring."""

from unittest.mock import MagicMock, patch

from wrappers.cloud_monitoring import WrapperCloudMonitoring


class TestWrapperCloudMonitoring:
    """Tests for the Cloud Monitoring wrapper."""

    def _make_wrapper(self) -> WrapperCloudMonitoring:
        with patch("wrappers.cloud_monitoring.monitoring_v3") as mock_mv3:
            mock_mv3.MetricServiceClient.return_value = MagicMock()
            wrapper = WrapperCloudMonitoring()
            return wrapper

    def test_get_total_units_returns_zero_on_no_data(self):
        wrapper = self._make_wrapper()
        # Make the query return None
        with patch.object(wrapper, "_query_time_series", return_value=None):
            result = wrapper.get_total_units("test.metric")
            assert result == 0

    def test_get_total_units_sums_points(self):
        wrapper = self._make_wrapper()

        # Create fake time-series data
        mock_point1 = MagicMock()
        mock_point1.value.int64_value = 100
        mock_point2 = MagicMock()
        mock_point2.value.int64_value = 200

        mock_ts = MagicMock()
        mock_ts.points = [mock_point1, mock_point2]

        with patch.object(wrapper, "_query_time_series", return_value=[mock_ts]):
            result = wrapper.get_total_units("test.metric")
            assert result == 300

    # ── Grouped units tests ───────────────────────────────────────────

    def test_get_grouped_units_returns_empty_on_no_data(self):
        wrapper = self._make_wrapper()
        with patch.object(wrapper, "_query_time_series", return_value=None):
            result = wrapper.get_grouped_units(
                "test.metric", group_by_fields=["resource.label.model_user_id"]
            )
            assert result == []

    def test_get_grouped_units_extracts_labels(self):
        """Grouped query should extract label values from each time series."""
        wrapper = self._make_wrapper()

        mock_point = MagicMock()
        mock_point.value.int64_value = 500

        mock_ts = MagicMock()
        mock_ts.points = [mock_point]
        mock_ts.resource.labels = {"model_user_id": "gemini-2.5-pro"}
        mock_ts.metric.labels = {"type": "input"}

        group_by = ["resource.label.model_user_id", "metric.label.type"]
        with patch.object(wrapper, "_query_time_series", return_value=[mock_ts]):
            result = wrapper.get_grouped_units(
                "test.metric", group_by_fields=group_by
            )

        assert len(result) == 1
        assert result[0]["labels"]["model_user_id"] == "gemini-2.5-pro"
        assert result[0]["labels"]["type"] == "input"
        assert result[0]["units"] == 500

    def test_get_grouped_units_multiple_groups(self):
        """Multiple time series should produce multiple group entries."""
        wrapper = self._make_wrapper()

        def make_ts(model, token_type, units):
            pt = MagicMock()
            pt.value.int64_value = units
            ts = MagicMock()
            ts.points = [pt]
            ts.resource.labels = {"model_user_id": model}
            ts.metric.labels = {"type": token_type}
            return ts

        series = [
            make_ts("gemini-2.5-pro", "input", 1000),
            make_ts("gemini-2.5-pro", "output", 400),
            make_ts("claude-3-opus", "input", 200),
        ]

        group_by = ["resource.label.model_user_id", "metric.label.type"]
        with patch.object(wrapper, "_query_time_series", return_value=series):
            result = wrapper.get_grouped_units(
                "test.metric", group_by_fields=group_by
            )

        assert len(result) == 3
        models = {r["labels"]["model_user_id"] for r in result}
        assert "gemini-2.5-pro" in models
        assert "claude-3-opus" in models

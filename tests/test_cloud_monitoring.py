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

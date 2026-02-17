"""Unit tests for wrappers.cloud_apis (disable / enable / status)."""

from unittest.mock import MagicMock, patch

import pytest

from wrappers.cloud_apis import WrapperCloudAPIs


class TestWrapperCloudAPIs:
    """Tests for the Cloud APIs wrapper."""

    def _make_wrapper(self) -> WrapperCloudAPIs:
        with patch("wrappers.cloud_apis.discovery") as mock_disc:
            mock_disc.build.return_value = MagicMock()
            return WrapperCloudAPIs(project_id="test-project")

    @patch("wrappers.cloud_apis.DRY_RUN_MODE", True)
    def test_disable_api_dry_run(self):
        wrapper = self._make_wrapper()
        result = wrapper.disable_api("firestore.googleapis.com")
        assert result is True  # dry-run always returns True

    @patch("wrappers.cloud_apis.DRY_RUN_MODE", False)
    def test_disable_api_success(self):
        wrapper = self._make_wrapper()
        mock_disable = MagicMock()
        mock_disable.execute.return_value = {"done": True}
        wrapper.service_usage_client.services.return_value.disable.return_value = mock_disable

        result = wrapper.disable_api("firestore.googleapis.com")
        assert result is True

    @patch("wrappers.cloud_apis.DRY_RUN_MODE", True)
    def test_enable_api_dry_run(self):
        wrapper = self._make_wrapper()
        result = wrapper.enable_api("firestore.googleapis.com")
        assert result is True

    @patch("wrappers.cloud_apis.DRY_RUN_MODE", False)
    def test_enable_api_success(self):
        wrapper = self._make_wrapper()
        mock_enable = MagicMock()
        mock_enable.execute.return_value = {"done": True}
        wrapper.service_usage_client.services.return_value.enable.return_value = mock_enable

        result = wrapper.enable_api("firestore.googleapis.com")
        assert result is True

    def test_get_api_status(self):
        wrapper = self._make_wrapper()
        mock_get = MagicMock()
        mock_get.execute.return_value = {"state": "ENABLED"}
        wrapper.service_usage_client.services.return_value.get.return_value = mock_get

        state = wrapper.get_api_status("firestore.googleapis.com")
        assert state == "ENABLED"

    def test_get_api_status_error(self):
        wrapper = self._make_wrapper()
        wrapper.service_usage_client.services.return_value.get.side_effect = Exception("fail")

        state = wrapper.get_api_status("firestore.googleapis.com")
        assert state is None

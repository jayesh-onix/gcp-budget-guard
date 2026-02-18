"""Unit tests for wrappers.cloud_billing (SKU price lookups)."""

from unittest.mock import MagicMock, patch

from wrappers.cloud_billing import CloudBillingWrapper


class TestCloudBillingWrapper:
    """Tests for the Cloud Billing wrapper."""

    def _make_wrapper(self) -> CloudBillingWrapper:
        with patch("wrappers.cloud_billing.CloudCatalogClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            wrapper = CloudBillingWrapper()
            wrapper.client = mock_client
            return wrapper

    def test_sku_cache_populated_once(self):
        """SKUs for a service should only be fetched once."""
        wrapper = self._make_wrapper()

        # Create a fake SKU
        fake_sku = MagicMock()
        fake_sku.sku_id = "TEST-SKU-1"
        fake_sku.pricing_info = []
        wrapper.client.list_skus.return_value = [fake_sku]

        # Ensure cache is populated
        wrapper._ensure_skus_loaded("SVC-1")
        wrapper._ensure_skus_loaded("SVC-1")  # second call should not re-fetch

        assert wrapper.client.list_skus.call_count == 1
        assert "TEST-SKU-1" in wrapper._sku_cache["SVC-1"]

    def test_extract_price_missing_sku(self):
        """Missing SKU should return None."""
        wrapper = self._make_wrapper()
        wrapper._sku_cache["SVC-1"] = {}
        result = wrapper._extract_price("SVC-1", "MISSING", 0)
        assert result is None

    def test_extract_price_with_tiered_rate(self):
        """Should compute price per base unit correctly."""
        wrapper = self._make_wrapper()

        # Build mock SKU with pricing
        mock_sku = MagicMock()
        mock_tier = MagicMock()
        mock_tier.unit_price.nanos = 500_000_000  # 0.50
        mock_tier.unit_price.units = 0

        mock_expr = MagicMock()
        mock_expr.tiered_rates = [mock_tier]
        mock_expr.base_unit_conversion_factor = 1_000_000  # e.g. tokens
        mock_expr.usage_unit_description = "1M tokens"
        mock_expr.base_unit_description = "token"

        mock_pricing = MagicMock()
        mock_pricing.pricing_expression = mock_expr

        mock_sku.pricing_info = [mock_pricing]
        mock_sku.sku_id = "SKU-A"

        wrapper._sku_cache["SVC-1"] = {"SKU-A": mock_sku}

        price = wrapper._extract_price("SVC-1", "SKU-A", 0)
        assert price is not None
        # 0.50 / 1_000_000 = 5e-7
        assert abs(price - 5e-7) < 1e-12

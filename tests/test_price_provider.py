"""Unit tests for the pricing provider abstraction layer."""

from unittest.mock import MagicMock, patch

import pytest

from services.price_provider import (
    CloudBillingPriceProvider,
    FallbackPriceProvider,
    PriceProvider,
    StaticPriceProvider,
    create_price_provider,
)


class TestStaticPriceProvider:
    """Tests for StaticPriceProvider."""

    def test_provider_name(self):
        provider = StaticPriceProvider()
        assert provider.provider_name == "static_catalog"

    def test_get_price_per_unit_known_sku(self):
        provider = StaticPriceProvider()
        # Gemini 2.5 Pro input: A121-E2B5-1418
        price = provider.get_price_per_unit(
            service_id="C7E2-9256-1C43",
            sku_id="A121-E2B5-1418",
        )
        assert price is not None
        assert price > 0

    def test_get_price_per_unit_unknown_sku_returns_fallback(self):
        provider = StaticPriceProvider()
        price = provider.get_price_per_unit(
            service_id="UNKNOWN",
            sku_id="UNKNOWN-SKU",
        )
        # Should return fallback price, not None
        assert price is not None
        assert price > 0

    def test_as_dict(self):
        provider = StaticPriceProvider()
        d = provider.as_dict()
        assert d["provider"] == "static_catalog"
        assert "catalog" in d


class TestCloudBillingPriceProvider:
    """Tests for CloudBillingPriceProvider."""

    @patch("services.price_provider.CloudBillingPriceProvider.__init__", return_value=None)
    def test_provider_name(self, mock_init):
        provider = CloudBillingPriceProvider.__new__(CloudBillingPriceProvider)
        assert provider.provider_name == "cloud_billing"

    @patch("services.price_provider.CloudBillingPriceProvider.__init__", return_value=None)
    def test_as_dict(self, mock_init):
        provider = CloudBillingPriceProvider.__new__(CloudBillingPriceProvider)
        d = provider.as_dict()
        assert d["provider"] == "cloud_billing"
        assert "source" in d


class TestFallbackPriceProvider:
    """Tests for FallbackPriceProvider."""

    def test_uses_primary_when_available(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "primary"
        primary.get_price_per_unit.return_value = 0.001

        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "fallback"

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        price = provider.get_price_per_unit("svc", "sku")

        assert price == 0.001
        fallback.get_price_per_unit.assert_not_called()

    def test_falls_back_when_primary_returns_none(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "primary"
        primary.get_price_per_unit.return_value = None

        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "fallback"
        fallback.get_price_per_unit.return_value = 0.002

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        price = provider.get_price_per_unit("svc", "sku")

        assert price == 0.002
        assert provider._fallback_count == 1

    def test_falls_back_when_primary_raises(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "primary"
        primary.get_price_per_unit.side_effect = Exception("billing API down")

        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "fallback"
        fallback.get_price_per_unit.return_value = 0.003

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        price = provider.get_price_per_unit("svc", "sku")

        assert price == 0.003

    def test_returns_none_when_both_fail(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "primary"
        primary.get_price_per_unit.side_effect = Exception("down")

        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "fallback"
        fallback.get_price_per_unit.side_effect = Exception("also down")

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        price = provider.get_price_per_unit("svc", "sku")

        assert price is None

    def test_provider_name_format(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "cloud_billing"
        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "static_catalog"

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        assert "cloud_billing" in provider.provider_name
        assert "static_catalog" in provider.provider_name

    def test_as_dict_includes_fallback_count(self):
        primary = MagicMock(spec=PriceProvider)
        primary.provider_name = "primary"
        primary.as_dict.return_value = {"provider": "primary"}
        primary.get_price_per_unit.return_value = None

        fallback = MagicMock(spec=PriceProvider)
        fallback.provider_name = "fallback"
        fallback.as_dict.return_value = {"provider": "fallback"}
        fallback.get_price_per_unit.return_value = 0.001

        provider = FallbackPriceProvider(primary=primary, fallback=fallback)
        provider.get_price_per_unit("svc", "sku")

        d = provider.as_dict()
        assert d["fallback_invocations"] == 1


class TestCreatePriceProvider:
    """Tests for the factory function."""

    @patch("helpers.constants.LAB_MODE", True)
    @patch("helpers.constants.PRICE_SOURCE", "billing")
    def test_lab_mode_returns_static(self):
        provider = create_price_provider()
        assert isinstance(provider, StaticPriceProvider)

    @patch("helpers.constants.LAB_MODE", False)
    @patch("helpers.constants.PRICE_SOURCE", "static")
    def test_static_source_returns_static(self):
        provider = create_price_provider()
        assert isinstance(provider, StaticPriceProvider)

    @patch("helpers.constants.LAB_MODE", False)
    @patch("helpers.constants.PRICE_SOURCE", "billing")
    @patch("services.price_provider.CloudBillingPriceProvider")
    def test_billing_source_returns_fallback(self, mock_billing_cls):
        mock_billing = MagicMock()
        mock_billing.provider_name = "cloud_billing"
        mock_billing_cls.return_value = mock_billing

        provider = create_price_provider()
        assert isinstance(provider, FallbackPriceProvider)

    @patch("helpers.constants.LAB_MODE", False)
    @patch("helpers.constants.PRICE_SOURCE", "billing")
    @patch("services.price_provider.CloudBillingPriceProvider")
    def test_billing_init_failure_falls_back_to_static(self, mock_billing_cls):
        mock_billing_cls.side_effect = Exception("billing API unavailable")

        provider = create_price_provider()
        assert isinstance(provider, StaticPriceProvider)

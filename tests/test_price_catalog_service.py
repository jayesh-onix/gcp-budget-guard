"""Unit tests for the static pricing catalog service."""

import json
import os
import tempfile

import pytest

from services.price_catalog_service import PriceCatalogService


class TestPriceCatalogService:
    """Tests for PriceCatalogService."""

    def _make_catalog(self, data: dict | None = None) -> PriceCatalogService:
        """Create a PriceCatalogService with a temporary catalog file."""
        if data is None:
            # Use the real catalog
            return PriceCatalogService()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            path = f.name

        try:
            return PriceCatalogService(catalog_path=path)
        finally:
            # Cleanup handled by test framework; service already loaded
            pass

    def test_loads_real_catalog(self):
        """Should successfully load the real pricing_catalog.json."""
        catalog = PriceCatalogService()
        assert catalog.version == "2026-02"
        assert catalog.region == "us-central1"
        assert catalog.currency == "USD"

    def test_sku_index_populated(self):
        """SKU index should contain all billing_sku_id entries."""
        catalog = PriceCatalogService()
        summary = catalog.as_dict()
        assert summary["indexed_sku_count"] > 0
        assert "vertex_ai" in summary["services"]
        assert "bigquery" in summary["services"]
        assert "firestore" in summary["services"]

    def test_get_price_per_base_unit_vertex_ai(self):
        """Should return correct normalised price for a Vertex AI SKU."""
        catalog = PriceCatalogService()
        # Gemini 2.5 Pro input: $1.25 per 1M tokens → 1.25e-6 per token
        price = catalog.get_price_per_base_unit(
            service_key="vertex_ai",
            sku_id="A121-E2B5-1418",
        )
        assert price is not None
        assert abs(price - 1.25e-6) < 1e-10

    def test_get_price_per_base_unit_bigquery(self):
        """Should return correct normalised price for BigQuery."""
        catalog = PriceCatalogService()
        price = catalog.get_price_per_base_unit(
            service_key="bigquery",
            sku_id="3362-E469-6BEF",
        )
        assert price is not None
        # $6.25 / 1099511627776 bytes
        expected = 6.25 / 1099511627776
        assert abs(price - expected) < 1e-18

    def test_get_price_per_base_unit_firestore(self):
        """Should return correct normalised price for Firestore reads."""
        catalog = PriceCatalogService()
        price = catalog.get_price_per_base_unit(
            service_key="firestore",
            sku_id="6A94-8525-876F",
        )
        assert price is not None
        # $0.06 / 100000 = 6e-7
        assert abs(price - 6e-7) < 1e-12

    def test_unknown_sku_returns_fallback(self):
        """Unknown SKU should return the default fallback price."""
        catalog = PriceCatalogService()
        price = catalog.get_price_per_base_unit(
            service_key="vertex_ai",
            sku_id="UNKNOWN-SKU-123",
            use_fallback=True,
        )
        assert price == catalog.default_fallback_price

    def test_unknown_sku_returns_none_when_no_fallback(self):
        """Unknown SKU should return None when fallback disabled."""
        catalog = PriceCatalogService()
        price = catalog.get_price_per_base_unit(
            service_key="vertex_ai",
            sku_id="UNKNOWN-SKU-123",
            use_fallback=False,
        )
        assert price is None

    def test_get_free_tier(self):
        """Should return free tier configuration."""
        catalog = PriceCatalogService()
        free_tier = catalog.get_free_tier("bigquery")
        assert "analysis_bytes_per_month" in free_tier

    def test_validate_region_match(self):
        catalog = PriceCatalogService()
        assert catalog.validate_region("us-central1") is True

    def test_validate_region_mismatch(self):
        catalog = PriceCatalogService()
        assert catalog.validate_region("europe-west1") is False

    def test_missing_catalog_file(self):
        """Should handle missing catalog file gracefully."""
        catalog = PriceCatalogService(catalog_path="/nonexistent/path.json")
        assert catalog.version == "unknown"
        # Should still return fallback price
        price = catalog.get_price_per_base_unit(
            service_key="test", sku_id="FAKE", use_fallback=True
        )
        assert price == 0.0001  # default fallback

    def test_invalid_json_catalog(self):
        """Should handle invalid JSON gracefully."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("{ invalid json }")
            path = f.name

        catalog = PriceCatalogService(catalog_path=path)
        assert catalog.version == "unknown"
        os.unlink(path)

    def test_partial_catalog(self):
        """Should work with a partial catalog (missing some services)."""
        partial_data = {
            "version": "test",
            "region": "us-central1",
            "currency": "USD",
            "vertex_ai": {},
            "bigquery": {},
            "firestore": {},
            "default_fallback_price": 0.001,
        }
        catalog = self._make_catalog(partial_data)
        assert catalog.version == "test"

    def test_as_dict(self):
        """Should return a serialisable summary."""
        catalog = PriceCatalogService()
        d = catalog.as_dict()
        assert "version" in d
        assert "region" in d
        assert "currency" in d
        assert "indexed_sku_count" in d
        assert "services" in d

"""Static pricing catalog service.

Loads pricing data from a JSON catalog file and provides price lookups
by service, metric, and SKU ID.  Used as a drop-in replacement for the
Cloud Billing Catalog API in lab environments or as an automatic
fallback when the billing API is unavailable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from helpers.constants import APP_LOGGER

# Default catalog path: config/pricing_catalog.json relative to this file
_DEFAULT_CATALOG_PATH = str(
    Path(__file__).resolve().parent.parent / "config" / "pricing_catalog.json"
)

# Required top-level keys for schema validation
_REQUIRED_KEYS = {"version", "region", "currency", "vertex_ai", "bigquery", "firestore"}


class PriceCatalogService:
    """Load and query the static pricing catalog.

    The catalog is a JSON file containing per-service, per-metric
    pricing structures that mirror Cloud Billing SKU pricing.

    Usage::

        catalog = PriceCatalogService()
        price = catalog.get_price_per_base_unit(
            service_key="vertex_ai",
            sku_id="A121-E2B5-1418",
        )
    """

    def __init__(self, catalog_path: str | None = None) -> None:
        self._catalog_path = catalog_path or os.environ.get(
            "PRICING_CATALOG_PATH", _DEFAULT_CATALOG_PATH
        )
        self._data: dict[str, Any] = {}
        self._sku_index: dict[str, dict[str, Any]] = {}  # sku_id → pricing entry
        self._load_catalog()

    # ── public API ────────────────────────────────────────────────────────

    @property
    def version(self) -> str:
        """Catalog version string (e.g. '2026-02')."""
        return self._data.get("version", "unknown")

    @property
    def region(self) -> str:
        """Region the catalog prices apply to."""
        return self._data.get("region", "us-central1")

    @property
    def currency(self) -> str:
        """Currency code (e.g. 'USD')."""
        return self._data.get("currency", "USD")

    @property
    def default_fallback_price(self) -> float:
        """Fallback price when a specific SKU is not found."""
        return float(self._data.get("default_fallback_price", 0.0001))

    def get_price_per_base_unit(
        self,
        service_key: str,
        sku_id: str,
        *,
        use_fallback: bool = True,
    ) -> float | None:
        """Return the price per base unit for a given SKU.

        Pricing is normalised to the base unit (e.g. per token, per byte,
        per single operation) so the value can be multiplied directly by
        the raw metric count from Cloud Monitoring.

        Args:
            service_key: Service identifier (vertex_ai, bigquery, firestore).
            sku_id: Cloud Billing SKU ID.
            use_fallback: If True, return the default fallback price
                when the SKU is not found.  If False, return None.

        Returns:
            Price per base unit, or None if SKU not found and
            use_fallback is False.
        """
        entry = self._sku_index.get(sku_id)

        if entry is not None:
            price_per_unit = float(entry.get("price_per_unit", 0))
            unit_size = int(entry.get("unit_size", 1))
            price_per_base = price_per_unit / unit_size if unit_size > 0 else 0.0

            APP_LOGGER.debug(
                msg=(
                    f"Static price for {service_key}/{sku_id}: "
                    f"{price_per_unit}/{unit_size} = {price_per_base:.12f} per base unit"
                )
            )
            return price_per_base

        APP_LOGGER.warning(
            msg=f"SKU {sku_id} not found in static catalog for service {service_key}"
        )

        if use_fallback:
            APP_LOGGER.info(
                msg=f"Using default fallback price: {self.default_fallback_price}"
            )
            return self.default_fallback_price

        return None

    def get_vertex_ai_model_price(
        self, model_id: str, token_type: str
    ) -> float | None:
        """Return the price per base token for a Vertex AI model.

        Resolution order:

        1. Exact model name match in ``vertex_ai`` section.
        2. Normalised match (strip ``@version`` suffix and publisher prefix).
        3. Default Vertex AI token price from ``vertex_ai_defaults``.
        4. Global ``default_fallback_price``.

        Args:
            model_id: The ``model_user_id`` label from Cloud Monitoring.
            token_type: ``"input"`` or ``"output"``.

        Returns:
            Price per single token, or the default fallback price.
        """
        vertex_ai = self._data.get("vertex_ai", {})

        # 1. Exact match
        price = self._extract_model_token_price(vertex_ai, model_id, token_type)
        if price is not None:
            return price

        # 2. Normalised match
        normalised = self._normalize_model_id(model_id)
        if normalised != model_id:
            price = self._extract_model_token_price(vertex_ai, normalised, token_type)
            if price is not None:
                return price

        # 3. Default vertex_ai pricing
        defaults = self._data.get("vertex_ai_defaults", {})
        default_key = f"default_{token_type}_token_price"
        default_price = defaults.get(default_key)
        if default_price is not None:
            unit_size = defaults.get("default_token_unit_size", 1_000_000)
            per_base = float(default_price) / unit_size if unit_size > 0 else 0.0
            APP_LOGGER.info(
                msg=(
                    f"Using default Vertex AI {token_type} price for "
                    f"unknown model '{model_id}': {per_base:.12f}/token"
                )
            )
            return per_base

        # 4. Global fallback
        APP_LOGGER.warning(
            msg=f"No price for model '{model_id}' {token_type} – using global fallback"
        )
        return self.default_fallback_price

    # ── model-id helpers ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_model_id(model_id: str) -> str:
        """Strip publisher prefix and ``@version`` suffix.

        Examples::

            publishers/anthropic/models/claude-3-opus@20240229
            → claude-3-opus

            gemini-2.5-pro@001  →  gemini-2.5-pro
        """
        if "/models/" in model_id:
            model_id = model_id.split("/models/")[-1]
        if "@" in model_id:
            model_id = model_id.split("@")[0]
        return model_id

    @staticmethod
    def _extract_model_token_price(
        vertex_ai_data: dict[str, Any], model_key: str, token_type: str
    ) -> float | None:
        """Look up a model's per-token price from the catalog section."""
        model_data = vertex_ai_data.get(model_key)
        if model_data is None:
            return None
        entry = model_data.get(token_type)
        if entry is None:
            return None
        price_per_unit = float(entry.get("price_per_unit", 0))
        unit_size = int(entry.get("unit_size", 1))
        return price_per_unit / unit_size if unit_size > 0 else 0.0

    def get_free_tier(self, service_key: str) -> dict[str, Any]:
        """Return free-tier configuration for a service.

        Returns an empty dict if no free tier is defined.
        """
        free_tiers = self._data.get("free_tiers", {})
        return free_tiers.get(service_key, {})

    def validate_region(self, region: str) -> bool:
        """Check whether the catalog region matches the requested region.

        Args:
            region: Region string to validate (e.g. 'us-central1').

        Returns:
            True if the catalog covers the requested region.
        """
        catalog_region = self.region
        if catalog_region != region:
            APP_LOGGER.warning(
                msg=(
                    f"Region mismatch: catalog covers '{catalog_region}' "
                    f"but requested region is '{region}'"
                )
            )
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        """Return a summary of the loaded catalog (for health/status endpoints)."""
        return {
            "version": self.version,
            "region": self.region,
            "currency": self.currency,
            "default_fallback_price": self.default_fallback_price,
            "indexed_sku_count": len(self._sku_index),
            "services": list(
                k for k in ("vertex_ai", "bigquery", "firestore") if k in self._data
            ),
        }

    # ── internal ──────────────────────────────────────────────────────────

    def _load_catalog(self) -> None:
        """Load and validate the pricing catalog from disk."""
        APP_LOGGER.info(msg=f"Loading static pricing catalog from: {self._catalog_path}")

        try:
            with open(self._catalog_path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except FileNotFoundError:
            APP_LOGGER.error(
                msg=f"Pricing catalog not found: {self._catalog_path}"
            )
            self._data = {}
            return
        except json.JSONDecodeError as exc:
            APP_LOGGER.error(
                msg=f"Invalid JSON in pricing catalog: {exc}"
            )
            self._data = {}
            return

        if not self._validate_schema():
            APP_LOGGER.warning(msg="Pricing catalog schema validation failed – partial data may be used")

        self._build_sku_index()

        APP_LOGGER.info(
            msg=(
                f"Pricing catalog loaded: version={self.version} "
                f"region={self.region} currency={self.currency} "
                f"indexed_skus={len(self._sku_index)}"
            )
        )

    def _validate_schema(self) -> bool:
        """Validate required top-level keys exist in the catalog."""
        missing = _REQUIRED_KEYS - set(self._data.keys())
        if missing:
            APP_LOGGER.warning(
                msg=f"Pricing catalog missing required keys: {missing}"
            )
            return False
        return True

    def _build_sku_index(self) -> None:
        """Build a flat sku_id → pricing-entry index across all services."""
        self._sku_index = {}

        for service_key in ("vertex_ai", "bigquery", "firestore"):
            service_data = self._data.get(service_key, {})
            self._index_service_entries(service_key, service_data)

        APP_LOGGER.debug(
            msg=f"Built SKU index with {len(self._sku_index)} entries"
        )

    def _index_service_entries(
        self, service_key: str, data: dict[str, Any], prefix: str = ""
    ) -> None:
        """Recursively index pricing entries that contain a billing_sku_id."""
        for key, value in data.items():
            if not isinstance(value, dict):
                continue

            current_prefix = f"{prefix}{key}/" if prefix else f"{key}/"

            if "billing_sku_id" in value and "price_per_unit" in value:
                sku_id = value["billing_sku_id"]
                self._sku_index[sku_id] = value
                APP_LOGGER.debug(
                    msg=(
                        f"Indexed: {service_key}/{current_prefix.rstrip('/')} "
                        f"→ SKU {sku_id}"
                    )
                )
            else:
                # Recurse into nested dicts (e.g. model → input/output)
                self._index_service_entries(service_key, value, current_prefix)

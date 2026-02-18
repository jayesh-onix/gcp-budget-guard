"""Wrapper for Google Cloud Billing Catalog API – live SKU pricing.

Replaces the previous hardcoded price dictionaries with real-time
lookups from the Cloud Billing Catalog (CloudCatalogClient).
"""

from typing import Any

from google.cloud.billing_v1 import CloudCatalogClient
from google.cloud.billing_v1.types import Sku

from helpers.constants import APP_LOGGER, CURRENCY_CODE


class CloudBillingWrapper:
    """Fetch SKU prices from the Cloud Billing Catalog API."""

    def __init__(self) -> None:
        self.client = CloudCatalogClient()
        # Cache: service_id → {sku_id → Sku}
        self._sku_cache: dict[str, dict[str, Sku]] = {}
        APP_LOGGER.info(msg="Cloud Billing wrapper initialised (SKU pricing).")

    # ── public ────────────────────────────────────────────────────────────

    def get_sku_price_per_unit(
        self,
        service_id: str,
        sku_id: str,
        price_tier: int = 0,
    ) -> float | None:
        """Return the price-per-base-unit for a given SKU.

        For example, for BigQuery "Analysis" the usage_unit is 1 TiB but the
        base_unit is 1 byte.  The conversion factor normalises the price
        to the smallest unit so that it can be multiplied directly by the
        raw metric value from Cloud Monitoring.
        """
        APP_LOGGER.debug(
            msg=f"Looking up price for service={service_id} sku={sku_id} tier={price_tier}"
        )
        self._ensure_skus_loaded(service_id)
        return self._extract_price(service_id, sku_id, price_tier)

    # ── internals ─────────────────────────────────────────────────────────

    def _ensure_skus_loaded(self, service_id: str) -> None:
        """Load all SKUs for a service into the local cache (once)."""
        if service_id in self._sku_cache:
            return

        self._sku_cache[service_id] = {}
        try:
            for sku in self.client.list_skus(
                request={
                    "parent": f"services/{service_id}",
                    "currency_code": CURRENCY_CODE,
                }
            ):
                self._sku_cache[service_id][sku.sku_id] = sku
        except Exception as exc:
            APP_LOGGER.error(msg=f"Error loading SKUs for service {service_id}: {exc}")

    def _extract_price(
        self, service_id: str, sku_id: str, price_tier: int
    ) -> float | None:
        """Extract normalised price-per-base-unit from a cached Sku object."""
        service_skus = self._sku_cache.get(service_id, {})
        sku: Sku | None = service_skus.get(sku_id)
        if sku is None:
            APP_LOGGER.warning(
                msg=f"SKU {sku_id} not found in service {service_id}"
            )
            return None

        if not sku.pricing_info:
            return None

        pricing_expression = sku.pricing_info[0].pricing_expression
        if not pricing_expression or not pricing_expression.tiered_rates:
            return None

        # Pick the requested pricing tier
        tier_index = min(price_tier, len(pricing_expression.tiered_rates) - 1)
        tiered_rate = pricing_expression.tiered_rates[tier_index]

        price_per_usage_unit = (
            tiered_rate.unit_price.nanos / 1e9 + tiered_rate.unit_price.units
        )
        conversion_factor = pricing_expression.base_unit_conversion_factor or 1
        price_per_base_unit = price_per_usage_unit / conversion_factor

        APP_LOGGER.debug(
            msg=(
                f"SKU {sku_id}: {price_per_usage_unit} {CURRENCY_CODE} per "
                f"{pricing_expression.usage_unit_description} → "
                f"{price_per_base_unit} per {pricing_expression.base_unit_description}"
            )
        )
        return price_per_base_unit

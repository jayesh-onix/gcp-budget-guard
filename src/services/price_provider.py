"""Pricing provider abstraction layer.

Defines a common interface for price lookups and provides two
concrete implementations:

* **CloudBillingPriceProvider** – live pricing via Cloud Billing Catalog API.
* **StaticPriceProvider** – offline pricing from a local JSON catalog.

Provider selection is driven by environment variables:

* ``LAB_MODE=True``  → StaticPriceProvider
* ``PRICE_SOURCE=static`` → StaticPriceProvider
* Otherwise → CloudBillingPriceProvider (with automatic fallback to
  static pricing when the billing API is unavailable).

The factory function :func:`create_price_provider` encapsulates this logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from helpers.constants import APP_LOGGER


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Interface
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PriceProvider(ABC):
    """Abstract base for all pricing providers.

    Every provider must be able to:
    1. Return a price-per-base-unit for a (service_id, sku_id) pair.
    2. Identify itself by name (for logging / status endpoints).
    """

    @abstractmethod
    def get_price_per_unit(
        self,
        service_id: str,
        sku_id: str,
        price_tier: int = 0,
    ) -> float | None:
        """Return the price per base unit for a given SKU.

        Args:
            service_id: Cloud Billing service ID (e.g. 'C7E2-9256-1C43').
            sku_id: Cloud Billing SKU ID (e.g. 'A121-E2B5-1418').
            price_tier: Which tier of tiered pricing to use (0-based).

        Returns:
            Price per base unit, or None if unavailable.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name of this provider (e.g. 'cloud_billing')."""

    def as_dict(self) -> dict[str, Any]:
        """Serialisable summary for status endpoints."""
        return {"provider": self.provider_name}

    def get_vertex_ai_token_price(
        self, model_id: str, token_type: str
    ) -> float | None:
        """Return the price per base token for a Vertex AI model.

        The default implementation returns ``None``; subclasses that can
        resolve model-specific pricing should override this method.
        """
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CloudBillingPriceProvider  (production)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CloudBillingPriceProvider(PriceProvider):
    """Fetches live pricing from the Cloud Billing Catalog API.

    Wraps the existing :class:`CloudBillingWrapper` so all existing
    production behaviour is preserved.
    """

    def __init__(self) -> None:
        from wrappers.cloud_billing import CloudBillingWrapper

        self._billing = CloudBillingWrapper()
        APP_LOGGER.info(msg="CloudBillingPriceProvider initialised (live billing API)")

    @property
    def provider_name(self) -> str:
        return "cloud_billing"

    def get_price_per_unit(
        self,
        service_id: str,
        sku_id: str,
        price_tier: int = 0,
    ) -> float | None:
        return self._billing.get_sku_price_per_unit(
            service_id=service_id,
            sku_id=sku_id,
            price_tier=price_tier,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "source": "Cloud Billing Catalog API"}

    def get_vertex_ai_token_price(
        self, model_id: str, token_type: str
    ) -> float | None:
        # Cloud Billing is indexed by SKU, not by model name.
        # Return None so that the FallbackPriceProvider delegates to the
        # static catalog for model-based lookups.
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  StaticPriceProvider  (lab / fallback)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StaticPriceProvider(PriceProvider):
    """Retrieves pricing from the local static catalog.

    Uses :class:`PriceCatalogService` to load
    ``config/pricing_catalog.json`` and resolve SKU-level prices.
    """

    def __init__(self, catalog_path: str | None = None) -> None:
        from services.price_catalog_service import PriceCatalogService

        self._catalog = PriceCatalogService(catalog_path=catalog_path)
        APP_LOGGER.info(
            msg=(
                f"StaticPriceProvider initialised "
                f"(catalog v{self._catalog.version}, "
                f"region={self._catalog.region})"
            )
        )

    @property
    def provider_name(self) -> str:
        return "static_catalog"

    def get_price_per_unit(
        self,
        service_id: str,
        sku_id: str,
        price_tier: int = 0,
    ) -> float | None:
        # Static catalog is indexed by sku_id; service_id is used only
        # as a hint for logging.  The service_key is not needed for lookup.
        return self._catalog.get_price_per_base_unit(
            service_key=service_id,
            sku_id=sku_id,
            use_fallback=True,
        )

    def get_vertex_ai_token_price(
        self, model_id: str, token_type: str
    ) -> float | None:
        """Resolve per-token price from the static catalog by model name."""
        return self._catalog.get_vertex_ai_model_price(model_id, token_type)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "catalog": self._catalog.as_dict(),
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FallbackPriceProvider  (auto-recovery wrapper)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FallbackPriceProvider(PriceProvider):
    """Wraps a primary provider with an automatic static-catalog fallback.

    On each price lookup:
    1. Try the *primary* provider.
    2. If it raises an exception or returns ``None``, try the *fallback*
       (static catalog).
    3. If both fail, return ``None``.
    """

    def __init__(
        self,
        primary: PriceProvider,
        fallback: PriceProvider | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback or StaticPriceProvider()
        self._fallback_count = 0
        APP_LOGGER.info(
            msg=(
                f"FallbackPriceProvider: primary={primary.provider_name}, "
                f"fallback={self._fallback.provider_name}"
            )
        )

    @property
    def provider_name(self) -> str:
        return f"fallback({self._primary.provider_name}→{self._fallback.provider_name})"

    def get_price_per_unit(
        self,
        service_id: str,
        sku_id: str,
        price_tier: int = 0,
    ) -> float | None:
        # Try primary
        try:
            price = self._primary.get_price_per_unit(service_id, sku_id, price_tier)
            if price is not None:
                return price
        except Exception as exc:
            APP_LOGGER.warning(
                msg=(
                    f"Primary pricing provider ({self._primary.provider_name}) "
                    f"failed for SKU {sku_id}: {exc}"
                )
            )

        # Fallback
        self._fallback_count += 1
        APP_LOGGER.info(
            msg=(
                f"Falling back to {self._fallback.provider_name} "
                f"for SKU {sku_id} (fallback #{self._fallback_count})"
            )
        )
        try:
            return self._fallback.get_price_per_unit(service_id, sku_id, price_tier)
        except Exception as exc:
            APP_LOGGER.error(
                msg=f"Fallback provider also failed for SKU {sku_id}: {exc}"
            )
            return None

    def get_vertex_ai_token_price(
        self, model_id: str, token_type: str
    ) -> float | None:
        """Resolve model-based price: try primary, then fallback."""
        try:
            price = self._primary.get_vertex_ai_token_price(model_id, token_type)
            if price is not None:
                return price
        except Exception:
            pass

        try:
            return self._fallback.get_vertex_ai_token_price(model_id, token_type)
        except Exception:
            return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "primary": self._primary.as_dict(),
            "fallback": self._fallback.as_dict(),
            "fallback_invocations": self._fallback_count,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_price_provider() -> PriceProvider:
    """Create the appropriate PriceProvider based on environment config.

    Selection logic::

        LAB_MODE=True           → StaticPriceProvider
        PRICE_SOURCE=static     → StaticPriceProvider
        PRICE_SOURCE=billing    → FallbackPriceProvider(CloudBilling → Static)
        (default)               → FallbackPriceProvider(CloudBilling → Static)

    Returns:
        A ready-to-use PriceProvider instance.
    """
    from helpers.constants import LAB_MODE, PRICE_SOURCE

    if LAB_MODE:
        APP_LOGGER.info(msg="LAB_MODE active → using StaticPriceProvider")
        return StaticPriceProvider()

    if PRICE_SOURCE == "static":
        APP_LOGGER.info(msg="PRICE_SOURCE=static → using StaticPriceProvider")
        return StaticPriceProvider()

    # Production: Cloud Billing with automatic static fallback
    APP_LOGGER.info(
        msg="PRICE_SOURCE=billing → using CloudBillingPriceProvider with static fallback"
    )
    try:
        primary = CloudBillingPriceProvider()
    except Exception as exc:
        APP_LOGGER.error(
            msg=(
                f"Failed to initialise CloudBillingPriceProvider: {exc}. "
                f"Falling back to StaticPriceProvider."
            )
        )
        return StaticPriceProvider()

    return FallbackPriceProvider(primary=primary)

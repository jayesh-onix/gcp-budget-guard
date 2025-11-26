"""Vertex AI Prices."""

from dataclasses import dataclass


@dataclass
class ModelPrice:
    """Price per Publisher ModelId input / output Token."""

    input: float
    output: float
    price_per_batch: int

    def get_price_per_token(self, metric_type: str) -> float:
        """Return normalized value 'per'."""
        return getattr(self, metric_type) / self.price_per_batch


RAW_GEMINI_PRICES = {
    # model_name, input, output, price_per_batch
    "gemini-3-pro": (4.00, 18.00, 1_000_000),
    "gemini-3-pro-image-preview": (2.00, 120.00, 1_000_000),
    "gemini-2.5-pro": (2.50, 15.00, 1_000_000),
    "gemini-2.5-flash": (0.30, 2.50, 1_000_000),
    "gemini-2.5-flash-lite": (0.10, 0.40, 1_000_000),
    "gemini-2.5-flash-native-audio-preview-09-2025": (0.50, 12.00, 1_000_000),
    "gemini-2.5-flash-image": (0.30, 0.039, 1_000_000),
    "gemini-2.5-flash-preview-tts": (0.50, 10.00, 1_000_000),
    "gemini-2.5-pro-preview-tts": (1.00, 20.00, 1_000_000),
    "gemini-2.0-flash": (0.10, 0.40, 1_000_000),
    "gemini-2.0-flash-lite": (0.075, 0.30, 1_000_000),
    "imagen-4.0-fast-generate-001": (0.00, 0.02, 1),
    "imagen-4.0-generate-001": (0.00, 0.04, 1),
    "imagen-4.0-ultra-001": (0.00, 0.06, 1),
    "imagen-3.0-generate-002": (0.00, 0.03, 1),
    "gemini-embedding-001": (0.15, 0.00, 1_000_000),
}

GEMINI_PRICES = {k: ModelPrice(*v) for k, v in RAW_GEMINI_PRICES.items()}

"""Firestore Prices."""

FIRESTORE_PRICES: dict[str, float] = {
    "read": 0.03,
    "write": 0.09,
    "delete": 0.01,
    "ttl_delete": 0.01,
}

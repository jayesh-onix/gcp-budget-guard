"""Utility functions for date/time operations."""

from datetime import datetime, timezone


def first_day_of_current_month_utc() -> datetime:
    """Return midnight UTC on the first day of the current month."""
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)

"""Tests for helpers.utils."""

from datetime import datetime, timezone

from helpers.utils import first_day_of_current_month_utc, now_utc


def test_first_day_is_day_one():
    dt = first_day_of_current_month_utc()
    assert dt.day == 1
    assert dt.hour == 0
    assert dt.minute == 0
    assert dt.second == 0
    assert dt.tzinfo == timezone.utc


def test_now_utc_is_utc():
    dt = now_utc()
    assert dt.tzinfo == timezone.utc
    # Should be very close to actual now
    diff = abs((datetime.now(timezone.utc) - dt).total_seconds())
    assert diff < 2

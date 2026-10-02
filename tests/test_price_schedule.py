from datetime import datetime
from zoneinfo import ZoneInfo

from stockscanner.price_schedule import resolve_collection_window
from stockscanner.snapshot_health import snapshot_health


NY = ZoneInfo("America/New_York")


def at(hour, minute=0, *, day=24):
    return datetime(2026, 9, day, hour, minute, tzinfo=NY)


def test_frequent_attempts_share_latest_due_hourly_slot():
    assert resolve_collection_window(at(8, 44))["valid"] is False
    assert resolve_collection_window(at(8, 52))["slot"] == "2026-09-24:08:45"
    assert resolve_collection_window(at(9, 7))["slot"] == "2026-09-24:08:45"
    assert resolve_collection_window(at(9, 52))["slot"] == "2026-09-24:09:45"


def test_close_retries_share_one_slot_until_20_new_york():
    first = resolve_collection_window(at(16, 7))
    retry = resolve_collection_window(at(19, 52))
    assert first == {
        "valid": True,
        "mode": "close",
        "market_date": "2026-09-24",
        "slot": "2026-09-24:close",
    }
    assert retry["slot"] == first["slot"]
    assert resolve_collection_window(at(20, 1))["valid"] is False


def test_weekend_and_explicit_modes_are_guarded():
    assert resolve_collection_window(at(10, day=26))["valid"] is False
    assert resolve_collection_window(at(15), "close")["valid"] is False
    assert resolve_collection_window(at(17), "hourly")["valid"] is False


def test_snapshot_health_uses_75_minute_threshold_and_alpaca_count():
    now = datetime.fromisoformat("2026-09-24T15:00:00-04:00")
    payload = {
        "generated_at": "2026-09-24T13:44:59-04:00",
        "provider_counts": {"Alpaca": 0, "Yahoo": 440},
        "provider_status": {"Alpaca": {"status": "missing_credentials"}},
    }
    health = snapshot_health(payload, now=now)
    assert health["fresh"] is False
    assert health["alpaca_ready"] is False
    assert health["alpaca_status"] == "missing_credentials"

    payload["generated_at"] = "2026-09-24T13:45:00-04:00"
    payload["provider_counts"]["Alpaca"] = 220
    payload["provider_status"]["Alpaca"]["status"] = "ok"
    health = snapshot_health(payload, now=now)
    assert health["fresh"] is True
    assert health["alpaca_ready"] is True
    assert health["alpaca_status"] == "ok"

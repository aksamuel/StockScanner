import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stockscanner.failed_symbol_store import (
    FailedSymbolStoreError,
    read_failed_symbols,
    read_scan_timestamp,
    record_failed_symbol_scan,
)


NEW_YORK = ZoneInfo("America/New_York")


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b""


def test_record_failed_symbol_scan_calls_idempotent_history_rpc():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    scanned_at = datetime(2026, 10, 2, 8, 46, tzinfo=NEW_YORK)
    row = record_failed_symbol_scan(
        scan_type="hourly",
        workflow_run_id=1234,
        failed_symbols=[
            {"symbol": "bbb", "reason": "missing quote"},
            {"symbol": "AAA", "reason": "provider timeout"},
            {"symbol": "aaa", "reason": "last duplicate"},
        ],
        attempted_symbols=["AAA", "BBB", "CCC"],
        supabase_url="https://example.supabase.co/",
        secret_key="sb_secret_test",
        scan_at=scanned_at,
        opener=opener,
    )

    request, timeout = requests[0]
    payload = json.loads(request.data)
    assert request.full_url.endswith("/rest/v1/rpc/record_failed_symbol_scan")
    assert request.get_header("Apikey") == "sb_secret_test"
    assert request.get_header("Authorization") is None
    assert request.get_header("Prefer") == "return=minimal"
    assert timeout == 30
    assert payload["p_market_date"] == "2026-10-02"
    assert payload["p_scan_type"] == "hourly"
    assert payload["p_workflow_run_id"] == 1234
    assert payload["p_scan_at"] == scanned_at.isoformat()
    assert payload["p_attempted_symbols"] == ["AAA", "BBB", "CCC"]
    assert payload["p_failed_symbols"] == [
        {"symbol": "AAA", "reason": "last duplicate"},
        {"symbol": "BBB", "reason": "missing quote"},
    ]
    assert row["scan_type"] == "hourly"


def test_read_failed_symbols_supports_daily_and_hourly_payloads(tmp_path):
    daily_file = tmp_path / "daily.json"
    daily_file.write_text(json.dumps({
        "failed_symbols": [{"symbol": "abc", "reason": "download_failure"}],
    }), encoding="utf-8")
    hourly_file = tmp_path / "hourly.json"
    hourly_file.write_text(json.dumps({
        "scanned_at": "2026-10-02T08:45:00-04:00",
        "failures": {"XYZ": "all providers returned no price"},
    }), encoding="utf-8")

    assert read_failed_symbols(daily_file) == [
        {"symbol": "ABC", "reason": "download_failure"},
    ]
    assert read_failed_symbols(hourly_file) == [
        {"symbol": "XYZ", "reason": "all providers returned no price"},
    ]
    assert read_scan_timestamp(hourly_file) == datetime(
        2026, 10, 2, 8, 45, tzinfo=NEW_YORK,
    )


def test_record_failed_symbol_scan_rejects_naive_timestamps():
    with pytest.raises(FailedSymbolStoreError, match="timezone-aware"):
        record_failed_symbol_scan(
            scan_type="daily",
            workflow_run_id=1234,
            failed_symbols=[],
            supabase_url="https://example.supabase.co",
            secret_key="secret",
            scan_at=datetime(2026, 10, 2, 8),
        )


def test_read_failed_symbols_rejects_invalid_scan_payload(tmp_path):
    source = Path(tmp_path) / "bad.json"
    source.write_text(json.dumps({"failures": []}), encoding="utf-8")

    with pytest.raises(FailedSymbolStoreError, match="JSON object"):
        read_failed_symbols(source)


def test_load_pending_failed_symbols_is_scoped_to_scan_type_and_prior_dates():
    from stockscanner.failed_symbol_store import load_pending_failed_symbols

    requests = []

    def opener(request, timeout):
        requests.append(request)
        return type("Response", (FakeResponse,), {
            "read": lambda self: json.dumps([{
                "symbol": "abc",
                "scan_type": "daily",
                "last_failed_market_date": "2026-10-01",
                "last_reason": "download_failure",
            }]).encode(),
        })()

    rows = load_pending_failed_symbols(
        scan_type="daily",
        before_market_date="2026-10-02",
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        opener=opener,
    )

    assert rows == [{
        "symbol": "ABC",
        "reason": "download_failure",
        "scan_type": "daily",
        "last_failed_market_date": "2026-10-01",
    }]
    assert "status=eq.pending" in requests[0].full_url
    assert "last_failed_market_date=lt.2026-10-02" in requests[0].full_url
    assert "scan_type=eq.daily" in requests[0].full_url

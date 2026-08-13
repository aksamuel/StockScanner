import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stockscanner.price_snapshot import (
    SnapshotError,
    is_regular_market_session,
    refresh_snapshot,
    write_snapshot_from_results,
)


NEW_YORK = ZoneInfo("America/New_York")


def ny_time(hour, minute=0, *, day=13):
    return datetime(2026, 8, day, hour, minute, tzinfo=NEW_YORK)


def test_regular_market_session_gate_includes_open_and_close():
    assert not is_regular_market_session(ny_time(9, 29))
    assert is_regular_market_session(ny_time(9, 30))
    assert is_regular_market_session(ny_time(16))
    assert not is_regular_market_session(ny_time(16, 1))
    assert not is_regular_market_session(ny_time(12, day=15))


def test_refresh_outside_market_hours_does_not_write(tmp_path):
    snapshot_path = tmp_path / "prices.json"

    result = refresh_snapshot(snapshot_path, now=ny_time(9))

    assert result["published"] is False
    assert result["reason"] == "outside_regular_market_session"
    assert not snapshot_path.exists()


def test_refresh_writes_json_and_preserves_failed_symbol_price(tmp_path, capsys):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [
            {
                "Symbol": "AAA",
                "Current Price": 10,
                "Price As Of": "2026-08-13T09:55:00-04:00",
            },
            {"Symbol": "BBB", "Current Price": 20},
        ],
        snapshot_path,
        ny_time(9),
    )
    initial_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert (
        initial_payload["price_timestamp_new_york"]
        == "13 August 2026, 09:55 AM EDT"
    )

    def downloader(symbol, now):
        if symbol == "AAA":
            return {
                "price": 11.25,
                "timestamp": "2026-08-13T09:59:00-04:00",
            }
        raise RuntimeError("rate limited")

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        downloader=downloader,
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result == {
        "published": True,
        "updated": 1,
        "failed": 1,
        "symbols": 2,
        "path": str(snapshot_path),
    }
    assert payload["prices"] == {"AAA": 11.25, "BBB": 20.0}
    assert payload["updated_symbols"] == ["AAA"]
    assert payload["failures"] == {"BBB": "RuntimeError: rate limited"}
    assert payload["generated_at_new_york"].endswith("EDT")
    assert payload["price_timestamp_new_york"] == "13 August 2026, 09:59 AM EDT"
    assert "Price refresh failed for BBB" in capsys.readouterr().err


def test_refresh_preserves_snapshot_when_all_yahoo_requests_fail(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "AAA", "Current Price": 10}],
        snapshot_path,
        ny_time(9),
    )
    original = snapshot_path.read_text(encoding="utf-8")

    with pytest.raises(SnapshotError, match="prior snapshot was preserved"):
        refresh_snapshot(
            snapshot_path,
            now=ny_time(10),
            downloader=lambda symbol, now: None,
        )

    assert snapshot_path.read_text(encoding="utf-8") == original


def test_refresh_bootstraps_symbols_from_generated_report(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    report_path = tmp_path / "technical.html"
    report_path.write_text(
        '<table><tr data-current-price="42.5">'
        '<td><span class="symbol-name">XYZ</span></td></tr></table>',
        encoding="utf-8",
    )

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        downloader=lambda symbol, now: {"price": 43.75},
        report_paths=[report_path],
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["updated"] == 1
    assert payload["prices"] == {"XYZ": 43.75}
    assert payload["price_timestamp_new_york"] is None

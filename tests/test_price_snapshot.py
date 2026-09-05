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

    result = refresh_snapshot(snapshot_path, now=ny_time(8, 44))

    assert result["published"] is False
    assert result["reason"] == "outside_price_collection_window"
    assert not snapshot_path.exists()


def test_refresh_accepts_first_premarket_collection_at_0845(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "AAA", "Current Price": 10}],
        snapshot_path,
        ny_time(8, 30),
    )

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(8, 45),
        alpaca_downloader=lambda symbols, now: {
            "AAA": {
                "price": 10.25,
                "daily_close": 10.0,
                "timestamp": ny_time(8, 44),
            }
        },
        downloader=lambda symbol, now: None,
    )

    assert result["published"] is True
    assert result["updated"] == 1


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
        == "13/Aug/2026, 09:55 EDT"
    )

    def downloader(symbol, now):
        if symbol == "AAA":
            return {
                "price": 11.25,
                "daily_close": 10.5,
                "timestamp": "2026-08-13T09:59:00-04:00",
            }
        raise RuntimeError("rate limited")

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        downloader=downloader,
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["published"] is True
    assert result["updated"] == 1
    assert result["failed"] == 1
    assert result["symbols"] == 2
    assert result["provider_counts"] == {"Alpaca": 0, "Yahoo": 1, "Twelve Data": 0}
    assert result["portfolio_missing"] == 0
    assert result["collection_kind"] == "intraday"
    assert result["path"] == str(snapshot_path)
    assert payload["prices"] == {"AAA": 11.25, "BBB": 20.0}
    assert payload["daily_prices"] == {"AAA": 10.5}
    assert payload["previous_close_prices"] == {"AAA": 10.5}
    assert payload["market_date"] == "2026-08-13"
    assert payload["intraday_series"]["AAA"] == [
        {"timestamp": "2026-08-13T09:59:00-04:00", "price": 11.25}
    ]
    assert payload["updated_symbols"] == ["AAA"]
    assert "Yahoo: RuntimeError: rate limited" in payload["failures"]["BBB"]
    assert payload["provider_counts"] == {
        "Alpaca": 0,
        "Yahoo": 1,
        "Twelve Data": 0,
    }
    assert payload["generated_at_new_york"].endswith("EDT")
    assert payload["price_timestamp_new_york"] == "13/Aug/2026, 09:59 EDT"
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


def test_refresh_splits_primary_work_and_cross_fails_over(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [
            {"Symbol": symbol, "Current Price": price}
            for symbol, price in zip(["AAA", "BBB", "CCC", "DDD"], range(10, 14))
        ],
        snapshot_path,
        ny_time(9),
    )
    alpaca_calls = []
    yahoo_calls = []

    def alpaca(symbols, now):
        alpaca_calls.append(list(symbols))
        return {
            symbol: {"price": 20 + index, "timestamp": now.isoformat()}
            for index, symbol in enumerate(symbols)
            if symbol in {"AAA", "DDD"}
        }

    def yahoo(symbol, now):
        yahoo_calls.append(symbol)
        if symbol in {"BBB", "CCC"}:
            return {"price": 30 + len(yahoo_calls), "timestamp": now.isoformat()}
        return None

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        downloader=yahoo,
        alpaca_downloader=alpaca,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert alpaca_calls == [["AAA", "CCC"], ["DDD"]]
    assert yahoo_calls == ["BBB", "DDD", "CCC"]
    assert result["updated"] == 4
    assert result["failed"] == 0
    assert result["provider_counts"] == {
        "Alpaca": 2,
        "Yahoo": 2,
        "Twelve Data": 0,
    }
    assert payload["collection_strategy"] == "free_split_with_bounded_failover"


def test_refresh_caps_twelve_data_fallback_at_eight_free_credits(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    symbols = [f"S{index:02d}" for index in range(12)]
    write_snapshot_from_results(
        [{"Symbol": symbol, "Current Price": 10} for symbol in symbols],
        snapshot_path,
        ny_time(9),
    )
    twelve_calls = []

    def twelve_data(requested, now):
        twelve_calls.append(list(requested))
        return {
            symbol: {"price": 12.5, "timestamp": now.isoformat()}
            for symbol in requested
        }

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        downloader=lambda symbol, now: None,
        alpaca_downloader=lambda symbols, now: {},
        twelve_data_downloader=twelve_data,
    )

    assert len(twelve_calls) == 1
    assert len(twelve_calls[0]) == 8
    assert result["provider_counts"]["Twelve Data"] == 8
    assert result["updated"] == 8
    assert result["failed"] == 4


def test_refresh_adds_user_held_symbols_outside_the_scanner_universe(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "NYSE1", "Current Price": 10}],
        snapshot_path,
        ny_time(9),
    )

    def alpaca(symbols, now):
        return {
            symbol: {"price": 25, "timestamp": now.isoformat()}
            for symbol in symbols
        }

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        additional_symbols=["nasdaq1", "amex1", "NYSE1", "nasdaq1"],
        alpaca_downloader=alpaca,
        downloader=lambda symbol, now: {
            "price": 30,
            "timestamp": now.isoformat(),
        },
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["symbols"] == 3
    assert payload["prices"] == {
        "AMEX1": 25.0,
        "NASDAQ1": 30.0,
        "NYSE1": 25.0,
    }
    assert payload["requested_symbol_count"] == 3
    assert payload["portfolio_symbol_count"] == 3


def test_refresh_keeps_only_current_day_intraday_points(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "AAA", "Current Price": 10}],
        snapshot_path,
        ny_time(9, day=12),
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["intraday_series"] = {
        "AAA": [{"timestamp": "2026-08-12T15:00:00-04:00", "price": 10.1}]
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    refresh_snapshot(
        snapshot_path,
        now=ny_time(10, day=13),
        alpaca_downloader=lambda symbols, now: {
            symbol: {
                "price": 10.5,
                "daily_close": 10.0,
                "timestamp": now.isoformat(),
            }
            for symbol in symbols
        },
        downloader=lambda symbol, now: None,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert payload["intraday_series"] == {
        "AAA": [{"timestamp": "2026-08-13T10:00:00-04:00", "price": 10.5}]
    }
    assert payload["daily_prices"] == {"AAA": 10.0}


def test_new_market_day_drops_unrefreshed_daily_comparisons(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [
            {"Symbol": "AAA", "Current Price": 10},
            {"Symbol": "BBB", "Current Price": 20},
        ],
        snapshot_path,
        ny_time(15, day=12),
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["daily_prices"] = {"AAA": 9.5, "BBB": 19.5}
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    refresh_snapshot(
        snapshot_path,
        now=ny_time(10, day=13),
        alpaca_downloader=lambda symbols, now: {
            "AAA": {
                "price": 10.25,
                "daily_close": 10.0,
                "timestamp": now.isoformat(),
            }
        },
        downloader=lambda symbol, now: None,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert payload["market_date"] == "2026-08-13"
    assert payload["daily_prices"] == {"AAA": 10.0}
    assert "BBB" not in payload["intraday_series"]


def test_market_close_becomes_next_day_previous_close(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "AAA", "Current Price": 10}],
        snapshot_path,
        ny_time(15, day=12),
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["market_close_prices"] = {"AAA": 10.75}
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    refresh_snapshot(
        snapshot_path,
        now=ny_time(10, day=13),
        alpaca_downloader=lambda symbols, now: {
            "AAA": {"price": 11, "timestamp": now.isoformat()}
        },
        downloader=lambda symbol, now: None,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert payload["previous_close_prices"] == {"AAA": 10.75}
    assert payload["market_close_prices"] == {}


def test_post_close_run_records_current_market_close(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "AAA", "Current Price": 10}],
        snapshot_path,
        ny_time(15),
    )

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(16, 15),
        close_run=True,
        alpaca_downloader=lambda symbols, now: {
            "AAA": {"price": 10.8, "timestamp": now.isoformat()}
        },
        downloader=lambda symbol, now: None,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["collection_kind"] == "market_close"
    assert payload["market_close_prices"] == {"AAA": 10.8}


def test_failed_new_held_symbol_is_reported_without_invalid_stored_price(tmp_path):
    snapshot_path = tmp_path / "prices.json"
    write_snapshot_from_results(
        [{"Symbol": "NYSE1", "Current Price": 10}],
        snapshot_path,
        ny_time(9),
    )

    result = refresh_snapshot(
        snapshot_path,
        now=ny_time(10),
        additional_symbols=["NASDAQ1"],
        alpaca_downloader=lambda symbols, now: {
            "NYSE1": {"price": 11, "timestamp": now.isoformat()}
        },
        downloader=lambda symbol, now: None,
        twelve_data_downloader=lambda symbols, now: {},
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["symbols"] == 1
    assert result["failed"] == 1
    assert payload["prices"] == {"NYSE1": 11.0}
    assert "NASDAQ1" in payload["failures"]
    assert payload["requested_symbol_count"] == 2

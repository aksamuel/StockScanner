from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from portfolio import (
    PortfolioAnalysis,
    PortfolioScheduler,
    SnapshotStatus,
    SupabaseCollectionLock,
    YahooCache,
    as_ny,
    hour_slot_key,
    market_is_open,
)
from stockscanner.market_data import download_data
from stockscanner.scoring import score_stock
from stockscanner.signals import generate_signal


def test_score_stock_basic():
    df = pd.DataFrame([
        {
            "Close": 120.0,
            "MA200": 100.0,
            "MA20": 110.0,
            "MA50": 105.0,
            "RSI": 60.0,
            "MACD": 1.0,
            "MACD_SIGNAL": 0.5,
            "AVG_VOLUME": 1000000.0,
            "Volume": 1200000.0,
            "High": 130.0,
        }
    ])
    score = score_stock(df, relative_strength=25)
    assert score >= 50


def test_generate_signal_neutral():
    df = pd.DataFrame([
        {
            "Close": 100.0,
            "High": 100.0,
            "MA20": 95.0,
            "MA50": 96.0,
            "MA200": 97.0,
            "RSI": 50.0,
            "MACD": -1.0,
            "MACD_SIGNAL": -0.5,
        }
    ])
    assert generate_signal(df) == "⚪ Neutral"


def test_scheduler_recovers_missed_hour_slots():
    now = datetime(2024, 5, 1, 19, 5, tzinfo=timezone.utc)
    scheduler = PortfolioScheduler(clock=lambda: now)
    scheduler.snapshots = {
        "2024-05-01T10:00": {
            "slot_key": "2024-05-01T10:00",
            "collected_at": "2024-05-01T10:00:00+00:00",
            "prices_stored": True,
        },
    }

    slots = scheduler._recover_missing_slots(now)
    assert slots == [
        "2024-05-01T11:00",
        "2024-05-01T12:00",
        "2024-05-01T13:00",
        "2024-05-01T14:00",
        "2024-05-01T15:00",
    ]
    assert hour_slot_key(now) == "2024-05-01T15:00"


def test_scheduler_releases_lock_after_collection_failure_and_retries():
    lock = SupabaseCollectionLock()
    attempts = {"count": 0}

    def collector(slot_key, now):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        return {"slot_key": slot_key, "collected_at": now.isoformat(), "prices_stored": True}

    scheduler = PortfolioScheduler(
        lock=lock,
        collector=collector,
        clock=lambda: datetime(2024, 5, 1, 18, 0, tzinfo=timezone.utc),
    )
    result = scheduler.run_cycle()
    assert result["slots"][0]["status"] == "retryable_failure"
    assert not lock.is_locked("2024-05-01T18:00")

    result = scheduler.run_cycle()
    assert result["slots"][0]["status"] == "saved"
    assert attempts["count"] == 2


def test_yahoo_cache_retries_with_backoff_and_initializes_cache(monkeypatch):
    calls = {"count": 0}
    cache = {}
    yahoo = YahooCache(cache=cache, retries=3, base_delay=0.01)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period):
            calls["count"] += 1
            if calls["count"] < 3:
                raise ValueError(f"temporary fail {calls['count']}")
            return {"symbol": self.symbol, "price": 123.45}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    value = yahoo.fetch_with_retries("AAPL", lambda symbol: FakeTicker(symbol).history("1y"))
    assert value == {"symbol": "AAPL", "price": 123.45}
    assert cache["_initialized"] is True
    assert cache["symbols"]["AAPL"] == value
    assert calls["count"] == 3


def test_freshness_watchdog_triggers_recovery_and_alert_for_stale_snapshot():
    alerts = []
    scheduler = PortfolioScheduler(
        snapshots={
            "2024-05-01T10:00": {
                "slot_key": "2024-05-01T10:00",
                "collected_at": "2024-05-01T10:00:00+00:00",
                "prices_stored": True,
            },
        },
        alert_handler=lambda title, message, **kwargs: alerts.append({"title": title, "message": message, **kwargs}),
        clock=lambda: datetime(2024, 5, 1, 15, 30, tzinfo=timezone.utc),
    )
    run_result = {"called": False}

    def fake_run_cycle(now=None, force=False):
        run_result["called"] = True
        return {"status": "recovery"}

    scheduler.run_cycle = fake_run_cycle
    status = scheduler.check_snapshot_freshness()
    assert status["status"] == "stale"
    assert status["minutes_old"] > 75
    assert status["recovery_run"] is True
    assert run_result["called"] is True
    assert alerts and alerts[0]["title"] == "Portfolio snapshot stale"


def test_status_and_analysis_report_stale_price_as_no_snapshot_collected():
    now = datetime(2024, 5, 1, 15, 30, tzinfo=timezone.utc)
    record = {
        "slot_key": "2024-05-01T10:00",
        "collected_at": "2024-05-01T10:00:00+00:00",
        "prices_stored": True,
    }
    scheduler = PortfolioScheduler(clock=lambda: now)
    status = scheduler.status_for_record(record, now)
    assert status.prices_stored is True
    assert status.stale is True
    assert status.status == "No snapshot collected"
    analysis = PortfolioAnalysis(status)
    assert "Stale prices" in analysis.summary
    assert status.price_color == "orange"
    assert analysis.price_color == "orange"
    assert market_is_open(as_ny(now))


def test_portfolio_analysis_moves_unavailable_tickers_to_secondary_table():
    status = SnapshotStatus("2024-05-01T15:00", "green", prices_stored=True)
    analysis = PortfolioAnalysis(status, [
        {"ticker": "AAPL", "rank": 20, "price": 190.0},
        {"ticker": "MSFT", "rank": 0, "price": None, "price_available": False},
        {"ticker": "TSLA", "rank": 100, "price": 170.0, "stale": True},
        {"ticker": "NVDA", "rank": 0, "price": 190.0, "broker": "Alpaca"},
    ])

    assert [row["ticker"] for row in analysis.tables[0]["rows"]] == ["NVDA", "AAPL", "TSLA"]
    assert analysis.tables[0]["rows"][0]["Symbols"] == "NVDA\n(Alpaca)"
    assert analysis.tables[0]["rows"][2]["stale"] is True
    assert analysis.tables[0]["rows"][2]["price_color"] == "orange"
    assert analysis.tables[0]["rows"][0]["price_color"] == "green"
    assert analysis.tables[1]["title"] == "Price Unavailable for Date"
    assert [row["ticker"] for row in analysis.tables[1]["rows"]] == ["MSFT"]


def test_download_data_retries_cache_failures(monkeypatch, tmp_path):
    calls = {"count": 0}

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period):
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("temporary")
            return pd.DataFrame({"Close": [100.0]})

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    import stockscanner.market_data as market_data
    monkeypatch.setattr(market_data, "_cache_path", lambda symbol: str(tmp_path / f"{symbol}.csv"))
    df = download_data("AAPL")
    assert not df.empty
    assert calls["count"] == 3

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from stockscanner.ticker_universe_store import (
    TickerUniverseStoreError,
    load_latest_ticker_universe,
    refresh_ticker_universe,
    store_ticker_universe,
    ticker_records,
)


def sample_tickers():
    return pd.DataFrame(
        [
            {
                "Symbol": "bbb",
                "Security Name": "Beta Corp",
                "Exchange": "nyq",
                "Market Cap": 200,
            },
            {
                "Symbol": "AAA",
                "Security Name": "Alpha Corp",
                "Exchange": "NYQ",
                "Market Cap": 100,
            },
        ]
    )


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class QueueOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payloads.pop(0))


def test_ticker_records_normalizes_backend_payload():
    records = ticker_records(sample_tickers())

    assert records == [
        {
            "symbol": "BBB",
            "security_name": "Beta Corp",
            "exchange": "NYQ",
            "market_cap": 200,
        },
        {
            "symbol": "AAA",
            "security_name": "Alpha Corp",
            "exchange": "NYQ",
            "market_cap": 100,
        },
    ]


def test_ticker_records_rejects_invalid_symbols():
    tickers = sample_tickers()
    tickers.loc[0, "Symbol"] = "BAD SYMBOL"

    with pytest.raises(TickerUniverseStoreError, match="invalid symbols"):
        ticker_records(tickers)


def test_store_ticker_universe_uses_secret_only_as_apikey():
    refreshed_at = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    opener = QueueOpener(
        [[{"symbol_count": 2, "refreshed_at": refreshed_at.isoformat()}]]
    )

    stored = store_ticker_universe(
        sample_tickers(),
        supabase_url="https://example.supabase.co/",
        secret_key="sb_secret_test",
        refreshed_at=refreshed_at,
        opener=opener,
    )

    request, timeout = opener.requests[0]
    assert request.full_url.endswith("/rest/v1/rpc/replace_nyse_tickers")
    assert request.method == "POST"
    assert request.get_header("Apikey") == "sb_secret_test"
    assert request.get_header("Authorization") is None
    assert timeout == 30
    assert json.loads(request.data)["p_tickers"][0]["symbol"] == "BBB"
    assert stored["symbol_count"] == 2


def test_load_latest_ticker_universe_returns_expected_dataframe():
    refreshed_at = "2026-08-28T12:00:00+00:00"
    opener = QueueOpener(
        [
            [{"refreshed_at": refreshed_at, "source": "yahoo_screener"}],
            [
                {
                    "symbol": "BBB",
                    "security_name": "Beta Corp",
                    "exchange": "NYQ",
                    "market_cap": 200,
                    "refreshed_at": refreshed_at,
                },
                {
                    "symbol": "AAA",
                    "security_name": "Alpha Corp",
                    "exchange": "NYQ",
                    "market_cap": 100,
                    "refreshed_at": refreshed_at,
                },
            ],
        ]
    )

    frame = load_latest_ticker_universe(
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        opener=opener,
    )

    assert list(frame.columns) == [
        "Symbol",
        "Security Name",
        "Exchange",
        "Market Cap",
    ]
    assert frame["Symbol"].tolist() == ["BBB", "AAA"]
    assert opener.requests[1][0].get_header("Range") == "0-999"


def test_refresh_skips_before_8am_new_york_without_calling_supabase():
    opener = QueueOpener([])

    result = refresh_ticker_universe(
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        now=datetime(2026, 8, 28, 11, 59, tzinfo=timezone.utc),
        opener=opener,
    )

    assert result["reason"] == "before_schedule"
    assert opener.requests == []


def test_refresh_skips_when_current_new_york_date_is_already_stored():
    opener = QueueOpener(
        [[{"refreshed_at": "2026-08-28T12:00:00+00:00", "source": "yahoo_screener"}]]
    )

    result = refresh_ticker_universe(
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        now=datetime(2026, 8, 28, 13, tzinfo=timezone.utc),
        downloader=lambda: pytest.fail("download should have been skipped"),
        opener=opener,
    )

    assert result["reason"] == "already_refreshed"


def test_refresh_replaces_tickers_once_when_due():
    refreshed_at = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    opener = QueueOpener(
        [
            [],
            [{"symbol_count": 2, "refreshed_at": refreshed_at.isoformat()}],
        ]
    )

    result = refresh_ticker_universe(
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        now=refreshed_at,
        downloader=sample_tickers,
        opener=opener,
    )

    assert result == {
        "stored": True,
        "symbol_count": 2,
        "refreshed_at": refreshed_at.isoformat(),
    }


def test_refresh_preserves_downloader_fallback_source():
    refreshed_at = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    opener = QueueOpener(
        [
            [],
            [{"symbol_count": 2, "refreshed_at": refreshed_at.isoformat()}],
        ]
    )

    refresh_ticker_universe(
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        now=refreshed_at,
        downloader=lambda: (sample_tickers(), "nasdaqtrader"),
        opener=opener,
    )

    rpc_payload = json.loads(opener.requests[1][0].data)
    assert rpc_payload["p_source"] == "nasdaqtrader"


def test_refresh_preserves_current_list_when_all_downloads_fail():
    opener = QueueOpener([[]])

    with pytest.raises(TickerUniverseStoreError, match="current Supabase list was preserved"):
        refresh_ticker_universe(
            supabase_url="https://example.supabase.co",
            secret_key="sb_secret_test",
            now=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
            downloader=lambda: (_ for _ in ()).throw(RuntimeError("rate limited")),
            opener=opener,
        )

    assert len(opener.requests) == 1


def test_workflows_use_supabase_and_dst_safe_new_york_schedule():
    scan_workflow = open(".github/workflows/scan.yml", encoding="utf-8").read()
    ticker_workflow = open(
        ".github/workflows/ticker-universe.yml", encoding="utf-8"
    ).read()
    price_workflow = open(
        ".github/workflows/price-snapshot.yml", encoding="utf-8"
    ).read()

    assert "--universe-source supabase" in scan_workflow
    assert "--force-download" not in scan_workflow
    assert 'cron: "17 13,14 * * 1-5"' in scan_workflow
    assert "Check 9 AM New York schedule window" in scan_workflow
    assert 'default: "8"' in scan_workflow
    assert "git pull --rebase -X theirs origin main" in scan_workflow
    assert "git push origin HEAD:main" in scan_workflow
    assert "Unable to publish generated reports after 3 attempts" in scan_workflow
    assert 'cron: "7 12,13 * * 1-5"' in ticker_workflow
    assert "SUPABASE_SECRET_KEY" in ticker_workflow
    assert 'cron: "47 13-21 * * 1-5"' in price_workflow
    assert 'branches: [main]' in price_workflow
    assert '"stockscanner/price_snapshot.py"' in price_workflow


def test_migration_keeps_only_current_tickers_and_hourly_prices():
    migration = open(
        "supabase/migrations/20260828093000_store_latest_market_data.sql",
        encoding="utf-8",
    ).read()

    assert "delete from public.price_snapshots" in migration
    assert "check (source = 'hourly_yahoo')" in migration
    assert "create unique index price_snapshots_source_key" in migration
    assert "delete from public.nyse_tickers" in migration
    assert "where symbol is not null" in migration
    assert "create table public.nyse_ticker_downloads" not in migration

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stockscanner.supabase_store import MockSupabaseTransport, SupabaseRESTClient, SupabaseSnapshotStore


@pytest.fixture
def store():
    client = SupabaseRESTClient(
        url="https://example.supabase.co",
        key="test-key",
        transport=MockSupabaseTransport(),
    )
    return SupabaseSnapshotStore(client=client)


def test_seed_daily_universe_and_claim_release(store):
    created = store.seed_daily_universe(["AAPL", "MSFT", "AAPL"])
    assert len(created) == 2
    rows = store.client.select(
        "scan_tickers",
        filters=[("slot_key", "eq", created[0]["slot_key"])],
        select="*",
    )
    assert {row["ticker"] for row in rows} == {"AAPL", "MSFT"}

    claimed = store.claim_pending_tickers(created[0]["slot_key"], batch_size=1, claimed_by="worker-1")
    assert len(claimed) == 1
    assert claimed[0]["status"] == "claimed"
    assert claimed[0]["attempt_count"] == 1

    released = store.release_ticker(created[0]["slot_key"], claimed[0]["ticker"], reason="retry")
    assert released["status"] == "pending"
    assert released["claimed_by"] is None


def test_hourly_collection_resumes_missing_tickers_only(store):
    slot_key = "2024-05-01T15:00"
    store.client.insert("scan_tickers", [{
        "slot_key": slot_key,
        "ticker": "AAPL",
        "status": "collected",
        "attempt_count": 1,
        "created_at": "2024-05-01T15:00:00+00:00",
        "updated_at": "2024-05-01T15:00:00+00:00",
    }])
    store.client.insert("scan_tickers", [{
        "slot_key": slot_key,
        "ticker": "MSFT",
        "status": "pending",
        "attempt_count": 0,
        "created_at": "2024-05-01T15:00:00+00:00",
        "updated_at": "2024-05-01T15:00:00+00:00",
    }])

    result = store.collect_hourly_snapshot(
        slot_key,
        batch_size=10,
        downloader=lambda ticker: {"symbol": ticker, "price": 101.0 if ticker == "MSFT" else None},
    )

    assert result["status"] == "complete"
    assert result["collected"] == 1
    assert result["remaining"] == 0
    snapshot_rows = store.client.select("price_snapshots", filters=[("slot_key", "eq", slot_key)], select="*")
    assert {row["ticker"] for row in snapshot_rows} == {"MSFT"}


def test_collect_hourly_snapshot_reports_no_snapshot_when_everything_missing(store):
    slot_key = "2024-05-01T16:00"
    store.client.insert("scan_tickers", [{
        "slot_key": slot_key,
        "ticker": "AAPL",
        "status": "pending",
        "attempt_count": 0,
        "created_at": "2024-05-01T16:00:00+00:00",
        "updated_at": "2024-05-01T16:00:00+00:00",
    }])

    result = store.collect_hourly_snapshot(slot_key, batch_size=10, downloader=lambda ticker: None)
    assert result["status"] == "no_snapshot"
    assert result["collected"] == 0
    assert result["remaining"] == 1

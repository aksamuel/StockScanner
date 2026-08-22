import json

import pytest

from stockscanner.supabase_snapshot import (
    SupabaseSnapshotError,
    snapshot_record,
    store_snapshot,
)


def sample_payload():
    return {
        "generated_at": "2026-08-21T15:50:48-04:00",
        "price_timestamp": "2026-08-21T15:52:00-04:00",
        "timezone": "America/New_York",
        "source": "hourly_yahoo",
        "prices": {"AAA": 10.25, "BBB": 20.5},
        "updated_symbols": ["AAA"],
        "failures": {"BBB": "rate limited"},
    }


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_snapshot_record_derives_counts():
    record = snapshot_record(sample_payload())

    assert record["symbol_count"] == 2
    assert record["updated_count"] == 1
    assert record["failed_count"] == 1
    assert record["prices"] == {"AAA": 10.25, "BBB": 20.5}


def test_store_snapshot_uses_secret_key_only_as_apikey_header():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            json.dumps(
                [{"id": 7, "generated_at": sample_payload()["generated_at"]}]
            ).encode("utf-8")
        )

    stored = store_snapshot(
        sample_payload(),
        supabase_url="https://example.supabase.co/",
        secret_key="sb_secret_test",
        opener=opener,
    )

    request = captured["request"]
    assert request.full_url.endswith(
        "/rest/v1/price_snapshots?on_conflict=generated_at%2Csource"
    )
    assert request.get_header("Apikey") == "sb_secret_test"
    assert request.get_header("Authorization") is None
    assert json.loads(request.data) == snapshot_record(sample_payload())
    assert stored["id"] == 7


def test_store_snapshot_requires_backend_credentials():
    with pytest.raises(SupabaseSnapshotError, match="SUPABASE_SECRET_KEY"):
        store_snapshot(
            sample_payload(),
            supabase_url="https://example.supabase.co",
            secret_key="",
        )

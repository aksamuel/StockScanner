import json

import pytest

from stockscanner.price_run_state import (
    PriceRunStateError,
    acquire_slot,
    finish_slot,
)


class Response:
    def __init__(self, value):
        self.body = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_acquire_slot_uses_secret_apikey_and_rpc():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        return Response(True)

    assert acquire_slot(
        slot="2026-08-31:10",
        market_date="2026-08-31",
        workflow_run_id=42,
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        opener=opener,
    ) is True
    request = captured["request"]
    assert request.full_url.endswith("/rpc/acquire_price_collection_slot")
    assert request.get_header("Apikey") == "sb_secret_test"
    assert request.get_header("Authorization") is None


def test_finish_slot_validates_status():
    with pytest.raises(PriceRunStateError, match="completed or failed"):
        finish_slot(
            slot="2026-08-31:10",
            workflow_run_id=42,
            status="running",
            supabase_url="https://example.supabase.co",
            secret_key="sb_secret_test",
        )

import json

import pytest

from stockscanner.scanner_run_state import (
    ScannerRunStateError,
    acquire_daily_run,
    finish_daily_run,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_acquire_daily_run_uses_backend_rpc_and_secret_apikey():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(True)

    acquired = acquire_daily_run(
        market_date="2026-08-31",
        workflow_run_id=123,
        trigger_source="schedule",
        supabase_url="https://example.supabase.co/",
        secret_key="sb_secret_test",
        opener=opener,
    )

    request = captured["request"]
    assert acquired is True
    assert request.full_url.endswith("/rest/v1/rpc/acquire_daily_scanner_run")
    assert request.get_header("Apikey") == "sb_secret_test"
    assert request.get_header("Authorization") is None
    assert json.loads(request.data) == {
        "p_market_date": "2026-08-31",
        "p_workflow_run_id": 123,
        "p_trigger_source": "schedule",
        "p_force": False,
    }


def test_finish_daily_run_supports_legacy_service_role_jwt():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        return FakeResponse(True)

    finished = finish_daily_run(
        market_date="2026-08-31",
        workflow_run_id=123,
        status="failed",
        error="download failed",
        supabase_url="https://example.supabase.co",
        secret_key="legacy.jwt",
        opener=opener,
    )

    request = captured["request"]
    assert finished is True
    assert request.full_url.endswith("/rest/v1/rpc/finish_daily_scanner_run")
    assert request.get_header("Authorization") == "Bearer legacy.jwt"
    assert json.loads(request.data)["p_error"] == "download failed"


def test_finish_daily_run_rejects_invalid_status():
    with pytest.raises(ScannerRunStateError, match="completed or failed"):
        finish_daily_run(
            market_date="2026-08-31",
            workflow_run_id=123,
            status="running",
            supabase_url="https://example.supabase.co",
            secret_key="sb_secret_test",
        )


def test_run_state_requires_backend_credentials():
    with pytest.raises(ScannerRunStateError, match="SUPABASE_SECRET_KEY"):
        acquire_daily_run(
            market_date="2026-08-31",
            workflow_run_id=123,
            trigger_source="schedule",
            supabase_url="https://example.supabase.co",
            secret_key="",
        )

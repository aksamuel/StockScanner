import json
from pathlib import Path

from stockscanner.technical_signal_store import (
    publish_portfolio_technical_signals,
    technical_signal_attempt,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_signal_attempt_preserves_targets_and_failure_reason():
    success = technical_signal_attempt(
        "adbe",
        {
            "Score": 35,
            "Recommendation": "AVOID",
            "Current Price": 100,
            "Target 1": 110,
            "Resistance Low": 105,
            "Target Upside": 20,
        },
        "analysed",
    )
    failure = technical_signal_attempt("acmr", None, "download_failure")

    assert success == {
        "symbol": "ADBE",
        "success": True,
        "score": 35.0,
        "recommendation": "AVOID",
        "scanner_price": 100.0,
        "technical_target": 110.0,
        "resistance_target": 105.0,
        "analyst_target_upside": 20.0,
    }
    assert failure == {
        "symbol": "ACMR",
        "success": False,
        "failure_reason": "download_failure",
    }


def test_signal_store_calls_backend_only_rpc_without_legacy_auth_for_secret_key():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(2)

    attempts = [
        technical_signal_attempt("ADBE", {"Score": 80}),
        technical_signal_attempt("ACMR", None, "insufficient_history"),
    ]
    stored = publish_portfolio_technical_signals(
        attempts,
        market_date="2026-10-02",
        supabase_url="https://example.supabase.co",
        secret_key="sb_secret_test",
        opener=opener,
    )

    assert stored == 2
    request = requests[0][0]
    assert request.full_url.endswith("/rpc/record_portfolio_technical_signal_attempts")
    assert request.headers["Apikey"] == "sb_secret_test"
    assert "Authorization" not in request.headers
    body = json.loads(request.data)
    assert body["p_market_date"] == "2026-10-02"
    assert body["p_attempts"] == attempts


def test_migration_denies_direct_client_access_and_owner_scopes_reads():
    migration = (ROOT / "supabase/migrations/20261002000000_add_portfolio_technical_signals.sql").read_text(
        encoding="utf-8"
    )

    assert "enable row level security" in migration
    assert "revoke all on table public.portfolio_technical_signals from public, anon, authenticated" in migration
    assert "grant execute on function public.get_my_portfolio_technical_signals()" in migration
    assert "holding.user_id = auth.uid()" in migration
    assert "on conflict (symbol) do update" in migration
    assert "then 'unavailable'" in migration
    assert "else 'stale'" in migration
    failure_update = migration.split("else\n      insert into", 1)[1]
    assert "set market_date = excluded.market_date" not in failure_update

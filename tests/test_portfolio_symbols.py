import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from stockscanner.portfolio_symbols import (
    PortfolioSymbolError,
    load_portfolio_symbols,
    normalize_portfolio_symbols,
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

    def close(self):
        pass


def test_normalize_portfolio_symbols_deduplicates_share_classes():
    assert normalize_portfolio_symbols([" aapl ", "BRK B", "AAPL", None]) == [
        "AAPL",
        "BRK-B",
    ]


def test_load_portfolio_symbols_reads_only_symbols_and_paginates():
    requests = []
    batches = [
        [{"symbol": "AAPL"}, {"symbol": "BRK B"}],
        [{"symbol": "AAPL"}],
    ]

    def opener(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(batches.pop(0))

    symbols = load_portfolio_symbols(
        supabase_url="https://example.supabase.co/",
        secret_key="sb_secret_test",
        opener=opener,
        page_size=2,
    )

    assert symbols == ["AAPL", "BRK-B"]
    assert len(requests) == 2
    assert all("select=symbol" in request.full_url for request, _ in requests)
    assert all("user_id" not in request.full_url for request, _ in requests)
    assert requests[0][0].headers["Range"] == "0-1"
    assert requests[1][0].headers["Range"] == "2-3"
    assert requests[0][0].headers["Apikey"] == "sb_secret_test"
    assert "Authorization" not in requests[0][0].headers


def test_load_portfolio_symbols_supports_legacy_service_role_header():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return FakeResponse([])

    assert load_portfolio_symbols(
        supabase_url="https://example.supabase.co",
        secret_key="legacy.jwt",
        opener=opener,
    ) == []
    assert requests[0].headers["Authorization"] == "Bearer legacy.jwt"


def test_load_portfolio_symbols_reports_http_errors_without_exposing_key():
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            FakeResponse({"message": "invalid key"}),
        )

    with pytest.raises(PortfolioSymbolError, match="HTTP 401") as exc_info:
        load_portfolio_symbols(
            supabase_url="https://example.supabase.co",
            secret_key="sb_secret_never_log_this",
            opener=opener,
        )

    assert "sb_secret_never_log_this" not in str(exc_info.value)


def test_load_portfolio_symbols_rejects_invalid_symbols():
    with pytest.raises(PortfolioSymbolError, match="invalid ticker"):
        normalize_portfolio_symbols(["AAPL", "BAD/SYMBOL"])


def test_hourly_workflow_loads_portfolio_symbols_with_backend_secret():
    workflow = (ROOT / ".github/workflows/price-snapshot.yml").read_text(
        encoding="utf-8"
    )

    assert '- "stockscanner/portfolio_symbols.py"' in workflow
    refresh_step = workflow[workflow.index("- name: Refresh prices"):]
    assert "SUPABASE_URL:" in refresh_step
    assert "SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}" in refresh_step

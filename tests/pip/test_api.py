from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from stockscanner.pip.api import create_app
from stockscanner.pip.research import ResearchDataUnavailable


USER_ID = "33333333-3333-4333-8333-333333333333"


class FakeQuery:
    def __init__(self, table: str, access_status: str):
        self.table_name = table
        self.access_status = access_status

    def select(self, columns: str):
        return self

    def or_(self, expression: str):
        return self

    def eq(self, key: str, value: str):
        return self

    def maybe_single(self):
        return self

    def order(self, column: str, desc: bool = False):
        return self

    def execute(self):
        if self.table_name == "user_access":
            data = {"status": self.access_status}
        elif self.table_name == "portfolios":
            data = [{"id": "portfolio-1", "name": "Long term", "currency": "USD"}]
        else:
            data = []
        return SimpleNamespace(data=data, error=None)


class FakeClient:
    def __init__(self, access_status: str):
        self.access_status = access_status
        self.seen_token = None
        self.auth = SimpleNamespace(get_user=self.get_user)
        self.postgrest = SimpleNamespace(auth=self.set_token)

    def get_user(self, token: str):
        self.seen_token = token
        return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email="user@example.test"))

    def set_token(self, token: str):
        self.seen_token = token

    def table(self, table: str):
        return FakeQuery(table, self.access_status)


class PipelineQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.rows = None
        self.single_result = False

    def select(self, columns):
        return self

    def eq(self, key, value):
        return self

    def gte(self, key, value):
        return self

    def or_(self, expression):
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, count):
        return self

    def maybe_single(self):
        self.single_result = True
        return self

    def single(self):
        self.single_result = True
        return self

    def insert(self, rows):
        self.rows = rows if isinstance(rows, list) else [rows]
        self.client.writes.append((self.table_name, self.rows))
        return self

    def upsert(self, rows, on_conflict):
        self.rows = rows if isinstance(rows, list) else [rows]
        self.client.writes.append((self.table_name, self.rows))
        return self

    def execute(self):
        if self.rows is not None:
            data = self.rows
        elif self.table_name == "portfolios":
            data = {"id": self.client.portfolio_id}
        elif self.table_name == "positions":
            data = [{
                "quantity": "2",
                "average_cost": "100",
                "market_price": "120",
                "market_value": "240",
                "cost_basis": "200",
                "entry_date": "2025-01-01T00:00:00+00:00",
                "currency": "USD",
            }]
        elif self.table_name == "sell_recommendations":
            data = {
                "id": self.client.recommendation_id,
                "portfolio_id": self.client.portfolio_id,
                "status": "under_review",
            }
        elif self.table_name == "price_snapshots":
            data = [self.client.market_snapshot] if self.client.market_snapshot else []
        elif self.table_name == "user_access":
            data = {"status": "approved"}
        else:
            data = []
        if self.single_result and isinstance(data, list):
            data = data[0] if data else None
        return SimpleNamespace(data=data, error=None)


class PipelineClient(FakeClient):
    portfolio_id = "22222222-2222-4222-8222-222222222222"
    recommendation_id = "44444444-4444-4444-8444-444444444444"

    def __init__(self):
        super().__init__("approved")
        self.writes = []
        self.rpc_calls = []
        self.market_snapshot = {
            "generated_at": "2026-01-01T15:00:00Z",
            "prices": {"AAPL": 150.0},
            "price_timestamps": {"AAPL": "2026-01-01T14:59:00Z"},
            "provider_by_symbol": {"AAPL": "Yahoo"},
            "stale_symbols": [],
        }

    def table(self, table):
        return PipelineQuery(self, table)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=params["p_next_status"], error=None))


def _client(access_status: str = "approved"):
    fake = FakeClient(access_status)
    calls = []

    def factory(url: str, key: str):
        calls.append((url, key))
        return fake

    app = create_app(
        client_factory=factory,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
            "PIP_CORS_ORIGINS": "https://app.example.test",
        },
    )
    return TestClient(app), fake, calls


def test_pip_api_requires_a_bearer_token_before_accessing_portfolios():
    client, _, calls = _client()
    response = client.get("/api/pip/portfolios")
    assert response.status_code == 401
    assert calls == []


def test_pip_api_verifies_approved_user_and_uses_the_callers_token():
    client, fake, calls = _client()
    response = client.get(
        "/api/pip/portfolios",
        headers={"Authorization": "Bearer user-access-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Long term"
    assert calls == [("https://project.example.test", "public-test-key")]
    assert fake.seen_token == "user-access-token"


def test_pip_api_denies_accounts_without_approval():
    client, _, _ = _client("pending")
    response = client.get(
        "/api/pip/portfolios",
        headers={"Authorization": "Bearer user-access-token"},
    )
    assert response.status_code == 403


def test_pip_api_cors_is_restricted_to_configured_browser_origin():
    client, _, _ = _client()
    response = client.options(
        "/api/pip/portfolios",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.test"


def test_research_api_requires_an_imported_holding_and_uses_shared_price_snapshot():
    fake = PipelineClient()
    calls = []

    def fetch_research(symbol, *, market_snapshot):
        calls.append((symbol, market_snapshot))
        return {"symbol": symbol, "price": market_snapshot["prices"][symbol]}

    app = create_app(
        client_factory=lambda url, key: fake,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
        research_fetcher=fetch_research,
    )
    client = TestClient(app)
    response = client.post(
        f"/api/pip/portfolios/{fake.portfolio_id}/research",
        headers={"Authorization": "Bearer user-access-token"},
        json={"symbol": "aapl"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"symbol": "AAPL", "price": 150.0}
    assert calls == [("AAPL", fake.market_snapshot)]


def test_research_api_surfaces_provider_failure_without_success_fallback():
    fake = PipelineClient()

    def unavailable_research(_symbol, *, market_snapshot):
        raise ResearchDataUnavailable("No market research data was returned.")

    app = create_app(
        client_factory=lambda url, key: fake,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
        research_fetcher=unavailable_research,
    )
    response = TestClient(app).post(
        f"/api/pip/portfolios/{fake.portfolio_id}/research",
        headers={"Authorization": "Bearer user-access-token"},
        json={"symbol": "AAPL"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "No market research data was returned."


def test_analysis_api_runs_modules_and_persists_score_and_proposed_recommendation():
    fake = PipelineClient()
    app = create_app(
        client_factory=lambda url, key: fake,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
    )
    client = TestClient(app)
    response = client.post(
        "/api/pip/analysis",
        headers={"Authorization": "Bearer user-access-token"},
        json={
            "portfolio_id": fake.portfolio_id,
            "symbol": "aapl",
            "position": {"market_price": 130, "dividends_received": 12},
            "dividends": {
                "records": [
                    {"symbol": "AAPL", "amount": 40, "pay_date": date.today().isoformat()},
                ],
            },
            "scores": {
                "tsr": 70,
                "relative_performance": 65,
                "dividend_growth": 60,
                "earnings_growth": 70,
                "analyst_revisions": 55,
                "revisions": 55,
                "dividend_quality": 60,
                "technical_health": 65,
                "opportunity_cost": 40,
            },
            "growth": {
                "earnings_growth_percent": 10,
                "revenue_growth_percent": 8,
            },
            "forward": {"target_price": 143, "analyst_revisions_score": 80},
            "peer_scores": [{"symbol": "MSFT", "score": 90}],
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["recommendation"]["status"] == "proposed"
    assert {
        "lifecycle",
        "dead_money",
        "dividends",
        "growth",
        "forward_looking",
        "opportunity_cost",
    } == set(result["modules"])
    assert {"stock_scores", "sell_recommendations", "daily_snapshots"} <= {
        table for table, _ in fake.writes
    }
    assert "analyst_signals" in {table for table, _ in fake.writes}
    assert result["modules"]["growth"]["confidence"] == 1
    assert abs(result["modules"]["dividends"]["current_yield_pct"] - (40 / 260 * 100)) < 1e-9
    assert abs(result["modules"]["lifecycle"]["total_return_percent"] - 36) < 1e-9
    assert result["modules"]["forward_looking"]["score"] == 68
    assert result["recommendation"]["replacement_candidates"][0]["symbol"] == "MSFT"
    assert fake.rpc_calls[0][0] == "pip_transition_sell_recommendation"
    assert fake.rpc_calls[0][1]["p_expected_status"] is None


def test_analysis_api_skips_opportunity_cost_without_current_cps():
    fake = PipelineClient()
    app = create_app(
        client_factory=lambda url, key: fake,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
    )
    response = TestClient(app).post(
        "/api/pip/analysis",
        headers={"Authorization": "******"},
        json={
            "portfolio_id": fake.portfolio_id,
            "symbol": "AAPL",
            "position": {"market_price": 130},
            "peer_scores": [{"symbol": "MSFT", "score": 90}],
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["modules"]["opportunity_cost"] == []
    assert result["recommendation"]["replacement_candidates"] == []


def test_approval_api_persists_authenticated_human_transition_through_atomic_rpc():
    fake = PipelineClient()
    app = create_app(
        client_factory=lambda url, key: fake,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
    )
    response = TestClient(app).post(
        f"/api/pip/recommendations/{fake.recommendation_id}/transitions",
        headers={"Authorization": "Bearer api-test-token"},
        json={"status": "approved", "actor": "Portfolio owner", "reason": "Reviewed the evidence."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert fake.rpc_calls == [
        (
            "pip_transition_sell_recommendation",
            {
                "p_recommendation_id": fake.recommendation_id,
                "p_expected_status": "under_review",
                "p_next_status": "approved",
                "p_actor": "Portfolio owner",
                "p_reason": "Reviewed the evidence.",
            },
        )
    ]

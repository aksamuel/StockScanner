"""The research route: who may call it, which rows it reads, and what it hands to the research fetcher."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

from stockscanner.pip.api import create_app

USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_USER_ID = "88888888-8888-4888-8888-888888888888"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
SECOND_PORTFOLIO_ID = "66666666-6666-4666-8666-666666666666"
FOREIGN_PORTFOLIO_ID = "77777777-7777-4777-8777-777777777777"
MISSING_PORTFOLIO_ID = "99999999-9999-4999-8999-999999999999"
TOKEN = "user-access-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
SNAPSHOT_COLUMNS = ["generated_at", "prices", "price_timestamps", "provider_by_symbol", "stale_symbols"]

TABLE_COLUMNS = {
    "user_access": {"user_id", "status"},
    "portfolios": {"id", "user_id", "name", "currency", "created_at", "updated_at"},
    "positions": {
        "id", "portfolio_id", "account_id", "symbol", "quantity", "average_cost", "market_price",
        "market_value", "cost_basis", "currency", "source_key", "entry_date", "last_updated",
        "metadata", "created_at", "updated_at",
    },
    "price_snapshots": {
        "id", "generated_at", "price_timestamp", "timezone", "source", "symbol_count", "updated_count",
        "failed_count", "prices", "failures", "created_at", "price_timestamps", "provider_by_symbol",
        "stale_symbols",
    },
}


class Query:
    """Models PostgREST reads: equality filters, ordering and a row limit.

    A write, and any table the research route has no business reading, fails the test.
    """

    def __init__(self, client, table):
        if table not in TABLE_COLUMNS:
            raise AssertionError(f"The research route must not read {table}.")
        self.client = client
        self.table_name = table
        self.columns = None
        self.filters = {}
        self.orderings = []
        self.max_rows = None
        self.single_result = False

    def select(self, columns):
        self.columns = [column.strip() for column in columns.split(",")]
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, column, desc=False):
        self.orderings.append((column, desc))
        return self

    def limit(self, count):
        self.max_rows = count
        return self

    def maybe_single(self):
        self.single_result = True
        return self

    def _refuse_write(self, *args, **kwargs):
        raise AssertionError("The research route must not write.")

    insert = upsert = update = delete = _refuse_write

    def execute(self):
        requested = set(self.columns or []) | set(self.filters) | {column for column, _ in self.orderings}
        missing = sorted(requested - TABLE_COLUMNS[self.table_name])
        if missing:
            raise APIError({"message": f"column {missing[0]} does not exist", "code": "42703"})

        rows = [
            row
            for row in self.client.data[self.table_name]
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        for column, desc in reversed(self.orderings):
            rows.sort(key=lambda row, column=column: row[column], reverse=desc)
        if self.max_rows is not None:
            rows = rows[:self.max_rows]

        self.client.reads.append({
            "table": self.table_name,
            "filters": dict(self.filters),
            "columns": self.columns,
        })
        data = [{column: row.get(column) for column in self.columns} for row in rows]
        if self.single_result:
            return SimpleNamespace(data=data[0], error=None) if data else None
        return SimpleNamespace(data=data, error=None)


def _snapshot(source, generated_at, price):
    return {
        "source": source,
        "generated_at": generated_at,
        "prices": {"AAA": price},
        "price_timestamps": {"AAA": generated_at},
        "provider_by_symbol": {"AAA": "Yahoo"},
        "stale_symbols": [],
    }


class Client:
    def __init__(self, *, access_status="approved"):
        self.reads = []
        self.seen_tokens = []
        self.auth = SimpleNamespace(get_user=self._get_user)
        self.postgrest = SimpleNamespace(auth=self.seen_tokens.append)
        self.data = {
            "user_access": [{"user_id": USER_ID, "status": access_status}] if access_status else [],
            "portfolios": [
                {"id": PORTFOLIO_ID, "user_id": USER_ID},
                {"id": SECOND_PORTFOLIO_ID, "user_id": USER_ID},
                {"id": FOREIGN_PORTFOLIO_ID, "user_id": OTHER_USER_ID},
            ],
            "positions": [
                {"id": "pos-1", "portfolio_id": PORTFOLIO_ID, "symbol": "AAA"},
                {"id": "pos-2", "portfolio_id": SECOND_PORTFOLIO_ID, "symbol": "BBB"},
                {"id": "pos-3", "portfolio_id": FOREIGN_PORTFOLIO_ID, "symbol": "LEAK"},
            ],
            "price_snapshots": [
                _snapshot("hourly_yahoo", "2026-01-01T10:00:00Z", 100.0),
                _snapshot("hourly_yahoo", "2026-01-01T15:00:00Z", 150.0),
                _snapshot("manual", "2026-01-02T09:00:00Z", 999.0),
            ],
        }

    def _get_user(self, token):
        if token != TOKEN:
            raise AuthApiError("Invalid token", 401, "bad_jwt")
        return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email="user@example.test"))

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        raise AssertionError("The research route must not call database functions.")

    def read_tables(self):
        return [read["table"] for read in self.reads]


def _fetcher(calls):
    def fetch(symbol, *, market_snapshot):
        calls.append((symbol, market_snapshot))
        price = market_snapshot["prices"][symbol] if market_snapshot else None
        return {"symbol": symbol, "price": price}

    return fetch


def _research(client, calls, symbol="AAA", portfolio_id=PORTFOLIO_ID, headers=AUTH):
    app = create_app(
        client_factory=lambda url, key: client,
        environ={
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
        },
        research_fetcher=_fetcher(calls),
    )
    return TestClient(app).post(
        f"/api/pip/portfolios/{portfolio_id}/research",
        headers=headers,
        json={"symbol": symbol},
    )


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer " + "another-token"}],
    ids=["no header", "not a bearer token", "token Supabase rejects"],
)
def test_research_needs_a_valid_sign_in(headers):
    fake, calls = Client(), []

    response = _research(fake, calls, headers=headers)

    assert response.status_code == 401
    assert fake.reads == []
    assert calls == []


@pytest.mark.parametrize("access_status", ["pending", "rejected", None])
def test_research_is_refused_to_an_account_that_is_not_approved(access_status):
    fake, calls = Client(access_status=access_status), []

    response = _research(fake, calls)

    assert response.status_code == 403
    assert fake.read_tables() == ["user_access"]
    assert calls == []


@pytest.mark.parametrize("portfolio_id", [FOREIGN_PORTFOLIO_ID, MISSING_PORTFOLIO_ID])
def test_research_for_a_portfolio_that_is_not_the_callers_is_reported_as_not_found(portfolio_id):
    fake, calls = Client(), []

    response = _research(fake, calls, symbol="LEAK", portfolio_id=portfolio_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Portfolio not found."}
    assert fake.read_tables() == ["user_access", "portfolios"]
    assert fake.reads[-1]["filters"] == {"id": portfolio_id, "user_id": USER_ID}
    assert calls == []


@pytest.mark.parametrize(
    "symbol",
    ["BBB", "LEAK", "ZZZ"],
    ids=["held in the caller's other portfolio", "held in another user's portfolio", "held by nobody"],
)
def test_research_is_refused_for_a_symbol_the_selected_portfolio_does_not_hold(symbol):
    fake, calls = Client(), []

    response = _research(fake, calls, symbol=symbol)

    assert response.status_code == 422
    assert response.json() == {"detail": "Import this holding into the selected portfolio before loading research."}
    assert fake.read_tables() == ["user_access", "portfolios", "positions"]
    assert fake.reads[-1]["filters"] == {"portfolio_id": PORTFOLIO_ID, "symbol": symbol}
    assert calls == []


def test_research_hands_the_fetcher_only_the_symbol_and_the_latest_hourly_yahoo_snapshot():
    fake, calls = Client(), []

    response = _research(fake, calls, symbol="aaa")

    assert response.status_code == 200, response.text
    assert response.json() == {"symbol": "AAA", "price": 150.0}
    assert calls == [("AAA", {
        "generated_at": "2026-01-01T15:00:00Z",
        "prices": {"AAA": 150.0},
        "price_timestamps": {"AAA": "2026-01-01T15:00:00Z"},
        "provider_by_symbol": {"AAA": "Yahoo"},
        "stale_symbols": [],
    })]
    assert fake.read_tables() == ["user_access", "portfolios", "positions", "price_snapshots"]
    assert fake.reads[-1]["filters"] == {"source": "hourly_yahoo"}
    assert fake.reads[-1]["columns"] == SNAPSHOT_COLUMNS


def test_research_passes_no_snapshot_when_there_is_no_hourly_yahoo_row():
    fake, calls = Client(), []
    fake.data["price_snapshots"] = [row for row in fake.data["price_snapshots"] if row["source"] != "hourly_yahoo"]

    response = _research(fake, calls)

    assert response.status_code == 200, response.text
    assert calls == [("AAA", None)]


def test_a_data_service_failure_while_checking_the_holding_is_reported_without_leaking_details(monkeypatch):
    fake, calls = Client(), []
    original = Query.execute

    def failing(self):
        if self.table_name == "positions":
            raise APIError({"message": "permission denied for table positions", "code": "42501"})
        return original(self)

    monkeypatch.setattr(Query, "execute", failing)

    response = _research(fake, calls)

    assert response.status_code == 502
    assert response.json() == {"detail": "The PIP data service request failed."}
    assert calls == []


@pytest.mark.parametrize(
    ("table", "detail"),
    [
        ("positions", "Unable to verify the selected holding."),
        ("price_snapshots", "Unable to load the shared market-price snapshot."),
    ],
)
def test_a_data_service_error_result_stops_the_research_in_plain_language(monkeypatch, table, detail):
    fake, calls = Client(), []
    original = Query.execute

    def erroring(self):
        if self.table_name == table:
            return SimpleNamespace(data=None, error="relation is unavailable")
        return original(self)

    monkeypatch.setattr(Query, "execute", erroring)

    response = _research(fake, calls)

    assert response.status_code == 502
    assert response.json() == {"detail": detail}
    assert calls == []

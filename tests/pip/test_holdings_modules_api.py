from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

import stockscanner.pip.api as pip_api
from stockscanner.pip.api import REVIEW_MAX_PAGES, REVIEW_PAGE_SIZE, create_app
from stockscanner.pip.holdings import FLAG_MESSAGES, HOLDINGS_NOTES, TRUNCATED_NOTE
from stockscanner.pip.position_lifecycle import PositionLifecycleAnalyzer
from stockscanner.pip.scoring import CPS_WEIGHTS, SELL_SCORE_WEIGHTS


USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_USER_ID = "88888888-8888-4888-8888-888888888888"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
FOREIGN_PORTFOLIO_ID = "77777777-7777-4777-8777-777777777777"
TOKEN = "user-access-token"
AUTH = {"Authorization": "Bearer " + TOKEN}

MODULES = (
    "lifecycle",
    "hurdle",
    "dead_money",
    "dividends",
    "growth",
    "forward_looking",
    "opportunity_cost",
    "cps",
    "sell_score",
    "replacements",
    "sell_advisor",
)
SECRETS = ("acct-secret", "ibkr:secret-key", "fp-secret")
HOLDINGS_COLUMNS = [
    "symbol", "quantity", "average_cost", "market_price", "market_value",
    "cost_basis", "entry_date", "currency", "last_updated",
]

TABLE_COLUMNS = {
    "user_access": {"user_id", "status"},
    "portfolios": {"id", "user_id", "name", "currency", "created_at", "updated_at"},
    "positions": {
        "id", "portfolio_id", "account_id", "symbol", "quantity", "average_cost",
        "market_price", "market_value", "cost_basis", "currency", "source_key",
        "entry_date", "last_updated", "metadata", "created_at", "updated_at",
    },
    "stock_scores": {
        "id", "portfolio_id", "symbol", "cps", "sell_score", "tsr", "relative_performance",
        "dividend_growth", "earnings_growth", "analyst_revisions", "dividend_quality",
        "technical_health", "opportunity_cost", "revisions", "calculated_at", "metadata",
        "created_at", "updated_at",
    },
    "analyst_signals": {
        "id", "portfolio_id", "symbol", "analyst_rating", "target_price", "target_upside",
        "revisions", "signal_date", "metadata", "created_at", "updated_at",
    },
    "dividends": {
        "id", "portfolio_id", "symbol", "dividend_amount", "ex_date", "pay_date",
        "source_key", "metadata", "created_at", "updated_at",
    },
}


class Query:
    """Models PostgREST reads: filters, ordering, windows and the server row cap.

    Any write, and any table these routes have no business reading, fails the test.
    """

    def __init__(self, client, table):
        if table not in TABLE_COLUMNS:
            raise AssertionError(f"These routes must not read {table}.")
        self.client = client
        self.table_name = table
        self.columns = None
        self.filters = {}
        self.alternatives = []
        self.orderings = []
        self.window = None
        self.max_rows = None
        self.single_result = False

    def select(self, columns):
        self.columns = [column.strip() for column in columns.split(",")]
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def or_(self, expression):
        clauses = []
        for clause in expression.split(","):
            column, operator, value = clause.split(".", 2)
            if operator != "gte":
                raise AssertionError(f"Unsupported filter operator {operator}.")
            clauses.append((column, value))
        self.alternatives.append(clauses)
        return self

    def order(self, column, desc=False):
        self.orderings.append((column, desc))
        return self

    def limit(self, count):
        self.max_rows = count
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def maybe_single(self):
        self.single_result = True
        return self

    def _refuse_write(self, *args, **kwargs):
        raise AssertionError("These routes must not write.")

    insert = upsert = update = delete = _refuse_write

    def execute(self):
        known = TABLE_COLUMNS[self.table_name]
        requested = (
            set(self.columns or [])
            | set(self.filters)
            | {column for column, _ in self.orderings}
            | {column for clauses in self.alternatives for column, _ in clauses}
        )
        missing = sorted(requested - known)
        if missing:
            raise APIError({"message": f"column {missing[0]} does not exist", "code": "42703"})

        rows = [
            row
            for row in self.client.data[self.table_name]
            if all(row.get(key) == value for key, value in self.filters.items())
            and all(
                any(
                    row.get(column) is not None and str(row[column]) >= value
                    for column, value in clauses
                )
                for clauses in self.alternatives
            )
        ]
        for column, desc in reversed(self.orderings):
            rows.sort(key=lambda row, column=column: row[column], reverse=desc)
        if self.window is not None:
            rows = rows[self.window[0]:self.window[1] + 1]
        if self.max_rows is not None:
            rows = rows[:self.max_rows]
        rows = rows[:self.client.server_row_cap]

        self.client.reads.append({
            "table": self.table_name,
            "filters": dict(self.filters),
            "alternatives": [list(clauses) for clauses in self.alternatives],
            "columns": self.columns,
            "orderings": list(self.orderings),
            "window": self.window,
            "limit": self.max_rows,
        })
        data = [{column: row.get(column) for column in self.columns} for row in rows]
        if self.single_result:
            return SimpleNamespace(data=data[0], error=None) if data else None
        return SimpleNamespace(data=data, error=None)


class Client:
    def __init__(self, *, access_status="approved", server_row_cap=1_000):
        self.server_row_cap = server_row_cap
        self.reads = []
        self.seen_tokens = []
        self.auth = SimpleNamespace(get_user=self._get_user)
        self.postgrest = SimpleNamespace(auth=self.seen_tokens.append)
        self.data = {
            "user_access": (
                [{"user_id": USER_ID, "status": access_status}] if access_status else []
            ),
            "portfolios": [
                {"id": PORTFOLIO_ID, "user_id": USER_ID},
                {"id": FOREIGN_PORTFOLIO_ID, "user_id": OTHER_USER_ID},
            ],
            "positions": [],
            "stock_scores": [],
            "analyst_signals": [],
            "dividends": [],
        }

    def _get_user(self, token):
        if token != TOKEN:
            raise AuthApiError("Invalid token", 401, "bad_jwt")
        return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email="user@example.test"))

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        raise AssertionError("These routes must not call database functions.")

    def add_positions(self, rows, portfolio_id=PORTFOLIO_ID):
        start = len(self.data["positions"])
        self.data["positions"].extend(
            {"id": f"pos-{start + index:06d}", "portfolio_id": portfolio_id, **row}
            for index, row in enumerate(rows)
        )

    def read_tables(self):
        return [read["table"] for read in self.reads]

    def portfolio_reads(self):
        return [read for read in self.reads if read["table"] not in {"user_access", "portfolios"}]


class FixedClockLifecycle(PositionLifecycleAnalyzer):
    """Pins "today" to 2027-01-01 so holding days do not drift with the calendar."""

    def __init__(self):
        super().__init__()
        self.snapshot_time = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _lot(
    symbol,
    cost,
    value,
    entry="2025-01-01",
    quantity=10,
    currency="USD",
    updated="2026-12-31T12:00:00+00:00",
):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "average_cost": cost / quantity if quantity else None,
        "market_price": value / quantity if quantity and value is not None else None,
        "market_value": value,
        "cost_basis": cost,
        "entry_date": f"{entry}T00:00:00+00:00" if entry else None,
        "currency": currency,
        "last_updated": updated,
        "account_id": "acct-secret",
        "source_key": "ibkr:secret-key",
        "metadata": {"account_fingerprint": "fp-secret"},
    }


def _dividend(symbol, amount, paid, portfolio_id=PORTFOLIO_ID, currency=None):
    return {
        "id": f"dividend-{symbol}-{paid}-{portfolio_id}",
        "portfolio_id": portfolio_id,
        "symbol": symbol,
        "dividend_amount": amount,
        "ex_date": None,
        "pay_date": paid.isoformat(),
        "metadata": {"currency": currency} if currency else {},
    }


def _signal(symbol, signal_date, target_price=None, target_upside=None, revisions=None):
    return {
        "id": f"signal-{symbol}-{signal_date}",
        "portfolio_id": PORTFOLIO_ID,
        "symbol": symbol,
        "signal_date": signal_date,
        "target_price": target_price,
        "target_upside": target_upside,
        "revisions": revisions,
    }


def _stored_score(symbol, portfolio_id=PORTFOLIO_ID, **scores):
    row = {
        "id": f"score-{symbol}",
        "portfolio_id": portfolio_id,
        "symbol": symbol,
        "tsr": None,
        "relative_performance": None,
        "dividend_growth": None,
        "earnings_growth": None,
        "analyst_revisions": None,
        "dividend_quality": None,
        "technical_health": None,
        "opportunity_cost": None,
        "revisions": None,
    }
    row.update(scores)
    return row


def _app(monkeypatch, fake):
    monkeypatch.setattr(pip_api, "PositionLifecycleAnalyzer", FixedClockLifecycle)
    return TestClient(
        create_app(
            client_factory=lambda url, key: fake,
            environ={
                "SUPABASE_URL": "https://project.example.test",
                "SUPABASE_PUBLISHABLE_KEY": "public-test-key",
            },
        )
    )


def _holdings(client, portfolio_id=PORTFOLIO_ID, headers=AUTH):
    return client.get(f"/api/pip/portfolios/{portfolio_id}/positions", headers=headers)


def _run(client, module, body=None, portfolio_id=PORTFOLIO_ID, headers=AUTH):
    return client.post(
        f"/api/pip/portfolios/{portfolio_id}/modules/{module}",
        headers=headers,
        json={"symbol": "AAA"} if body is None else body,
    )


def _result(client, module, body=None):
    response = _run(client, module, body)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _standard_portfolio(fake):
    fake.add_positions([
        _lot("AAA", 1000, 1100),  # 730 days, +10% against a 14.49% hurdle path
        _lot("BBB", 100, 60),
        _lot("CCC", 100, 130),
    ])


def _all_scores(value):
    return {
        "tsr": value,
        "relative_performance": value,
        "dividend_growth": value,
        "earnings_growth": value,
        "analyst_revisions": value,
        "revisions": value,
        "dividend_quality": value,
        "technical_health": value,
        "opportunity_cost": value,
    }


def _cps_scores(value):
    return {
        "tsr": value,
        "relative_performance": value,
        "dividend_growth": value,
        "earnings_growth": value,
        "analyst_revisions": value,
    }


def _today():
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- #
# Access control, shared by both routes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda client, **kwargs: _holdings(client, **kwargs), id="holdings"),
        pytest.param(lambda client, **kwargs: _run(client, "lifecycle", **kwargs), id="module"),
    ],
)
def test_both_routes_are_protected_by_the_same_account_checks_as_the_other_routes(monkeypatch, call):
    anonymous = Client()
    assert call(_app(monkeypatch, anonymous), headers={}).status_code == 401
    assert anonymous.reads == []

    not_bearer = Client()
    assert call(_app(monkeypatch, not_bearer), headers={"Authorization": "Basic abc"}).status_code == 401
    assert not_bearer.reads == []

    bad_token = Client()
    rejected = call(_app(monkeypatch, bad_token), headers={"Authorization": "Bearer expired-token"})
    assert rejected.status_code == 401
    assert bad_token.reads == []


@pytest.mark.parametrize("access_status", ["pending", "rejected", None])
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda client: _holdings(client), id="holdings"),
        pytest.param(lambda client: _run(client, "lifecycle"), id="module"),
    ],
)
def test_an_unapproved_account_cannot_use_either_route(monkeypatch, call, access_status):
    fake = Client(access_status=access_status)
    _standard_portfolio(fake)

    response = call(_app(monkeypatch, fake))

    assert response.status_code == 403
    assert fake.read_tables() == ["user_access"]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda client, portfolio_id: _holdings(client, portfolio_id), id="holdings"),
        pytest.param(
            lambda client, portfolio_id: _run(client, "lifecycle", {"symbol": "LEAK"}, portfolio_id),
            id="module",
        ),
    ],
)
def test_another_users_portfolio_is_reported_as_not_found(monkeypatch, call):
    fake = Client()
    fake.add_positions([_lot("LEAK", 100, 10)], portfolio_id=FOREIGN_PORTFOLIO_ID)

    response = call(_app(monkeypatch, fake), FOREIGN_PORTFOLIO_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Portfolio not found."}
    assert "LEAK" not in response.text
    assert fake.read_tables() == ["user_access", "portfolios"]
    assert fake.portfolio_reads() == []
    assert fake.seen_tokens == [TOKEN]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda client, portfolio_id: _holdings(client, portfolio_id), id="holdings"),
        pytest.param(lambda client, portfolio_id: _run(client, "lifecycle", None, portfolio_id), id="module"),
    ],
)
def test_a_missing_portfolio_is_reported_as_not_found(monkeypatch, call):
    fake = Client()

    response = call(_app(monkeypatch, fake), "99999999-9999-4999-8999-999999999999")

    assert response.status_code == 404
    assert fake.portfolio_reads() == []


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda client, portfolio_id: _holdings(client, portfolio_id), id="holdings"),
        pytest.param(lambda client, portfolio_id: _run(client, "lifecycle", None, portfolio_id), id="module"),
    ],
)
def test_a_malformed_portfolio_id_is_rejected_before_any_data_is_read(monkeypatch, call):
    fake = Client()
    _standard_portfolio(fake)

    response = call(_app(monkeypatch, fake), "not-a-uuid")

    assert response.status_code == 422
    assert fake.portfolio_reads() == []
    assert "portfolios" not in fake.read_tables()


# --------------------------------------------------------------------------- #
# Holdings list
# --------------------------------------------------------------------------- #


def test_the_holdings_list_reads_only_the_callers_portfolio_and_never_writes(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    fake.add_positions([_lot("LEAK", 100, 10)], portfolio_id=FOREIGN_PORTFOLIO_ID)
    before = copy.deepcopy(fake.data)

    response = _holdings(_app(monkeypatch, fake))

    assert response.status_code == 200
    assert [holding["symbol"] for holding in response.json()["holdings"]] == ["AAA", "BBB", "CCC"]
    assert "LEAK" not in response.text
    assert fake.data == before
    assert fake.seen_tokens == [TOKEN]
    assert fake.portfolio_reads() == [{
        "table": "positions",
        "filters": {"portfolio_id": PORTFOLIO_ID},
        "alternatives": [],
        "columns": HOLDINGS_COLUMNS,
        "orderings": [("id", False)],
        "window": (0, REVIEW_PAGE_SIZE - 1),
        "limit": None,
    }]


def test_holdings_are_grouped_by_symbol_with_unconverted_per_currency_totals(monkeypatch):
    fake = Client()
    fake.add_positions([
        _lot("AAA", 100, 120, entry="2024-05-01"),
        _lot("AAA", 100, 90, entry="2025-02-01"),
        _lot("BBB", 100, 60),
        _lot("CCC", 50, 55, currency="CAD"),
        _lot("DDD", 80, None),
        _lot("EEE", 10, 10, quantity=0),
    ])

    response = _holdings(_app(monkeypatch, fake))

    body = response.json()
    holdings = {holding["symbol"]: holding for holding in body["holdings"]}
    assert sorted(holdings) == ["AAA", "BBB", "CCC", "DDD"]
    aaa = holdings["AAA"]
    assert (aaa["quantity"], aaa["lot_count"], aaa["cost_basis"], aaa["market_value"]) == (20, 2, 200, 210)
    assert aaa["price_return_percent"] == pytest.approx(5.0)
    assert aaa["entry_date"] == "2024-05-01"
    assert aaa["days_held"] == (_today() - datetime(2024, 5, 1).date()).days
    assert holdings["BBB"]["price_return_percent"] == pytest.approx(-40.0)
    assert holdings["CCC"]["currency"] == "CAD"
    assert body["lots"] == 5
    assert body["totals"] == [
        {
            "currency": "CAD", "holdings": 1, "market_value": 55, "priced_holdings": 1,
            "cost_basis": 50, "costed_holdings": 1,
        },
        {
            "currency": "USD", "holdings": 3, "market_value": 270, "priced_holdings": 2,
            "cost_basis": 380, "costed_holdings": 3,
        },
    ]
    assert body["as_of"] == "2026-12-31T12:00:00+00:00"
    assert body["truncated"] is False
    assert body["notes"] == list(HOLDINGS_NOTES)


def test_holdings_that_cannot_be_valued_are_flagged_not_filled_in(monkeypatch):
    fake = Client()
    fake.add_positions([
        _lot("AAA", 100, None),
        _lot("MIX", 100, 110),
        _lot("MIX", 100, 110, currency="CAD"),
        _lot("NODATE", 100, 110, entry=None),
    ])

    body = _holdings(_app(monkeypatch, fake)).json()

    holdings = {holding["symbol"]: holding for holding in body["holdings"]}
    assert holdings["AAA"]["market_value"] is None
    assert holdings["AAA"]["price_return_percent"] is None
    assert holdings["AAA"]["flags"] == ["missing_market_value"]
    assert holdings["MIX"]["currency"] is None
    assert holdings["MIX"]["market_value"] is None
    assert holdings["MIX"]["flags"] == ["mixed_currency"]
    assert holdings["NODATE"]["flags"] == ["missing_entry_date"]
    assert holdings["NODATE"]["days_held"] is None
    assert {item["flag"]: item["count"] for item in body["flags"]} == {
        "mixed_currency": 1,
        "missing_entry_date": 1,
        "missing_market_value": 1,
    }
    assert all(item["message"] == FLAG_MESSAGES[item["flag"]] for item in body["flags"])
    assert body["totals"] == [{
        "currency": "USD", "holdings": 2, "market_value": 110, "priced_holdings": 1,
        "cost_basis": 200, "costed_holdings": 2,
    }]


def test_holding_time_counts_from_the_earliest_lot(monkeypatch):
    fake = Client()
    fake.add_positions([
        _lot("AAA", 100, 100, entry="2025-06-01"),
        _lot("AAA", 100, 100, entry="2023-03-15"),
    ])

    holding = _holdings(_app(monkeypatch, fake)).json()["holdings"][0]

    assert holding["entry_date"] == "2023-03-15"
    assert holding["days_held"] == (_today() - datetime(2023, 3, 15).date()).days


def test_an_empty_portfolio_lists_no_holdings(monkeypatch):
    fake = Client()

    response = _holdings(_app(monkeypatch, fake))

    assert response.status_code == 200
    assert response.json() == {
        "as_of": None,
        "lots": 0,
        "holdings": [],
        "totals": [],
        "flags": [],
        "truncated": False,
        "notes": list(HOLDINGS_NOTES),
    }


def test_every_page_of_a_large_portfolio_is_listed(monkeypatch):
    fake = Client()
    fake.add_positions([_lot(f"S{index:04d}", 100, 110) for index in range(2_300)])

    body = _holdings(_app(monkeypatch, fake)).json()

    assert len(body["holdings"]) == 2_300
    assert body["truncated"] is False
    assert [read["window"] for read in fake.portfolio_reads()] == [
        (0, 999), (1_000, 1_999), (2_000, 2_999),
    ]


def test_a_portfolio_that_fills_the_page_boundary_exactly_is_listed_completely(monkeypatch):
    fake = Client()
    fake.add_positions([_lot(f"S{index:04d}", 100, 110) for index in range(REVIEW_PAGE_SIZE)])

    body = _holdings(_app(monkeypatch, fake)).json()

    assert len(body["holdings"]) == REVIEW_PAGE_SIZE
    assert body["truncated"] is False
    assert len(fake.portfolio_reads()) == 2


def test_a_list_stops_at_the_page_ceiling_and_says_so(monkeypatch):
    fake = Client()
    fake.add_positions(
        [_lot(f"S{index:05d}", 100, 110) for index in range(REVIEW_MAX_PAGES * REVIEW_PAGE_SIZE + 50)]
    )

    body = _holdings(_app(monkeypatch, fake)).json()

    assert body["truncated"] is True
    assert TRUNCATED_NOTE in body["notes"]
    assert len(body["holdings"]) == REVIEW_MAX_PAGES * REVIEW_PAGE_SIZE
    assert len(fake.portfolio_reads()) == REVIEW_MAX_PAGES


def test_a_data_service_failure_is_reported_without_leaking_details(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    original = Query.execute

    def failing(self):
        if self.table_name == "positions":
            raise APIError({"message": "permission denied for table positions", "code": "42501"})
        return original(self)

    monkeypatch.setattr(Query, "execute", failing)

    response = _holdings(_app(monkeypatch, fake))

    assert response.status_code == 502
    assert response.json() == {"detail": "The PIP data service request failed."}
    assert "positions" not in response.text


def test_a_data_service_error_result_is_reported_in_plain_language(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    original = Query.execute

    def erroring(self):
        if self.table_name == "positions":
            return SimpleNamespace(data=None, error="relation positions is unavailable")
        return original(self)

    monkeypatch.setattr(Query, "execute", erroring)

    response = _holdings(_app(monkeypatch, fake))

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to load portfolio positions."}


def test_the_holdings_response_contains_no_account_identifiers(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    response = _holdings(_app(monkeypatch, fake))

    for forbidden in (
        USER_ID, PORTFOLIO_ID, TOKEN, *SECRETS,
        "user_id", "portfolio_id", "account", "source_key", "metadata",
    ):
        assert forbidden not in response.text


def test_health_reports_the_holdings_and_module_capabilities(monkeypatch):
    health = _app(monkeypatch, Client()).get("/healthz").json()

    assert health["positions_list"] == 1
    assert health["module_runner"] == 1


# --------------------------------------------------------------------------- #
# Module runner: request handling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["nope", "analysis", "review", "CPS", "sell-score", "Lifecycle"])
def test_an_unknown_module_is_rejected_before_any_portfolio_data_is_read(monkeypatch, module):
    fake = Client()
    _standard_portfolio(fake)

    response = _run(_app(monkeypatch, fake), module)

    assert response.status_code == 422
    assert fake.portfolio_reads() == []
    assert "portfolios" not in fake.read_tables()


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"symbol": ""},
        {"symbol": "bad symbol!"},
        {"symbol": "AAA", "unknown": 1},
        {"symbol": "AAA", "portfolio_id": PORTFOLIO_ID},
        {"symbol": "AAA", "scores": {"tsr": 100.5}},
        {"symbol": "AAA", "scores": {"tsr": -1}},
        {"symbol": "AAA", "scores": {"tsr": "high"}},
        {"symbol": "AAA", "scores": {"unknown_score": 50}},
        {"symbol": "AAA", "dividends": {"current_price": 0}},
        {"symbol": "AAA", "dividends": {"records": [{"symbol": "AAA"}]}},
        {"symbol": "AAA", "forward": {"analyst_revisions_score": 101}},
        {"symbol": "AAA", "forward": {"target_price": -5}},
        {"symbol": "AAA", "hurdle": {"required_annual_return_percent": 100.5}},
        {"symbol": "AAA", "hurdle": {"required_annual_return_percent": -1}},
        {"symbol": "AAA", "peer_scores": [{"symbol": "bad symbol", "score": 50}]},
        {"symbol": "AAA", "peer_scores": [{"symbol": "NEW1"}]},
        {"symbol": "AAA", "peer_scores": "NEW1:50"},
        {"symbol": "AAA", "peer_scores": [{"symbol": f"S{index}", "score": 50} for index in range(501)]},
        {"symbol": "AAA", "position": {"market_price": 0}},
        {"symbol": "AAA", "position": {"entry_date": "yesterday"}},
    ],
)
def test_an_invalid_module_request_is_rejected_before_any_portfolio_data_is_read(monkeypatch, body):
    fake = Client()
    _standard_portfolio(fake)

    response = _run(_app(monkeypatch, fake), "lifecycle", body)

    assert response.status_code == 422
    assert fake.portfolio_reads() == []
    assert "portfolios" not in fake.read_tables()


def test_a_holding_that_is_not_in_the_portfolio_is_explained_in_plain_language(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    fake.add_positions([_lot("LEAK", 100, 10)], portfolio_id=FOREIGN_PORTFOLIO_ID)

    response = _run(_app(monkeypatch, fake), "lifecycle", {"symbol": "LEAK"})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Import this holding into the selected portfolio before analyzing it."
    }


def test_a_holding_in_more_than_one_currency_is_not_analyzed(monkeypatch):
    fake = Client()
    fake.add_positions([_lot("AAA", 100, 110), _lot("AAA", 100, 110, currency="CAD")])

    response = _run(_app(monkeypatch, fake), "hurdle")

    assert response.status_code == 422
    assert "one currency at a time" in response.json()["detail"]


def test_dividends_in_another_currency_are_refused(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    supplied = _run(
        _app(monkeypatch, fake),
        "dividends",
        {"symbol": "AAA", "dividends": {"records": [
            {"symbol": "AAA", "amount": 1.0, "pay_date": _today().isoformat(), "currency": "CAD"},
        ]}},
    )
    fake.data["dividends"].append(_dividend("AAA", 1.0, _today(), currency="EUR"))
    stored = _run(_app(monkeypatch, fake), "dividends")

    for response in (supplied, stored):
        assert response.status_code == 422
        assert "holding's currency" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Module runner: nothing is saved
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", MODULES)
def test_a_module_run_reads_only_the_callers_data_and_saves_nothing(monkeypatch, module):
    fake = Client()
    _standard_portfolio(fake)
    fake.data["stock_scores"].append(_stored_score("AAA", tsr=40, relative_performance=40))
    fake.data["analyst_signals"].append(_signal("AAA", "2026-06-01T00:00:00+00:00", target_upside=12))
    fake.data["dividends"].append(_dividend("AAA", 2.0, _today() - timedelta(days=20)))
    before = copy.deepcopy(fake.data)

    response = _run(
        _app(monkeypatch, fake),
        module,
        {
            "symbol": "aaa",
            "scores": {"opportunity_cost": 70},
            "peer_scores": [{"symbol": "NEW1", "score": 90}],
            "candidate_cps": {"NEW1": 85},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["module"] == module
    assert body["symbol"] == "AAA"
    assert body["currency"] == "USD"
    assert body["saved"] is False
    assert isinstance(body["result"], dict)
    assert fake.data == before
    assert fake.seen_tokens == [TOKEN]
    assert fake.portfolio_reads()
    assert all(
        read["filters"].get("portfolio_id") == PORTFOLIO_ID for read in fake.portfolio_reads()
    )
    assert set(fake.read_tables()) <= {
        "user_access", "portfolios", "positions", "stock_scores", "analyst_signals", "dividends",
    }


@pytest.mark.parametrize("module", MODULES)
def test_a_module_run_response_contains_no_account_identifiers(monkeypatch, module):
    fake = Client()
    _standard_portfolio(fake)

    response = _run(
        _app(monkeypatch, fake),
        module,
        {"symbol": "AAA", "scores": _all_scores(50), "peer_scores": [{"symbol": "NEW1", "score": 90}]},
    )

    assert response.status_code == 200
    for forbidden in (USER_ID, PORTFOLIO_ID, TOKEN, *SECRETS, "user_id", "portfolio_id", "account"):
        assert forbidden not in response.text


# --------------------------------------------------------------------------- #
# Module runner: each module's result
# --------------------------------------------------------------------------- #


def test_the_lifecycle_module_reports_holding_time_and_price_return(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "lifecycle")

    assert result["symbol"] == "AAA"
    assert result["days_held"] == 730
    assert result["price_return_percent"] == pytest.approx(10.0)
    assert result["total_return_percent"] is None


def test_dividends_received_make_the_lifecycle_return_a_total_return(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "lifecycle",
        {"symbol": "AAA", "position": {"dividends_received": 50}},
    )

    assert result["price_return_percent"] == pytest.approx(10.0)
    assert result["total_return_percent"] == pytest.approx(15.0)


def test_the_hurdle_module_compares_the_holding_with_the_required_return_path(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "hurdle",
        {"symbol": "AAA", "position": {"dividends_received": 0}},
    )

    assert result["status"] == "below"
    assert result["return_basis"] == "total"
    assert result["required_annual_return_percent"] == 7.0
    assert result["return_percent"] == pytest.approx(10.0)
    assert result["hurdle_return_percent"] == pytest.approx(14.49)
    assert result["days_held"] == 730
    assert result["shortfall_amount"] > 0


def test_the_hurdle_verdict_waits_for_dividends_received(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "hurdle")

    assert result["status"] == "unavailable"
    assert result["return_basis"] == "price_only"
    assert result["return_percent"] == pytest.approx(10.0)
    assert result["hurdle_return_percent"] == pytest.approx(14.49)
    assert any("enter dividends received (0 if none)" in reason for reason in result["reasons"])


def test_a_lower_required_return_changes_the_hurdle_verdict(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "hurdle",
        {
            "symbol": "AAA",
            "position": {"dividends_received": 0},
            "hurdle": {"required_annual_return_percent": 4},
        },
    )

    assert result["status"] == "meets"
    assert result["required_annual_return_percent"] == 4.0


def test_a_holding_held_under_a_year_is_not_judged_against_the_hurdle(monkeypatch):
    fake = Client()
    fake.add_positions([_lot("AAA", 1000, 900, entry="2026-06-01")])

    result = _result(_app(monkeypatch, fake), "hurdle")

    assert result["status"] == "unavailable"
    assert result["days_held"] == 214


def test_the_dead_money_verdict_is_withheld_when_there_is_nothing_to_judge(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "dead_money")

    assert result["is_dead_money"] is None
    assert result["confidence"] == 0
    assert result["reasons"] == ["No lifecycle or productivity data is available."]


def test_the_dead_money_verdict_is_withheld_when_only_the_hurdle_is_known(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "dead_money",
        {"symbol": "AAA", "position": {"dividends_received": 0}},
    )

    assert result["is_dead_money"] is None
    assert any("no productivity or outlook evidence" in reason for reason in result["reasons"])


def test_the_dead_money_module_flags_a_weak_holding_below_the_hurdle(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "dead_money",
        {"symbol": "AAA", "scores": _cps_scores(20), "position": {"dividends_received": 0}},
    )

    assert result["is_dead_money"] is True
    assert any("CPS is below" in reason for reason in result["reasons"])
    assert any("hurdle path" in reason for reason in result["reasons"])


def test_a_weak_cps_alone_does_not_confirm_dead_money(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "dead_money",
        {"symbol": "AAA", "scores": _cps_scores(20)},
    )

    assert result["is_dead_money"] is False
    assert any("CPS is below" in reason for reason in result["reasons"])


def test_a_strong_holding_that_meets_the_hurdle_is_not_dead_money(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "dead_money",
        {"symbol": "CCC", "scores": _cps_scores(80), "position": {"dividends_received": 0}},
    )

    assert result["is_dead_money"] is False
    assert any("meets the 7% per year hurdle path" in reason for reason in result["reasons"])


def test_the_dividends_module_uses_only_the_trailing_twelve_months_of_saved_dividends(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    today = _today()
    cutoff = (today - timedelta(days=365)).isoformat()
    fake.data["dividends"] = [
        _dividend("AAA", 1.5, today - timedelta(days=30)),
        _dividend("AAA", 1.5, today - timedelta(days=200)),
        _dividend("AAA", 9.0, today - timedelta(days=400)),
        _dividend("BBB", 7.0, today - timedelta(days=10)),
        _dividend("AAA", 5.0, today - timedelta(days=10), portfolio_id=FOREIGN_PORTFOLIO_ID),
    ]

    result = _result(_app(monkeypatch, fake), "dividends")

    assert result["trailing_twelve_month_income"] == pytest.approx(3.0)
    assert result["current_yield_pct"] == pytest.approx(3.0 / 1100 * 100)
    assert result["confidence"] == pytest.approx(0.30)
    assert "annualized_income" not in result
    dividend_reads = [read for read in fake.reads if read["table"] == "dividends"]
    assert dividend_reads == [{
        "table": "dividends",
        "filters": {"portfolio_id": PORTFOLIO_ID, "symbol": "AAA"},
        "alternatives": [[("pay_date", cutoff), ("ex_date", cutoff)]],
        "columns": ["symbol", "dividend_amount", "ex_date", "pay_date", "metadata"],
        "orderings": [],
        "window": None,
        "limit": 2_000,
    }]


def test_supplied_dividend_records_replace_the_saved_ones(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    fake.data["dividends"].append(_dividend("AAA", 99.0, _today() - timedelta(days=5)))
    old = (_today() - timedelta(days=500)).isoformat()
    recent = (_today() - timedelta(days=60)).isoformat()

    result = _result(
        _app(monkeypatch, fake),
        "dividends",
        {"symbol": "AAA", "dividends": {"records": [
            {"symbol": "AAA", "amount": 2.0, "pay_date": recent},
            {"symbol": "AAA", "amount": 8.0, "pay_date": old},
        ]}},
    )

    assert result["trailing_twelve_month_income"] == pytest.approx(2.0)
    assert "dividends" not in fake.read_tables()


def test_the_dividends_module_says_what_it_could_not_measure(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "dividends")

    assert result["trailing_twelve_month_income"] is None
    assert result["current_yield_pct"] is None
    assert result["dividend_quality_score"] is None
    assert result["confidence"] == 0
    assert "dividend yield data is missing or invalid." in result["reasons"]


def test_the_growth_module_scores_supplied_growth_rates(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    both = _result(
        _app(monkeypatch, fake),
        "growth",
        {"symbol": "AAA", "growth": {"earnings_growth_percent": 20, "revenue_growth_percent": 10}},
    )
    one = _result(
        _app(monkeypatch, fake),
        "growth",
        {"symbol": "AAA", "growth": {"earnings_growth_percent": 20}},
    )
    none = _result(_app(monkeypatch, fake), "growth")

    assert both["score"] == pytest.approx(87.5)
    assert both["confidence"] == 1.0
    assert one["score"] == pytest.approx(100.0)
    assert one["confidence"] == 0.5
    assert none["score"] is None
    assert none["confidence"] == 0.0
    assert none["reasons"] == ["Earnings and revenue growth data are missing."]


def test_the_growth_module_names_the_inputs_its_score_used(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    app = _app(monkeypatch, fake)

    both = _result(app, "growth", {"symbol": "AAA", "growth": {"earnings_growth_percent": 20, "revenue_growth_percent": 10}})
    earnings = _result(app, "growth", {"symbol": "AAA", "growth": {"earnings_growth_percent": 20}})
    revenue = _result(app, "growth", {"symbol": "AAA", "growth": {"revenue_growth_percent": 20}})
    none = _result(app, "growth")

    assert [item["basis"] for item in (both, earnings, revenue, none)] == [
        "earnings_and_revenue", "earnings_only", "revenue_only", "none",
    ]
    assert earnings["reasons"] == [
        "Revenue growth data is missing; the score uses earnings growth only and confidence is reduced."
    ]
    assert revenue["reasons"] == [
        "Earnings growth data is missing; the score uses revenue growth only and confidence is reduced."
    ]


@pytest.mark.parametrize("module", ["cps", "sell_score"])
def test_a_score_that_borrows_revenue_growth_says_so(monkeypatch, module):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        module,
        {"symbol": "AAA", "growth": {"revenue_growth_percent": 10}},
    )

    assert result["component_scores"] == {"earnings_growth": 75.0}
    assert result["earnings_growth_input"] == {"source": "growth_analysis", "basis": "revenue_only"}


@pytest.mark.parametrize(
    ("saved", "body", "expected_score", "expected_input"),
    [
        (
            None,
            {"scores": {"earnings_growth": 40}, "growth": {"revenue_growth_percent": 10}},
            40,
            {"source": "request", "basis": None},
        ),
        (
            30,
            {"growth": {"revenue_growth_percent": 10}},
            30,
            {"source": "saved_score", "basis": None},
        ),
        (
            None,
            {"growth": {"earnings_growth_percent": 20, "revenue_growth_percent": 10}},
            87.5,
            {"source": "growth_analysis", "basis": "earnings_and_revenue"},
        ),
        (
            None,
            {"growth": {"earnings_growth_percent": 20}},
            100.0,
            {"source": "growth_analysis", "basis": "earnings_only"},
        ),
        (None, {}, None, {"source": "unavailable", "basis": None}),
    ],
    ids=["request", "saved-score", "earnings-and-revenue", "earnings-only", "unavailable"],
)
def test_the_earnings_growth_input_reports_where_it_came_from(
    monkeypatch, saved, body, expected_score, expected_input
):
    fake = Client()
    _standard_portfolio(fake)
    if saved is not None:
        fake.data["stock_scores"].append(_stored_score("AAA", earnings_growth=saved))

    result = _result(_app(monkeypatch, fake), "cps", {"symbol": "AAA", **body})

    assert result["component_scores"].get("earnings_growth") == expected_score
    assert result["earnings_growth_input"] == expected_input


def test_the_forward_looking_module_uses_supplied_outlook_inputs(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "forward_looking",
        {"symbol": "AAA", "forward": {"target_upside_percent": 20, "analyst_revisions_score": 60}},
    )

    assert result["score"] == pytest.approx(66.0)
    assert result["confidence"] == 1.0


def test_a_target_price_is_turned_into_upside_against_the_saved_price(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "forward_looking",
        {"symbol": "AAA", "forward": {"target_price": 121}},
    )

    assert result["score"] == pytest.approx(60.0)
    assert result["confidence"] == pytest.approx(0.6)


def test_the_latest_saved_analyst_signal_supplies_the_outlook(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    fake.data["analyst_signals"] = [
        _signal("AAA", "2026-01-01T00:00:00+00:00", target_upside=-30, revisions=5),
        _signal("AAA", "2026-06-01T00:00:00+00:00", target_upside=20, revisions=60),
    ]

    result = _result(_app(monkeypatch, fake), "forward_looking")

    assert result["score"] == pytest.approx(66.0)
    signal_reads = [read for read in fake.reads if read["table"] == "analyst_signals"]
    assert [(read["orderings"], read["limit"]) for read in signal_reads] == [
        ([("signal_date", True)], 1)
    ]


def test_the_forward_looking_module_says_what_is_missing(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "forward_looking")

    assert result["score"] is None
    assert result["confidence"] == 0.0
    assert "Target Upside data is missing." in result["reasons"]
    assert "Analyst Revisions data is missing." in result["reasons"]


def test_the_cps_module_reports_the_weights_and_the_missing_components(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "cps",
        {"symbol": "AAA", "scores": {"tsr": 80, "relative_performance": 40}},
    )

    assert result["score"] == pytest.approx((40 * 80 + 20 * 40) / 60)
    assert result["confidence"] == pytest.approx(60 / 100)
    assert result["component_scores"] == {"tsr": 80, "relative_performance": 40}
    assert result["weights"] == CPS_WEIGHTS
    assert result["missing_components"] == ["dividend_growth", "earnings_growth", "analyst_revisions"]
    assert "Dividend Growth data is missing." in result["reasons"]


def test_the_cps_module_withholds_a_score_when_there_are_no_inputs(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(_app(monkeypatch, fake), "cps")

    assert result["score"] is None
    assert result["confidence"] == 0.0
    assert result["component_scores"] == {}
    assert result["missing_components"] == list(CPS_WEIGHTS)


def test_saved_scores_fill_in_what_the_request_leaves_out_but_never_override_it(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    fake.data["stock_scores"].append(_stored_score("AAA", tsr=30, relative_performance=60))

    result = _result(
        _app(monkeypatch, fake),
        "cps",
        {"symbol": "AAA", "scores": {"tsr": 90}},
    )

    assert result["component_scores"] == {"tsr": 90, "relative_performance": 60}


def test_the_sell_score_module_reports_the_documented_weights(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "sell_score",
        {"symbol": "AAA", "scores": {"tsr": 100}},
    )

    assert result["score"] == pytest.approx(100.0)
    assert result["confidence"] == pytest.approx(20 / 115)
    assert result["weights"] == SELL_SCORE_WEIGHTS
    assert result["missing_components"] == [
        "relative_performance", "revisions", "dividend_quality",
        "technical_health", "earnings_growth", "opportunity_cost",
    ]

    complete = _result(
        _app(monkeypatch, fake),
        "sell_score",
        {"symbol": "AAA", "scores": _all_scores(50)},
    )
    assert complete["score"] == pytest.approx(50.0)
    assert complete["confidence"] == 1.0
    assert complete["missing_components"] == []


def test_the_opportunity_cost_module_needs_a_cps_and_candidates(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    without_cps = _result(
        _app(monkeypatch, fake),
        "opportunity_cost",
        {"symbol": "AAA", "peer_scores": [{"symbol": "NEW1", "score": 80}]},
    )
    without_candidates = _result(
        _app(monkeypatch, fake),
        "opportunity_cost",
        {"symbol": "AAA", "scores": _cps_scores(20)},
    )

    assert without_cps == {
        "available": False,
        "items": [],
        "reasons": ["Current holding CPS is unavailable."],
    }
    assert without_candidates == {
        "available": True,
        "items": [],
        "reasons": ["No replacement candidate scores were supplied."],
    }


def test_building_the_opportunity_cost_result_leaves_the_evaluation_untouched():
    assessment = {"available": True, "items": [], "reasons": []}
    evaluation = SimpleNamespace(module_assessments={"opportunity_cost": assessment})

    result = pip_api._module_result(
        "opportunity_cost", PORTFOLIO_ID, pip_api.HoldingInputs(symbol="AAA"), evaluation
    )

    assert result == {
        "available": True,
        "items": [],
        "reasons": ["No replacement candidate scores were supplied."],
    }
    assert result is not assessment
    assert assessment == {"available": True, "items": [], "reasons": []}


def test_the_opportunity_cost_module_compares_supplied_candidates_with_the_cps(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "opportunity_cost",
        {
            "symbol": "AAA",
            "scores": _cps_scores(20),
            "peer_scores": [{"symbol": "NEW1", "score": 80}, {"symbol": "NEW2", "score": 40}],
        },
    )

    assert result["available"] is True
    assert result["reasons"] == []
    assert [item["alternative_symbol"] for item in result["items"]] == ["NEW1", "NEW2"]
    assert result["items"][0]["expected_benefit"] == pytest.approx(30.0)
    assert result["items"][1]["expected_benefit"] == pytest.approx(10.0)


def test_the_replacements_module_explains_why_it_could_not_compare(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    no_candidates = _result(
        _app(monkeypatch, fake),
        "replacements",
        {"symbol": "AAA", "scores": _cps_scores(20)},
    )
    no_cps = _result(
        _app(monkeypatch, fake),
        "replacements",
        {"symbol": "AAA", "peer_scores": [{"symbol": "NEW1", "score": 80}]},
    )

    assert no_candidates == {
        "compared": False,
        "reasons": ["No replacement candidate scores were supplied."],
        "candidates": [],
    }
    assert no_cps["compared"] is False
    assert no_cps["candidates"] == []
    assert no_cps["reasons"] == [
        "This holding's CPS is unavailable, so candidates cannot be compared with it."
    ]


def test_the_replacements_module_lists_only_candidates_that_beat_the_holdings_cps(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "replacements",
        {
            "symbol": "AAA",
            "scores": _cps_scores(20),
            "peer_scores": [
                {"symbol": "NEW1", "score": 80},
                {"symbol": "NEW2", "score": 10},
                {"symbol": "BBB", "score": 99},
                {"symbol": "AAA", "score": 99},
                {"symbol": "ZZZ", "score": 99},
            ],
            "candidate_cps": {"NEW1": 70},
            "held_symbols": ["zzz"],
        },
    )

    assert result["compared"] is True
    assert result["reasons"] == []
    assert [candidate["symbol"] for candidate in result["candidates"]] == ["NEW1"]
    assert result["candidates"][0]["score"] == pytest.approx(75.0)


def test_replacements_are_ranked_against_the_cps_not_the_sell_score(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)
    scores = {
        **_cps_scores(60),
        "revisions": 10,
        "dividend_quality": 10,
        "technical_health": 10,
        "opportunity_cost": 10,
    }
    below = {
        "symbol": "AAA",
        "scores": scores,
        "peer_scores": [{"symbol": "NEW1", "score": 62}],
        "candidate_cps": {"NEW1": 55},
    }
    above = {**below, "candidate_cps": {"NEW1": 90}}

    sell_score = _result(_app(monkeypatch, fake), "sell_score", below)["score"]
    weaker = _result(_app(monkeypatch, fake), "replacements", below)
    stronger = _result(_app(monkeypatch, fake), "replacements", above)

    assert sell_score < 40
    assert weaker["compared"] is True
    assert weaker["candidates"] == []
    assert weaker["reasons"] == ["No supplied candidate scores are above this holding's CPS."]
    assert [candidate["symbol"] for candidate in stronger["candidates"]] == ["NEW1"]


def test_the_sell_advisor_module_returns_a_recommendation_with_its_reasons(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    strong = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {
            "symbol": "AAA",
            "scores": _all_scores(95),
            "peer_scores": [{"symbol": "NEW1", "score": 99}],
        },
    )
    weak = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {"symbol": "AAA", "scores": _all_scores(10)},
    )

    assert strong["recommendation"] == "sell"
    assert strong["sell_score"] == pytest.approx(95.0)
    assert strong["cps"] == pytest.approx(95.0)
    assert "Sell score is strong enough to justify exit or replacement review." in strong["rationale"]
    assert weak["recommendation"] == "watch"
    assert "Capital productivity score is weak enough to warrant a close review." in weak["rationale"]


def test_advice_confidence_reflects_input_coverage_not_the_strength_of_the_signal(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    weak = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {"symbol": "AAA", "scores": _all_scores(10)},
    )
    strong = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {"symbol": "AAA", "scores": _all_scores(95)},
    )
    partial = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {"symbol": "AAA", "scores": {"tsr": 95}},
    )

    assert weak["sell_score"] < 20
    assert weak["confidence"] == 1.0
    assert strong["confidence"] == 1.0
    assert partial["sell_score"] == pytest.approx(95.0)
    assert partial["confidence"] == pytest.approx(20 / 115)
    assert partial["recommendation"] == "watch"
    assert "Available data is insufficient for a confident sell recommendation." in partial["rationale"]


def test_the_sell_advisor_lists_replacement_candidates_that_beat_the_cps(monkeypatch):
    fake = Client()
    _standard_portfolio(fake)

    result = _result(
        _app(monkeypatch, fake),
        "sell_advisor",
        {
            "symbol": "AAA",
            "scores": _cps_scores(20),
            "peer_scores": [{"symbol": "NEW1", "score": 80}, {"symbol": "BBB", "score": 99}],
        },
    )

    assert [candidate["symbol"] for candidate in result["replacement_candidates"]] == ["NEW1"]
    assert any(
        reason.startswith("Stronger replacement candidates are available: NEW1")
        for reason in result["rationale"]
    )

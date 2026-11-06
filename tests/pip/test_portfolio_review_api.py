from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

import stockscanner.pip.api as pip_api
from stockscanner.pip.api import create_app
from stockscanner.pip.portfolio_review import TRUNCATED_NOTE
from stockscanner.pip.position_lifecycle import PositionLifecycleAnalyzer


USER_ID = "33333333-3333-4333-8333-333333333333"
OTHER_USER_ID = "88888888-8888-4888-8888-888888888888"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
FOREIGN_PORTFOLIO_ID = "77777777-7777-4777-8777-777777777777"
TOKEN = "user-access-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
REVIEW_URL = f"/api/pip/portfolios/{PORTFOLIO_ID}/review"

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
}


class ReviewQuery:
    """Models PostgREST reads: filters, ordering, windows and the server row cap.

    Any write, and any table the review has no business reading, fails the test.
    """

    def __init__(self, client, table):
        if table not in TABLE_COLUMNS:
            raise AssertionError(f"The portfolio review must not read {table}.")
        self.client = client
        self.table_name = table
        self.columns = None
        self.filters = {}
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
        raise AssertionError("The portfolio review must not write.")

    insert = upsert = update = delete = _refuse_write

    def execute(self):
        known = TABLE_COLUMNS[self.table_name]
        requested = set(self.columns or []) | set(self.filters) | {c for c, _ in self.orderings}
        missing = sorted(requested - known)
        if missing:
            raise APIError({"message": f"column {missing[0]} does not exist", "code": "42703"})

        rows = [
            row
            for row in self.client.data[self.table_name]
            if all(row.get(key) == value for key, value in self.filters.items())
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
            "columns": self.columns,
            "orderings": list(self.orderings),
            "window": self.window,
            "limit": self.max_rows,
        })
        data = [{column: row.get(column) for column in self.columns} for row in rows]
        if self.single_result:
            return SimpleNamespace(data=data[0], error=None) if data else None
        return SimpleNamespace(data=data, error=None)


class ReviewClient:
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
        }

    def _get_user(self, token):
        if token != TOKEN:
            raise AuthApiError("Invalid token", 401, "bad_jwt")
        return SimpleNamespace(user=SimpleNamespace(id=USER_ID, email="user@example.test"))

    def table(self, name):
        return ReviewQuery(self, name)

    def rpc(self, name, params):
        raise AssertionError("The portfolio review must not call database functions.")

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


def _position(symbol, cost, value, entry="2025-01-01", quantity=10, currency="USD"):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "average_cost": cost / quantity if quantity else None,
        "market_price": value / quantity if quantity else None,
        "market_value": value,
        "cost_basis": cost,
        "entry_date": f"{entry}T00:00:00+00:00" if entry else None,
        "currency": currency,
    }


def _score(symbol, cps=None, opportunity_cost=None, portfolio_id=PORTFOLIO_ID):
    return {
        "id": f"score-{symbol}",
        "portfolio_id": portfolio_id,
        "symbol": symbol,
        "cps": cps,
        "opportunity_cost": opportunity_cost,
    }


def _signal(symbol, signal_date, target_price=None, target_upside=None):
    return {
        "id": f"signal-{symbol}-{signal_date}",
        "portfolio_id": PORTFOLIO_ID,
        "symbol": symbol,
        "signal_date": signal_date,
        "target_price": target_price,
        "target_upside": target_upside,
    }


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


def _review(client, body=None, portfolio_id=PORTFOLIO_ID, headers=AUTH):
    return client.post(
        f"/api/pip/portfolios/{portfolio_id}/review",
        headers=headers,
        json=body if body is not None else {},
    )


def _standard_portfolio(fake):
    fake.add_positions([
        _position("AAA", 100, 110),  # 730 days, +10% against a 14.49% path
        _position("BBB", 100, 60),  # 730 days, -40%
        _position("CCC", 100, 130),  # 730 days, +30%: ahead of the path
        _position("DDD", 100, 80, entry="2026-06-01"),  # 214 days: too recent to judge
        _position("EEE", 100, 90, entry="2024-01-01"),  # 1096 days, -10%
    ])


def test_the_review_is_protected_by_the_same_account_checks_as_the_other_routes(monkeypatch):
    unauthenticated = ReviewClient()
    anonymous = _review(_app(monkeypatch, unauthenticated), headers={})
    assert anonymous.status_code == 401
    assert unauthenticated.reads == []

    not_bearer = ReviewClient()
    assert _review(_app(monkeypatch, not_bearer), headers={"Authorization": "Basic abc"}).status_code == 401
    assert not_bearer.reads == []

    bad_token = ReviewClient()
    rejected = _review(
        _app(monkeypatch, bad_token),
        headers={"Authorization": "Bearer " + "expired-token"},
    )
    assert rejected.status_code == 401
    assert bad_token.reads == []


@pytest.mark.parametrize("access_status", ["pending", "rejected", None])
def test_an_unapproved_account_cannot_review_a_portfolio(monkeypatch, access_status):
    fake = ReviewClient(access_status=access_status)
    _standard_portfolio(fake)

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 403
    assert fake.read_tables() == ["user_access"]


def test_another_users_portfolio_is_reported_as_not_found(monkeypatch):
    fake = ReviewClient()
    fake.add_positions([_position("LEAK", 100, 10)], portfolio_id=FOREIGN_PORTFOLIO_ID)

    response = _review(_app(monkeypatch, fake), portfolio_id=FOREIGN_PORTFOLIO_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Portfolio not found."}
    assert "LEAK" not in response.text
    assert fake.read_tables() == ["user_access", "portfolios"]
    assert fake.portfolio_reads() == []
    assert fake.seen_tokens == [TOKEN]


def test_a_missing_portfolio_is_reported_as_not_found(monkeypatch):
    fake = ReviewClient()

    response = _review(
        _app(monkeypatch, fake),
        portfolio_id="99999999-9999-4999-8999-999999999999",
    )

    assert response.status_code == 404
    assert fake.portfolio_reads() == []


def test_a_malformed_portfolio_id_is_rejected_before_any_data_is_read(monkeypatch):
    fake = ReviewClient()

    response = _review(_app(monkeypatch, fake), portfolio_id="not-a-uuid")

    assert response.status_code == 422
    assert fake.portfolio_reads() == []


@pytest.mark.parametrize(
    "body",
    [
        {"required_annual_return_percent": -0.1},
        {"required_annual_return_percent": 100.1},
        {"required_annual_return_percent": "seven"},
        {"required_annual_return_percent": None},
        {"top_n": 0},
        {"top_n": 21},
        {"top_n": 2.5},
        {"replacement_limit": 0},
        {"replacement_limit": 11},
        {"peer_scores": [{"symbol": "NEW1", "score": 100.5}]},
        {"peer_scores": [{"symbol": "NEW1", "score": -1}]},
        {"peer_scores": [{"symbol": "not a symbol", "score": 50}]},
        {"peer_scores": [{"symbol": "NEW1", "score": 50}, {"symbol": "new1", "score": 60}]},
        {"peer_scores": [{"symbol": f"S{index}", "score": 50} for index in range(501)]},
        {"peer_scores": [{"symbol": "NEW1", "score": 50, "extra": 1}]},
        {"peer_scores": "NEW1:50"},
        {"hurdle": {"required_annual_return_percent": 7}},
        {"portfolio_id": PORTFOLIO_ID},
    ],
)
def test_an_invalid_request_is_rejected_before_any_portfolio_data_is_read(monkeypatch, body):
    fake = ReviewClient()
    _standard_portfolio(fake)

    response = _review(_app(monkeypatch, fake), body)

    assert response.status_code == 422
    assert fake.portfolio_reads() == []
    assert "portfolios" not in fake.read_tables()


def test_a_duplicate_candidate_is_explained_in_plain_language(monkeypatch):
    fake = ReviewClient()

    response = _review(
        _app(monkeypatch, fake),
        {"peer_scores": [{"symbol": "NEW1", "score": 50}, {"symbol": "new1", "score": 60}]},
    )

    assert response.status_code == 422
    messages = [item["msg"] for item in response.json()["detail"]]
    assert any("may appear only once" in message for message in messages)


def test_the_review_reads_only_the_callers_portfolio_and_never_writes(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)
    fake.add_positions([_position("LEAK", 100, 10)], portfolio_id=FOREIGN_PORTFOLIO_ID)
    fake.data["stock_scores"].append(_score("LEAK", cps=1, portfolio_id=FOREIGN_PORTFOLIO_ID))

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    assert "LEAK" not in response.text
    assert fake.read_tables() == [
        "user_access", "portfolios", "positions", "stock_scores", "analyst_signals",
    ]
    assert fake.reads[1]["filters"] == {"id": PORTFOLIO_ID, "user_id": USER_ID}
    for read in fake.portfolio_reads():
        assert read["filters"] == {"portfolio_id": PORTFOLIO_ID}


def test_the_review_selects_only_the_columns_it_needs(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)

    assert _review(_app(monkeypatch, fake)).status_code == 200

    selected = {read["table"]: read["columns"] for read in fake.portfolio_reads()}
    assert selected["positions"] == [
        "symbol", "quantity", "average_cost", "market_price", "market_value",
        "cost_basis", "entry_date", "currency",
    ]
    assert selected["stock_scores"] == ["symbol", "cps", "opportunity_cost"]
    assert selected["analyst_signals"] == ["symbol", "target_price", "target_upside", "signal_date"]


def test_the_review_ranks_the_holdings_furthest_behind_the_hurdle(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)

    response = _review(_app(monkeypatch, fake), {"top_n": 2})

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["required_annual_return_percent"] == 7
    assert review["minimum_holding_days"] == 365
    assert review["top_n"] == 2
    assert [item["symbol"] for item in review["top"]] == ["BBB", "EEE"]
    assert [item["rank"] for item in review["top"]] == [1, 2]
    assert review["summary"] == {
        "holdings": 5,
        "not_analysable": 0,
        "held_under_minimum": 1,
        "meeting_hurdle": 1,
        "behind_hurdle": 3,
        "truncated": False,
    }
    first = review["top"][0]
    assert first["currency"] == "USD"
    assert first["hurdle"]["days_held"] == 730
    assert first["hurdle"]["return_basis"] == "price_only"
    assert first["hurdle"]["status"] == "unavailable"
    assert first["hurdle"]["return_percent"] == pytest.approx(-40)
    assert first["hurdle"]["shortfall_amount"] == pytest.approx(100 * 1.07**2 - 60)
    assert first["cps"] is None
    assert first["dead_money"]["is_dead_money"] is None
    assert first["replacements"]["compared"] is False
    assert review["notes"]


def test_the_default_request_uses_the_documented_hurdle_and_review_size(monkeypatch):
    fake = ReviewClient()
    fake.add_positions([_position(f"S{index}", 100, 50 + index) for index in range(8)])

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["required_annual_return_percent"] == 7
    assert review["top_n"] == 5
    assert len(review["top"]) == 5
    assert review["summary"]["behind_hurdle"] == 8


def test_a_higher_required_return_is_applied_to_every_holding(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)

    seven = _review(_app(monkeypatch, fake)).json()["review"]
    twenty = _review(_app(monkeypatch, fake), {"required_annual_return_percent": 20}).json()["review"]

    assert seven["summary"]["meeting_hurdle"] == 1
    assert twenty["summary"]["meeting_hurdle"] == 0
    assert twenty["required_annual_return_percent"] == 20
    assert twenty["summary"]["behind_hurdle"] == 4


def test_holdings_that_cannot_be_compared_are_listed_not_ranked(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)
    fake.add_positions([
        _position("CLOSED", 100, 0, quantity=0),
        _position("NODATE", 100, 90, entry=None),
        _position("MIXED", 100, 90, currency="USD"),
        _position("MIXED", 100, 90, currency="EUR"),
    ])

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["summary"]["holdings"] == 7
    assert review["summary"]["not_analysable"] == 2
    assert {item["reason"]: item["symbols"] for item in review["skipped"]} == {
        "no_entry_date": ["NODATE"],
        "mixed_currency": ["MIXED"],
    }
    ranked = {item["symbol"] for item in review["top"]}
    assert not ranked & {"NODATE", "MIXED", "CLOSED"}


def test_replacements_use_the_saved_cps_and_the_supplied_candidates(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)
    fake.data["stock_scores"].append(_score("BBB", cps=30, opportunity_cost=70))

    response = _review(
        _app(monkeypatch, fake),
        {
            "top_n": 2,
            "replacement_limit": 2,
            "peer_scores": [
                {"symbol": "new1", "score": 80},
                {"symbol": "NEW2", "score": 55},
                {"symbol": "NEW3", "score": 45},
                {"symbol": "AAA", "score": 90},
                {"symbol": "NEW4", "score": 10},
            ],
        },
    )

    assert response.status_code == 200, response.text
    top = {item["symbol"]: item for item in response.json()["review"]["top"]}
    advice = top["BBB"]["replacements"]
    assert top["BBB"]["cps"] == 30
    assert advice["compared"] is True
    assert [candidate["symbol"] for candidate in advice["candidates"]] == ["NEW1", "NEW2"]
    assert [candidate["expected_benefit"] for candidate in advice["candidates"]] == [50, 25]
    assert top["BBB"]["dead_money"]["is_dead_money"] is True
    assert top["EEE"]["replacements"]["compared"] is False
    assert top["EEE"]["replacements"]["candidates"] == []


def test_replacement_advice_is_withheld_without_candidate_scores(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)
    fake.data["stock_scores"].append(_score("BBB", cps=30))

    response = _review(_app(monkeypatch, fake), {"top_n": 1})

    advice = response.json()["review"]["top"][0]["replacements"]
    assert advice["compared"] is False
    assert advice["candidates"] == []
    assert advice["reasons"]


def test_the_latest_analyst_signal_supplies_the_outlook(monkeypatch):
    fake = ReviewClient()
    fake.add_positions([_position("BBB", 100, 60, quantity=10)])
    fake.data["analyst_signals"].extend([
        _signal("BBB", "2026-01-01T00:00:00+00:00", target_price=9.0),
        _signal("BBB", "2026-12-01T00:00:00+00:00", target_price=5.0),
    ])

    response = _review(_app(monkeypatch, fake))

    hurdle = response.json()["review"]["top"][0]["hurdle"]
    assert [read["orderings"] for read in fake.reads if read["table"] == "analyst_signals"] == [
        [("signal_date", True)]
    ]
    assert hurdle["outlook_status"] == "below"
    assert hurdle["forward_return_percent"] == pytest.approx((5.0 / 6.0 - 1) * 100)


def test_a_portfolio_with_no_positions_returns_an_empty_review(monkeypatch):
    fake = ReviewClient()

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["top"] == []
    assert review["skipped"] == []
    assert review["summary"] == {
        "holdings": 0,
        "not_analysable": 0,
        "held_under_minimum": 0,
        "meeting_hurdle": 0,
        "behind_hurdle": 0,
        "truncated": False,
    }


def test_every_page_of_a_large_portfolio_is_reviewed(monkeypatch):
    fake = ReviewClient(server_row_cap=1_000)
    fake.add_positions([_position(f"S{index:05d}", 100, 100) for index in range(2_345)])
    fake.add_positions([_position("WORST", 100, 1)])

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["summary"]["holdings"] == 2_346
    assert review["summary"]["truncated"] is False
    assert review["top"][0]["symbol"] == "WORST"
    windows = [read["window"] for read in fake.reads if read["table"] == "positions"]
    assert windows == [(0, 999), (1_000, 1_999), (2_000, 2_999)]


def test_a_portfolio_that_fills_the_page_boundary_exactly_is_read_completely(monkeypatch):
    fake = ReviewClient(server_row_cap=1_000)
    fake.add_positions([_position(f"S{index:05d}", 100, 100) for index in range(2_000)])

    review = _review(_app(monkeypatch, fake)).json()["review"]

    assert review["summary"]["holdings"] == 2_000
    assert review["summary"]["truncated"] is False
    windows = [read["window"] for read in fake.reads if read["table"] == "positions"]
    assert windows == [(0, 999), (1_000, 1_999), (2_000, 2_999)]


def test_positions_are_read_in_a_stable_order_so_pages_do_not_overlap(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)

    assert _review(_app(monkeypatch, fake)).status_code == 200

    orderings = [read["orderings"] for read in fake.reads if read["table"] == "positions"]
    assert orderings == [[("id", False)]]


def test_a_review_stops_at_the_page_ceiling_and_says_so(monkeypatch):
    monkeypatch.setattr(pip_api, "REVIEW_PAGE_SIZE", 3)
    monkeypatch.setattr(pip_api, "REVIEW_MAX_PAGES", 2)
    fake = ReviewClient(server_row_cap=3)
    fake.add_positions([_position(f"S{index}", 100, 100) for index in range(9)])

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["summary"]["holdings"] == 6
    assert review["summary"]["truncated"] is True
    assert TRUNCATED_NOTE in review["notes"]
    assert [read["window"] for read in fake.reads if read["table"] == "positions"] == [(0, 2), (3, 5)]


def test_a_portfolio_below_the_page_ceiling_is_not_marked_truncated(monkeypatch):
    monkeypatch.setattr(pip_api, "REVIEW_PAGE_SIZE", 3)
    monkeypatch.setattr(pip_api, "REVIEW_MAX_PAGES", 2)
    fake = ReviewClient(server_row_cap=3)
    fake.add_positions([_position(f"S{index}", 100, 100) for index in range(5)])

    review = _review(_app(monkeypatch, fake)).json()["review"]

    assert review["summary"]["holdings"] == 5
    assert review["summary"]["truncated"] is False
    assert TRUNCATED_NOTE not in review["notes"]


def test_a_data_service_failure_is_reported_without_leaking_details(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)
    original = ReviewQuery.execute

    def failing(self):
        if self.table_name == "stock_scores":
            raise APIError({"message": "permission denied for table stock_scores", "code": "42501"})
        return original(self)

    monkeypatch.setattr(ReviewQuery, "execute", failing)

    response = _review(_app(monkeypatch, fake))

    assert response.status_code == 502
    assert response.json() == {"detail": "The PIP data service request failed."}
    assert "stock_scores" not in response.text


def test_the_review_response_contains_no_account_identifiers(monkeypatch):
    fake = ReviewClient()
    _standard_portfolio(fake)

    response = _review(_app(monkeypatch, fake))

    for forbidden in (USER_ID, PORTFOLIO_ID, TOKEN, "user_id", "portfolio_id", "account"):
        assert forbidden not in response.text

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone

import pytest

from stockscanner.pip.holdings import (
    FLAG_MESSAGES,
    FLAG_MISSING_COST_BASIS,
    FLAG_MISSING_ENTRY_DATE,
    FLAG_MISSING_MARKET_VALUE,
    FLAG_MIXED_CURRENCY,
    FLAG_SHORT_POSITION,
    HOLDINGS_NOTES,
    TRUNCATED_NOTE,
    summarize_holdings,
)

TODAY = date(2027, 1, 1)


def _row(symbol, cost=100, value=110, entry="2026-01-01", quantity=10, currency="USD", **extra):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis": cost,
        "market_value": value,
        "entry_date": entry,
        "currency": currency,
        **extra,
    }


def _summarize(rows, **kwargs):
    return summarize_holdings(rows, today=TODAY, **kwargs)


def _by_symbol(overview):
    return {holding.symbol: holding for holding in overview.holdings}


def test_lots_of_one_symbol_are_combined_and_the_earliest_entry_date_is_used():
    overview = _summarize([
        _row("AAA", cost=100, value=120, entry="2026-06-01", quantity=4),
        _row("AAA", cost=300, value=330, entry="2025-01-01T09:30:00+00:00", quantity=6),
    ])

    holding = _by_symbol(overview)["AAA"]
    assert overview.lots == 2
    assert holding.lot_count == 2
    assert holding.quantity == 10
    assert holding.cost_basis == 400
    assert holding.market_value == 450
    assert holding.price_return_percent == pytest.approx(12.5)
    assert holding.entry_date == "2025-01-01"
    assert holding.days_held == 730
    assert holding.currency == "USD"
    assert holding.flags == ()


def test_holdings_are_sorted_by_symbol_and_symbols_are_normalised():
    overview = _summarize([_row(" ccc "), _row("AAA"), _row("bbb")])

    assert [holding.symbol for holding in overview.holdings] == ["AAA", "BBB", "CCC"]


def test_closed_blank_and_unreadable_quantity_rows_are_not_holdings():
    overview = _summarize([
        _row("AAA", quantity=0),
        _row("BBB", quantity=None),
        _row("CCC", quantity="not a number"),
        _row("DDD", quantity=float("nan")),
        _row("", quantity=5),
        _row(None, quantity=5),
        _row("EEE"),
    ])

    assert [holding.symbol for holding in overview.holdings] == ["EEE"]
    assert overview.lots == 1


def test_cost_and_value_fall_back_to_per_share_figures_like_the_analysis_route():
    overview = _summarize([
        {
            "symbol": "AAA",
            "quantity": 5,
            "cost_basis": None,
            "average_cost": 20,
            "market_value": None,
            "market_price": 30,
            "entry_date": "2026-01-01",
            "currency": "USD",
        },
    ])

    holding = _by_symbol(overview)["AAA"]
    assert holding.cost_basis == 100
    assert holding.market_value == 150
    assert holding.price_return_percent == pytest.approx(50)


def test_an_explicit_cost_basis_and_market_value_win_over_per_share_figures():
    overview = _summarize([_row("AAA", cost=100, value=110, average_cost=1, market_price=1)])

    holding = _by_symbol(overview)["AAA"]
    assert (holding.cost_basis, holding.market_value) == (100, 110)


@pytest.mark.parametrize(
    ("row", "flag", "withheld"),
    [
        (_row("AAA", value=None), FLAG_MISSING_MARKET_VALUE, ("market_value", "price_return_percent")),
        (_row("AAA", cost=None), FLAG_MISSING_COST_BASIS, ("cost_basis", "price_return_percent")),
        (_row("AAA", cost=0), FLAG_MISSING_COST_BASIS, ("price_return_percent",)),
        (_row("AAA", cost=-5), FLAG_MISSING_COST_BASIS, ("price_return_percent",)),
        (_row("AAA", entry=None), FLAG_MISSING_ENTRY_DATE, ("entry_date", "days_held")),
        (_row("AAA", entry="not a date"), FLAG_MISSING_ENTRY_DATE, ("entry_date", "days_held")),
        (_row("AAA", currency=""), FLAG_MIXED_CURRENCY, ("currency", "cost_basis", "market_value", "price_return_percent")),
        (_row("AAA", currency=None), FLAG_MIXED_CURRENCY, ("currency", "cost_basis", "market_value", "price_return_percent")),
    ],
)
def test_missing_data_is_flagged_and_never_replaced_with_a_guess(row, flag, withheld):
    holding = _by_symbol(_summarize([row]))["AAA"]

    assert holding.flags == (flag,)
    for field in withheld:
        assert getattr(holding, field) is None


def test_a_return_needs_every_lot_to_have_a_positive_cost_and_a_value():
    overview = _summarize([
        _row("AAA", cost=100, value=110),
        _row("AAA", cost=None, value=50),
        _row("BBB", cost=100, value=110),
        _row("BBB", cost=100, value=None),
    ])

    holdings = _by_symbol(overview)
    assert holdings["AAA"].flags == (FLAG_MISSING_COST_BASIS,)
    assert holdings["AAA"].price_return_percent is None
    assert holdings["AAA"].market_value == 160
    assert holdings["BBB"].flags == (FLAG_MISSING_MARKET_VALUE,)
    assert holdings["BBB"].price_return_percent is None
    assert holdings["BBB"].cost_basis == 200


def test_one_dateless_lot_flags_the_holding_but_keeps_the_earliest_known_date():
    overview = _summarize([_row("AAA", entry="2026-06-01"), _row("AAA", entry=None)])

    holding = _by_symbol(overview)["AAA"]
    assert holding.flags == (FLAG_MISSING_ENTRY_DATE,)
    assert holding.entry_date == "2026-06-01"
    assert holding.days_held == 214


def test_short_positions_are_listed_without_a_return_or_a_cost_flag():
    overview = _summarize([_row("AAA", quantity=-10, cost=-1_000, value=-1_100)])

    holding = _by_symbol(overview)["AAA"]
    assert holding.flags == (FLAG_SHORT_POSITION,)
    assert holding.quantity == -10
    assert holding.price_return_percent is None
    assert holding.market_value == -1_100


def test_one_short_lot_makes_the_whole_holding_short_with_no_return():
    overview = _summarize([
        _row("AAA", quantity=10, cost=1_000, value=1_100),
        _row("AAA", quantity=-4, cost=-400, value=-440),
    ])

    holding = _by_symbol(overview)["AAA"]
    assert holding.flags == (FLAG_SHORT_POSITION,)
    assert holding.quantity == 6
    assert holding.price_return_percent is None


def test_a_holding_in_two_currencies_is_not_added_up_or_totalled():
    overview = _summarize([
        _row("AAA", currency="USD", cost=100, value=110),
        _row("AAA", currency="eur", cost=100, value=110),
        _row("BBB", currency="USD", cost=100, value=110),
    ])

    mixed = _by_symbol(overview)["AAA"]
    assert mixed.currency is None
    assert mixed.cost_basis is None
    assert mixed.market_value is None
    assert mixed.price_return_percent is None
    assert mixed.quantity == 20
    assert mixed.flags == (FLAG_MIXED_CURRENCY,)
    assert [(total.currency, total.holdings, total.market_value) for total in overview.totals] == [
        ("USD", 1, 110),
    ]


def test_totals_are_kept_per_currency_and_report_how_many_holdings_are_priced():
    overview = _summarize([
        _row("AAA", currency="USD", cost=100, value=110),
        _row("BBB", currency="USD", cost=200, value=None),
        _row("CCC", currency="usd", cost=None, value=40),
        _row("DDD", currency="EUR", cost=500, value=450),
    ])

    totals = {total.currency: total for total in overview.totals}
    assert list(totals) == ["EUR", "USD"]
    assert totals["EUR"].market_value == 450
    assert totals["EUR"].cost_basis == 500
    assert totals["USD"].holdings == 3
    assert totals["USD"].market_value == 150
    assert totals["USD"].priced_holdings == 2
    assert totals["USD"].cost_basis == 300
    assert totals["USD"].costed_holdings == 2


def test_flag_summary_counts_holdings_once_with_the_explanatory_message():
    overview = _summarize([
        _row("AAA", value=None),
        _row("AAA", value=None),
        _row("BBB", value=None, entry=None),
        _row("CCC"),
    ])

    assert [(item.flag, item.count) for item in overview.flags] == [
        (FLAG_MISSING_ENTRY_DATE, 1),
        (FLAG_MISSING_MARKET_VALUE, 2),
    ]
    assert all(item.message == FLAG_MESSAGES[item.flag] for item in overview.flags)


def test_data_as_of_is_the_latest_update_among_open_holdings():
    overview = _summarize([
        _row("AAA", last_updated="2026-11-01T10:00:00+00:00"),
        _row("BBB", last_updated="2026-11-02T08:30:00.123Z"),
        _row("CCC", last_updated="2026-11-01T23:00:00-05:00"),
        _row("DDD", last_updated="garbage"),
        _row("EEE", quantity=0, last_updated="2030-01-01T00:00:00+00:00"),
    ])

    assert overview.as_of == "2026-11-02T08:30:00.123000+00:00"


def test_data_as_of_treats_naive_timestamps_as_utc_and_is_none_when_unknown():
    assert _summarize([_row("AAA", last_updated=datetime(2026, 11, 1, 9, 0))]).as_of == (
        "2026-11-01T09:00:00+00:00"
    )
    assert _summarize([_row("AAA")]).as_of is None
    assert _summarize([]).as_of is None


def test_entry_dates_accept_dates_datetimes_and_iso_strings():
    overview = _summarize([
        _row("AAA", entry=date(2026, 12, 1)),
        _row("BBB", entry=datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc)),
        _row("CCC", entry="2026-12-01"),
    ])

    assert {holding.entry_date for holding in overview.holdings} == {"2026-12-01"}
    assert {holding.days_held for holding in overview.holdings} == {31}


def test_a_future_entry_date_never_produces_negative_days_held():
    holding = _by_symbol(_summarize([_row("AAA", entry="2027-06-01")]))["AAA"]

    assert holding.days_held == 0


@pytest.mark.parametrize("bad", [True, "abc", [1], {"v": 1}, float("inf"), float("nan")])
def test_unreadable_numbers_count_as_missing_not_zero(bad):
    holding = _by_symbol(_summarize([_row("AAA", cost=bad, value=bad)]))["AAA"]

    assert holding.cost_basis is None
    assert holding.market_value is None
    assert set(holding.flags) == {FLAG_MISSING_COST_BASIS, FLAG_MISSING_MARKET_VALUE}


def test_notes_say_the_view_is_read_only_and_flag_truncation():
    assert _summarize([_row("AAA")]).notes == HOLDINGS_NOTES
    assert any("never places or transmits orders" in note for note in HOLDINGS_NOTES)

    truncated = _summarize([_row("AAA")], truncated=True)
    assert truncated.truncated is True
    assert truncated.notes == HOLDINGS_NOTES + (TRUNCATED_NOTE,)
    assert _summarize([_row("AAA")]).truncated is False


def test_account_and_source_identifiers_never_reach_the_overview():
    overview = _summarize([
        _row(
            "AAA",
            account_id="ACCOUNT-SECRET",
            source_key="SOURCE-SECRET",
            metadata={"account_fingerprint": "FINGERPRINT-SECRET"},
        ),
    ])

    text = json.dumps(asdict(overview))
    assert "SECRET" not in text
    assert set(asdict(overview.holdings[0])) == {
        "symbol", "currency", "quantity", "lot_count", "cost_basis", "market_value",
        "price_return_percent", "entry_date", "days_held", "flags",
    }


def test_the_overview_is_json_serialisable_and_empty_input_is_empty_not_an_error():
    json.dumps(asdict(_summarize([_row("AAA"), _row("BBB", value=None)])))

    overview = _summarize([])
    assert overview.holdings == ()
    assert overview.totals == ()
    assert overview.flags == ()
    assert overview.lots == 0

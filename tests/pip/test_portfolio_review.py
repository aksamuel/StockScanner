from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from stockscanner.pip.hurdle import BASIS_PRICE_ONLY, STATUS_BELOW, STATUS_MEETS, STATUS_UNAVAILABLE
from stockscanner.pip.portfolio_review import (
    DEFAULT_REPLACEMENT_LIMIT,
    DEFAULT_TOP_N,
    MAX_SKIPPED_SYMBOLS,
    REVIEW_NOTES,
    TRUNCATED_NOTE,
    UNCONFIRMED_REASON,
    PortfolioReviewer,
)
from stockscanner.pip.position_lifecycle import PositionLifecycleAnalyzer


class _FixedClock(PositionLifecycleAnalyzer):
    """Pins "today" to 2027-01-01 so holding days do not drift with the calendar."""

    def __init__(self):
        super().__init__()
        self.snapshot_time = datetime(2027, 1, 1, tzinfo=timezone.utc)


def _reviewer() -> PortfolioReviewer:
    return PortfolioReviewer(lifecycle_analyzer=_FixedClock())


def _row(symbol, cost, value, entry="2025-01-01", quantity=10, currency="USD", **extra):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis": cost,
        "market_value": value,
        "entry_date": entry,
        "currency": currency,
        **extra,
    }


def _portfolio():
    return [
        _row("AAA", 100, 110),  # 730 days, return 10% against a 14.49% path
        _row("BBB", 100, 60),  # 730 days, return -40%
        _row("CCC", 100, 130),  # 730 days, return 30%: ahead of the path
        _row("DDD", 100, 80, entry="2026-06-01"),  # 214 days: too recent to judge
        _row("EEE", 100, 90, entry="2024-01-01"),  # 1096 days, return -10%
        _row("FFF", 100, 100),  # 730 days, flat
    ]


def _hurdle_return(days: int, required: float = 7.0) -> float:
    return ((1 + required / 100) ** (days / 365) - 1) * 100


def test_defaults_match_the_documented_review_size():
    assert DEFAULT_TOP_N == 5
    assert DEFAULT_REPLACEMENT_LIMIT == 5


def test_holdings_are_ranked_by_how_far_they_trail_the_hurdle_path():
    review = _reviewer().review(_portfolio())

    assert [item.symbol for item in review.top] == ["BBB", "EEE", "FFF", "AAA"]
    assert [item.rank for item in review.top] == [1, 2, 3, 4]
    assert review.top[0].hurdle.excess_return_percentage_points == pytest.approx(-40 - _hurdle_return(730), abs=0.01)
    assert review.top[1].hurdle.excess_return_percentage_points == pytest.approx(-10 - _hurdle_return(1096), abs=0.01)
    assert review.top[3].hurdle.excess_return_percentage_points == pytest.approx(10 - _hurdle_return(730), abs=0.01)
    assert asdict(review.summary) == {
        "holdings": 6,
        "not_analysable": 0,
        "held_under_minimum": 1,
        "meeting_hurdle": 1,
        "behind_hurdle": 4,
        "truncated": False,
    }
    assert review.required_annual_return_percent == 7.0
    assert review.minimum_holding_days == 365
    assert review.notes == REVIEW_NOTES


def test_ranked_holdings_are_labelled_price_only_because_dividends_are_unknown():
    review = _reviewer().review(_portfolio())

    for item in review.top:
        assert item.hurdle.return_basis == BASIS_PRICE_ONLY
        assert item.hurdle.shortfall_amount > 0
        assert item.currency == "USD"


def test_top_n_limits_the_list_but_not_the_summary_counts():
    review = _reviewer().review(_portfolio(), top_n=2)

    assert [item.symbol for item in review.top] == ["BBB", "EEE"]
    assert review.top_n == 2
    assert review.summary.behind_hurdle == 4


def test_equal_shortfalls_are_ordered_by_symbol():
    review = _reviewer().review([_row("ZZZ", 100, 80), _row("AAA", 100, 80), _row("MMM", 100, 80)])

    assert [item.symbol for item in review.top] == ["AAA", "MMM", "ZZZ"]


def test_a_holding_is_ranked_after_exactly_one_year_but_not_a_day_earlier():
    review = _reviewer().review([
        _row("ONE", 100, 90, entry="2026-01-01"),
        _row("TWO", 100, 90, entry="2026-01-02"),
    ])

    assert [item.symbol for item in review.top] == ["ONE"]
    assert review.top[0].hurdle.days_held == 365
    assert review.summary.held_under_minimum == 1


def test_a_holding_ahead_of_the_path_is_counted_but_not_ranked():
    review = _reviewer().review([_row("UP", 100, 130)])

    assert review.top == ()
    assert review.summary.meeting_hurdle == 1
    assert review.summary.behind_hurdle == 0


def test_the_required_return_is_applied_to_every_holding():
    positions = [_row("LOW", 100, 105), _row("HIGH", 100, 130)]

    flat = _reviewer().review(positions, required_annual_return_percent=0)
    demanding = _reviewer().review(positions, required_annual_return_percent=20)

    assert flat.top == ()
    assert flat.summary.meeting_hurdle == 2
    assert [item.symbol for item in demanding.top] == ["LOW", "HIGH"]
    assert demanding.required_annual_return_percent == 20
    assert demanding.top[0].hurdle.required_annual_return_percent == 20


def test_cost_and_value_fall_back_to_per_unit_prices():
    review = _reviewer().review([{
        "symbol": "PPP",
        "quantity": "10",
        "average_cost": "10",
        "market_price": "6",
        "entry_date": "2025-01-01T00:00:00+00:00",
        "currency": "usd",
    }])

    item = review.top[0]
    assert item.currency == "USD"
    assert item.hurdle.return_percent == pytest.approx(-40)


def test_lots_of_one_symbol_are_combined_with_their_own_entry_dates():
    review = _reviewer().review([
        _row("LOT", 100, 150, entry="2025-01-01", quantity=4),
        _row("LOT", 300, 250, entry="2026-01-01", quantity=6),
    ])

    item = review.top[0]
    assert review.summary.holdings == 1
    assert item.hurdle.lot_count == 2
    assert item.hurdle.days_held == 456
    assert item.hurdle.shortfall_amount == pytest.approx(100 * 1.07**2 + 300 * 1.07 - 400)


def test_a_lot_without_an_entry_date_skips_the_whole_symbol():
    review = _reviewer().review([
        _row("LOT", 100, 150, entry="2025-01-01"),
        _row("LOT", 300, 250, entry=None),
    ])

    assert review.top == ()
    assert [(skip.reason, skip.symbols) for skip in review.skipped] == [("no_entry_date", ("LOT",))]


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([_row("X", 100, 90, currency="USD"), _row("X", 100, 90, currency="EUR")], "mixed_currency"),
        ([_row("X", 100, 90, currency="")], "mixed_currency"),
        ([_row("X", 100, 90, currency=None)], "mixed_currency"),
        ([_row("X", 100, 90, quantity=-5)], "short_position"),
        ([_row("X", 100, 90, quantity=3), _row("X", 100, 90, quantity=-3)], "short_position"),
        ([_row("X", None, 90)], "no_cost_basis"),
        ([_row("X", 0, 90)], "no_cost_basis"),
        ([_row("X", -100, 90)], "no_cost_basis"),
        ([_row("X", 100, 90, entry=None)], "no_entry_date"),
        ([_row("X", 100, 90, entry="not-a-date")], "no_entry_date"),
        ([_row("X", 100, None)], "no_market_value"),
        ([_row("X", 100, -5)], "no_market_value"),
    ],
)
def test_holdings_that_cannot_be_compared_are_listed_with_a_reason(rows, reason):
    review = _reviewer().review(rows)

    assert review.top == ()
    assert review.summary.holdings == 1
    assert review.summary.not_analysable == 1
    assert review.summary.behind_hurdle == 0
    assert len(review.skipped) == 1
    skip = review.skipped[0]
    assert (skip.reason, skip.count, skip.symbols) == (reason, 1, ("X",))
    assert skip.message


def test_a_short_position_with_a_positive_cost_is_never_ranked_as_a_long():
    review = _reviewer().review([_row("SHRT", 100, 60, quantity=-10)])

    assert review.top == ()
    assert review.skipped[0].reason == "short_position"


def test_closed_unnamed_and_unquantified_rows_are_not_holdings():
    review = _reviewer().review([
        _row("ZERO", 100, 90, quantity=0),
        _row("NONE", 100, 90, quantity=None),
        _row("BLNK", 100, 90, quantity=""),
        _row("", 100, 90),
        _row(None, 100, 90),
        _row("OPEN", 100, 90),
    ])

    assert review.summary.holdings == 1
    assert [item.symbol for item in review.top] == ["OPEN"]


def test_skip_groups_are_ordered_by_size_and_list_a_bounded_number_of_symbols():
    positions = [_row(f"S{index:02d}", None, 90) for index in range(MAX_SKIPPED_SYMBOLS + 5)]
    positions.append(_row("LATE", 100, 90, entry=None))

    review = _reviewer().review(positions)

    assert [(skip.reason, skip.count) for skip in review.skipped] == [
        ("no_cost_basis", MAX_SKIPPED_SYMBOLS + 5),
        ("no_entry_date", 1),
    ]
    assert len(review.skipped[0].symbols) == MAX_SKIPPED_SYMBOLS
    assert review.skipped[0].symbols == tuple(f"S{index:02d}" for index in range(MAX_SKIPPED_SYMBOLS))
    assert review.summary.not_analysable == MAX_SKIPPED_SYMBOLS + 6


def test_a_worthless_holding_ranks_first_and_stays_serializable():
    review = _reviewer().review([_row("ZERO", 100, 0), *_portfolio()])

    assert review.top[0].symbol == "ZERO"
    assert review.top[0].hurdle.return_percent == pytest.approx(-100)
    json.dumps(asdict(review), allow_nan=False)


def test_the_review_does_not_modify_its_inputs():
    positions = _portfolio()
    scores = [{"symbol": "BBB", "cps": 30, "opportunity_cost": 70}]
    signals = [{"symbol": "BBB", "target_price": 6.3, "signal_date": "2026-06-01"}]
    snapshot = copy.deepcopy((positions, scores, signals))

    _reviewer().review(positions, scores=scores, signals=signals, peer_scores=[("NEW", 90)])

    assert (positions, scores, signals) == snapshot


def test_forward_outlook_comes_from_the_latest_signal_and_prefers_the_target_price():
    positions = [_row("BBB", 100, 60)]
    signals = [
        {"symbol": "BBB", "target_price": 5, "target_upside": 50, "signal_date": "2026-01-01"},
        {"symbol": "BBB", "target_price": 6.3, "target_upside": 50, "signal_date": "2026-06-01"},
        {"symbol": "OTHER", "target_price": 60, "signal_date": "2026-12-01"},
    ]

    item = _reviewer().review(positions, signals=signals).top[0]

    assert item.hurdle.forward_return_percent == pytest.approx(5.0)
    assert item.hurdle.outlook_status == STATUS_BELOW


def test_forward_outlook_falls_back_to_the_stored_upside_and_is_unavailable_without_a_signal():
    positions = [_row("BBB", 100, 60)]

    upside = _reviewer().review(
        positions, signals=[{"symbol": "BBB", "target_upside": 12, "signal_date": "2026-06-01"}]
    ).top[0]
    missing = _reviewer().review(positions).top[0]

    assert upside.hurdle.forward_return_percent == 12
    assert upside.hurdle.outlook_status == STATUS_MEETS
    assert missing.hurdle.forward_return_percent is None
    assert missing.hurdle.outlook_status == STATUS_UNAVAILABLE


def test_ranked_holdings_never_report_a_confirmed_hurdle_status_without_dividends():
    review = _reviewer().review(_portfolio())

    assert {item.hurdle.status for item in review.top} == {STATUS_UNAVAILABLE}


def test_a_dead_money_verdict_is_withheld_when_dividends_are_unknown():
    scores = [
        {"symbol": "BBB", "cps": 30, "opportunity_cost": 20},
        {"symbol": "EEE", "cps": 80, "opportunity_cost": 20},
    ]

    review = _reviewer().review(_portfolio(), scores=scores)
    verdicts = {item.symbol: item.dead_money for item in review.top}

    assert verdicts["BBB"].is_dead_money is None
    assert any("CPS is below" in reason for reason in verdicts["BBB"].reasons)
    assert UNCONFIRMED_REASON in verdicts["BBB"].reasons
    assert verdicts["EEE"].is_dead_money is None
    assert UNCONFIRMED_REASON in verdicts["EEE"].reasons


def test_a_holding_without_any_evidence_reports_insufficient_data():
    verdict = _reviewer().review([_row("BBB", 100, 60)]).top[0].dead_money

    assert verdict.is_dead_money is None
    assert verdict.confidence == 0.0
    assert UNCONFIRMED_REASON not in verdict.reasons


def test_dead_money_is_flagged_when_cps_is_weak_and_opportunity_cost_is_high():
    scores = [{"symbol": "BBB", "cps": 30, "opportunity_cost": 70}]

    item = _reviewer().review([_row("BBB", 100, 60)], scores=scores).top[0]

    assert item.cps == 30
    assert item.dead_money.is_dead_money is True
    assert item.dead_money.confidence > 0
    assert UNCONFIRMED_REASON not in item.dead_money.reasons


def test_scores_outside_zero_to_one_hundred_are_ignored():
    scores = [{"symbol": "BBB", "cps": 250, "opportunity_cost": -5}]

    item = _reviewer().review([_row("BBB", 100, 60)], scores=scores).top[0]

    assert item.cps is None
    assert item.dead_money.is_dead_money is None


def _scored(symbol: str, cps: float = 30):
    return {"symbol": symbol, "cps": cps}


def test_replacements_compare_candidate_scores_with_the_holding_cps():
    peers = [("NEW1", 80), ("NEW2", 55), ("NEW3", 20), ("AAA", 90), ("fff", 95)]

    review = _reviewer().review(
        _portfolio(), scores=[_scored("BBB"), _scored("EEE")], peer_scores=peers
    )
    by_symbol = {item.symbol: item.replacements for item in review.top}

    assert by_symbol["BBB"].compared is True
    assert by_symbol["BBB"].reasons == ()
    assert [(candidate.symbol, candidate.expected_benefit) for candidate in by_symbol["BBB"].candidates] == [
        ("NEW1", 50),
        ("NEW2", 25),
    ]
    assert [(candidate.symbol, candidate.expected_benefit) for candidate in by_symbol["EEE"].candidates] == [
        ("NEW1", 50),
        ("NEW2", 25),
    ]
    assert "EEE" in by_symbol["EEE"].candidates[0].rationale[0]


def test_replacements_never_suggest_a_symbol_that_is_already_held():
    review = _reviewer().review(
        [*_portfolio(), _row("SKIP", None, 90)],
        scores=[_scored("BBB")],
        peer_scores=[("AAA", 90), ("skip", 95), ("NEW1", 80)],
    )

    assert [candidate.symbol for candidate in review.top[0].replacements.candidates] == ["NEW1"]


def test_the_replacement_limit_caps_candidates_per_holding():
    peers = [("NEW1", 80), ("NEW2", 70), ("NEW3", 60)]

    review = _reviewer().review(
        [_row("BBB", 100, 60)], scores=[_scored("BBB")], peer_scores=peers, replacement_limit=2
    )

    assert [candidate.symbol for candidate in review.top[0].replacements.candidates] == ["NEW1", "NEW2"]


def test_only_ranked_holdings_receive_replacement_advice():
    review = _reviewer().review(
        _portfolio(),
        scores=[_scored(symbol) for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")],
        peer_scores=[("NEW1", 80)],
        top_n=2,
    )

    assert [item.symbol for item in review.top] == ["BBB", "EEE"]
    assert all(item.replacements.candidates for item in review.top)


def test_replacements_are_not_compared_without_candidates_or_a_saved_cps():
    both_missing = _reviewer().review([_row("BBB", 100, 60)]).top[0].replacements
    no_peers = _reviewer().review([_row("BBB", 100, 60)], scores=[_scored("BBB")]).top[0].replacements
    no_cps = _reviewer().review([_row("BBB", 100, 60)], peer_scores=[("NEW1", 80)]).top[0].replacements

    assert both_missing.compared is False
    assert len(both_missing.reasons) == 2
    assert both_missing.candidates == ()
    assert no_peers.compared is False
    assert no_peers.reasons == ("No replacement candidate scores were supplied.",)
    assert no_cps.compared is False
    assert "no saved CPS" in no_cps.reasons[0]


def test_candidates_that_do_not_beat_the_holding_are_reported_as_compared_with_none():
    review = _reviewer().review(
        [_row("BBB", 100, 60)], scores=[_scored("BBB", 70)], peer_scores=[("NEW1", 70), ("NEW2", 40)]
    )

    advice = review.top[0].replacements
    assert advice.compared is True
    assert advice.candidates == ()
    assert advice.reasons == ("No supplied candidate scores are above this holding's CPS.",)


def test_a_candidate_listed_twice_keeps_its_lowest_score():
    review = _reviewer().review(
        [_row("BBB", 100, 60)],
        scores=[_scored("BBB")],
        peer_scores=[("NEW1", 95), ("new1", 50)],
    )

    candidates = review.top[0].replacements.candidates
    assert [(candidate.symbol, candidate.score) for candidate in candidates] == [("NEW1", 50)]


def test_non_numeric_candidate_scores_are_ignored():
    review = _reviewer().review(
        [_row("BBB", 100, 60)],
        scores=[_scored("BBB")],
        peer_scores=[("NEW1", "high"), ("NEW2", float("nan")), ("NEW3", 80)],
    )

    assert [candidate.symbol for candidate in review.top[0].replacements.candidates] == ["NEW3"]


def test_a_truncated_position_list_is_disclosed():
    review = _reviewer().review(_portfolio(), truncated=True)

    assert review.summary.truncated is True
    assert review.notes[-1] == TRUNCATED_NOTE
    assert TRUNCATED_NOTE not in _reviewer().review(_portfolio()).notes


@pytest.mark.parametrize("required", [-1, float("nan"), float("inf"), "abc", None, True])
def test_an_invalid_required_return_is_rejected(required):
    with pytest.raises(ValueError):
        _reviewer().review(_portfolio(), required_annual_return_percent=required)


@pytest.mark.parametrize("value", [0, -1, 2.5, "5", None, True])
def test_top_n_must_be_a_positive_whole_number(value):
    with pytest.raises(ValueError):
        _reviewer().review(_portfolio(), top_n=value)


@pytest.mark.parametrize("value", [0, -1, 2.5, "5", None, True])
def test_replacement_limit_must_be_a_positive_whole_number(value):
    with pytest.raises(ValueError):
        _reviewer().review(_portfolio(), replacement_limit=value)


def test_review_output_is_json_serializable_with_replacements_and_signals():
    review = _reviewer().review(
        _portfolio(),
        scores=[_scored("BBB")],
        signals=[{"symbol": "BBB", "target_price": 7, "signal_date": "2026-06-01"}],
        peer_scores=[("NEW1", 80)],
    )

    payload = json.loads(json.dumps(asdict(review), allow_nan=False))

    assert payload["top"][0]["replacements"]["candidates"][0]["symbol"] == "NEW1"
    assert payload["top"][0]["hurdle"]["required_return_by_horizon"][0]["years"] == 1

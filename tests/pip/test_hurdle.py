from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from math import log

import pytest

from stockscanner.pip.dead_money import DeadMoneyDetector
from stockscanner.pip.hurdle import (
    BASIS_PRICE_ONLY,
    BASIS_TOTAL,
    DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT,
    STATUS_BELOW,
    STATUS_MEETS,
    STATUS_UNAVAILABLE,
    HoldingLot,
    HurdleAnalyzer,
)
from stockscanner.pip.position_lifecycle import PositionLifecycleAnalyzer


def _analyze(**overrides):
    inputs = {"cost_basis": 100, "market_value": 110, "dividends": 0, "days_held": 730}
    inputs.update(overrides)
    return HurdleAnalyzer().analyze("AAA", **inputs)


def _path(cost: float, days: int, hurdle: float = 7.0) -> float:
    return cost * (1 + hurdle / 100) ** (days / 365)


def test_default_required_return_is_seven_percent_per_year():
    assert DEFAULT_REQUIRED_ANNUAL_RETURN_PERCENT == 7.0
    assert _analyze().required_annual_return_percent == 7.0


def test_holding_below_the_hurdle_path_after_a_full_year_is_flagged():
    result = _analyze()

    assert result.status == STATUS_BELOW
    assert result.return_basis == BASIS_TOTAL
    assert result.lot_count == 1
    assert result.days_held == 730
    assert result.return_percent == pytest.approx(10)
    assert result.hurdle_return_percent == pytest.approx(14.49)
    assert result.excess_return_percentage_points == pytest.approx(-4.49)
    assert result.annualized_return_percent == pytest.approx((1.1**0.5 - 1) * 100)
    assert result.shortfall_amount == pytest.approx(4.49)


def test_dividends_received_count_towards_the_hurdle():
    assert _analyze(dividends=0).status == STATUS_BELOW

    result = _analyze(dividends=5)

    assert result.status == STATUS_MEETS
    assert result.return_percent == pytest.approx(15)
    assert result.shortfall_amount == pytest.approx(-0.51)


def test_missing_or_invalid_dividends_keep_the_verdict_unavailable_instead_of_guessing():
    for dividends in (None, -5, "n/a"):
        result = _analyze(dividends=dividends)

        assert result.status == STATUS_UNAVAILABLE
        assert result.return_basis == BASIS_PRICE_ONLY
        assert result.return_percent == pytest.approx(10)
        assert any("dividends" in reason.lower() for reason in result.reasons)


def test_price_return_that_already_meets_the_hurdle_does_not_need_dividends():
    result = _analyze(market_value=120, dividends=None)

    assert result.status == STATUS_MEETS
    assert result.return_basis == BASIS_PRICE_ONLY


def test_holding_under_one_year_is_never_judged_below_or_annualized():
    young = _analyze(market_value=90, days_held=100)

    assert young.status == STATUS_UNAVAILABLE
    assert young.annualized_return_percent is None
    assert any("365" in reason for reason in young.reasons)

    ahead = _analyze(market_value=110, days_held=100)
    assert ahead.status == STATUS_MEETS
    assert ahead.annualized_return_percent is None


def test_one_year_is_the_boundary_for_judging_and_annualizing():
    just_short = _analyze(market_value=106, days_held=364)
    assert just_short.status == STATUS_UNAVAILABLE
    assert just_short.annualized_return_percent is None

    one_year = _analyze(market_value=106, days_held=365)
    assert one_year.status == STATUS_BELOW
    assert one_year.annualized_return_percent == pytest.approx(6)


def test_zero_hurdle_only_requires_preserving_capital():
    assert _analyze(
        market_value=100, days_held=400, required_annual_return_percent=0
    ).status == STATUS_MEETS
    assert _analyze(
        market_value=99.99, days_held=400, required_annual_return_percent=0
    ).status == STATUS_BELOW


def test_custom_required_return_changes_the_hurdle_path():
    result = _analyze(market_value=120, required_annual_return_percent=10)

    assert result.required_annual_return_percent == 10
    assert result.hurdle_return_percent == pytest.approx(21)
    assert result.status == STATUS_BELOW


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "abc", None, True])
def test_invalid_required_return_is_rejected(value):
    with pytest.raises(ValueError, match="Required annual return"):
        _analyze(required_annual_return_percent=value)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"cost_basis": None}, "cost basis"),
        ({"cost_basis": 0}, "cost basis"),
        ({"cost_basis": -50}, "cost basis"),
        ({"cost_basis": float("nan")}, "cost basis"),
        ({"market_value": None}, "market value"),
        ({"market_value": -1}, "market value"),
        ({"market_value": True}, "market value"),
        ({"days_held": None}, "entry date"),
        ({"days_held": -1}, "entry date"),
    ],
)
def test_unusable_inputs_leave_the_hurdle_unavailable(overrides, reason):
    result = _analyze(**overrides)

    assert result.status == STATUS_UNAVAILABLE
    assert result.return_percent is None
    assert result.hurdle_return_percent is None
    assert result.annualized_return_percent is None
    assert result.shortfall_amount is None
    assert all(item.required_annual_return_percent is None for item in result.required_return_by_horizon)
    assert any(reason in item.lower() for item in result.reasons)


def test_total_loss_is_reported_without_inventing_a_catch_up_rate():
    result = _analyze(market_value=0)

    assert result.status == STATUS_BELOW
    assert result.return_percent == pytest.approx(-100)
    assert result.annualized_return_percent == pytest.approx(-100)
    assert all(item.required_annual_return_percent is None for item in result.required_return_by_horizon)


def test_extreme_holding_periods_do_not_overflow():
    result = _analyze(days_held=10**7, required_annual_return_percent=100)

    assert result.status == STATUS_UNAVAILABLE
    assert result.hurdle_return_percent is None
    assert any("too long" in reason for reason in result.reasons)


def test_required_return_to_catch_up_keeps_the_holding_on_the_hurdle_path():
    result = _analyze()

    assert [item.years for item in result.required_return_by_horizon] == [1, 3, 5]
    for item in result.required_return_by_horizon:
        reached = 110 * (1 + item.required_annual_return_percent / 100) ** item.years
        assert reached == pytest.approx(_path(100, 730 + 365 * item.years))


def test_years_to_catch_up_exist_only_for_an_explicit_assumed_return():
    path = _path(100, 730)

    assert _analyze(market_value=96).years_to_catch_up is None

    result = _analyze(market_value=96, holding_assumed_return_percent=12)
    assert result.holding_assumed_return_percent == 12
    assert result.years_to_catch_up == pytest.approx(log(path / 96) / (log(1.12) - log(1.07)))
    assert 96 * (1.12 / 1.07) ** result.years_to_catch_up == pytest.approx(path)

    slow = _analyze(market_value=96, holding_assumed_return_percent=7)
    assert slow.years_to_catch_up is None
    assert any("would not catch up" in reason for reason in slow.reasons)

    ahead = _analyze(market_value=130, holding_assumed_return_percent=12)
    assert ahead.years_to_catch_up == 0


def test_replacement_months_are_scenario_arithmetic_from_an_assumed_return():
    assert _analyze().replacement_months_to_hurdle_gain is None

    result = _analyze(replacement_assumed_return_percent=15)
    assert result.replacement_assumed_return_percent == 15
    assert result.replacement_months_to_hurdle_gain == pytest.approx(12 * log(1.07) / log(1.15))
    assert 1.15 ** (result.replacement_months_to_hurdle_gain / 12) == pytest.approx(1.07)
    assert "not forecasts" in result.note

    flat = _analyze(replacement_assumed_return_percent=0)
    assert flat.replacement_months_to_hurdle_gain is None
    assert any("never reaches" in reason for reason in flat.reasons)

    assert _analyze(
        required_annual_return_percent=0, replacement_assumed_return_percent=5
    ).replacement_months_to_hurdle_gain == 0


def test_replacement_months_do_not_depend_on_the_holding_data():
    result = HurdleAnalyzer().analyze("AAA", replacement_assumed_return_percent=15)

    assert result.status == STATUS_UNAVAILABLE
    assert result.replacement_months_to_hurdle_gain == pytest.approx(12 * log(1.07) / log(1.15))


def test_outlook_compares_analyst_target_upside_with_the_hurdle():
    assert _analyze(forward_return_percent=3).outlook_status == STATUS_BELOW
    assert _analyze(forward_return_percent=7).outlook_status == STATUS_MEETS
    assert _analyze(forward_return_percent=12).outlook_status == STATUS_MEETS

    missing = _analyze()
    assert missing.outlook_status == STATUS_UNAVAILABLE
    assert missing.forward_return_percent is None
    assert any("target upside" in reason.lower() for reason in missing.reasons)


def test_multiple_lots_are_measured_from_their_own_entry_dates():
    lots = [HoldingLot(100, 1000), HoldingLot(300, 200)]
    result = HurdleAnalyzer().analyze("AAA", market_value=420, dividends=0, lots=lots)

    expected_path = _path(100, 1000) + _path(300, 200)
    assert result.lot_count == 2
    assert result.days_held == 400
    assert result.status == STATUS_BELOW
    assert result.hurdle_return_percent == pytest.approx((expected_path / 400 - 1) * 100)
    assert result.shortfall_amount == pytest.approx(expected_path - 420)
    # The earliest entry date applied to every dollar would overstate the hurdle.
    assert result.hurdle_return_percent < (_path(400, 1000) / 400 - 1) * 100

    rate = result.annualized_return_percent / 100
    assert 100 * (1 + rate) ** (1000 / 365) + 300 * (1 + rate) ** (200 / 365) == pytest.approx(420)
    assert -100 < result.annualized_return_percent < 7


def test_multiple_lots_with_a_negative_overall_return_annualize_below_zero():
    lots = [HoldingLot(100, 1000), HoldingLot(300, 200)]
    result = HurdleAnalyzer().analyze("AAA", market_value=300, dividends=0, lots=lots)

    assert result.annualized_return_percent < 0
    rate = result.annualized_return_percent / 100
    assert 100 * (1 + rate) ** (1000 / 365) + 300 * (1 + rate) ** (200 / 365) == pytest.approx(300)


def test_a_single_lot_matches_the_scalar_inputs():
    scalar = _analyze()
    lot = HurdleAnalyzer().analyze(
        "AAA", market_value=110, dividends=0, lots=[HoldingLot(100, 730)]
    )

    assert lot == scalar


def test_lots_take_precedence_over_scalar_cost_and_days():
    result = HurdleAnalyzer().analyze(
        "AAA",
        cost_basis=1,
        days_held=1,
        market_value=420,
        dividends=0,
        lots=[HoldingLot(100, 1000), HoldingLot(300, 200)],
    )

    assert result.lot_count == 2
    assert result.days_held == 400


def test_incomplete_lots_leave_the_hurdle_unavailable_with_deduplicated_reasons():
    missing_date = HurdleAnalyzer().analyze(
        "AAA",
        market_value=420,
        dividends=0,
        lots=[HoldingLot(100, 1000), HoldingLot(300, None), HoldingLot(50, None)],
    )
    assert missing_date.status == STATUS_UNAVAILABLE
    assert missing_date.days_held is None
    assert any("at least one lot" in reason for reason in missing_date.reasons)
    assert len(set(missing_date.reasons)) == len(missing_date.reasons)

    missing_cost = HurdleAnalyzer().analyze(
        "AAA",
        market_value=420,
        dividends=0,
        lots=[HoldingLot(100, 1000), HoldingLot(None, 200)],
    )
    assert missing_cost.status == STATUS_UNAVAILABLE
    assert any("every lot" in reason for reason in missing_cost.reasons)

    empty = HurdleAnalyzer().analyze("AAA", market_value=420, dividends=0, lots=[])
    assert empty.status == STATUS_UNAVAILABLE
    assert empty.lot_count == 0
    assert any("No holding lots" in reason for reason in empty.reasons)


def _hurdle(**overrides):
    return _analyze(forward_return_percent=3, **overrides)


def test_dead_money_without_a_hurdle_keeps_the_legacy_verdict_and_confidence():
    legacy = DeadMoneyDetector().assess("AAA", cps=30, total_return_percent=-10)

    assert legacy.is_dead_money is True
    assert legacy.confidence == pytest.approx(2 / 3)
    assert DeadMoneyDetector().assess("AAA", cps=80, total_return_percent=-10).is_dead_money is False
    assert DeadMoneyDetector().assess("AAA", cps=None).is_dead_money is None


def test_below_the_hurdle_with_a_weak_outlook_is_dead_money_even_without_a_cps():
    hurdle = _hurdle()
    assert (hurdle.status, hurdle.outlook_status) == (STATUS_BELOW, STATUS_BELOW)

    result = DeadMoneyDetector().assess("AAA", cps=None, hurdle=hurdle)

    assert result.is_dead_money is True
    assert result.confidence == pytest.approx(2 / 5)
    assert any("7% per year hurdle path" in reason for reason in result.reasons)
    assert any("Analyst target upside" in reason for reason in result.reasons)


def test_weak_cps_below_the_hurdle_is_dead_money_without_an_outlook():
    result = DeadMoneyDetector().assess(
        "AAA", cps=30, hurdle=_analyze(forward_return_percent=None)
    )

    assert result.is_dead_money is True
    assert result.confidence == pytest.approx(2 / 5)


def test_below_the_hurdle_alone_does_not_override_a_productive_cps():
    result = DeadMoneyDetector().assess(
        "AAA", cps=75, hurdle=_analyze(forward_return_percent=None)
    )

    assert result.is_dead_money is False
    assert any("hurdle path" in reason for reason in result.reasons)


def test_below_the_hurdle_with_no_other_evidence_is_not_reported_as_dead_money():
    result = DeadMoneyDetector().assess(
        "AAA", cps=None, hurdle=_analyze(forward_return_percent=None)
    )

    assert result.is_dead_money is None
    assert any("no productivity or outlook evidence" in reason for reason in result.reasons)


def test_meeting_the_hurdle_is_not_dead_money_and_says_so():
    result = DeadMoneyDetector().assess("AAA", cps=75, hurdle=_hurdle(market_value=130))

    assert result.is_dead_money is False
    assert any("meets the 7% per year hurdle path" in reason for reason in result.reasons)


def test_unavailable_hurdle_keeps_the_legacy_verdict_but_lowers_confidence():
    young = _analyze(market_value=90, days_held=100, forward_return_percent=None)
    assert young.status == STATUS_UNAVAILABLE

    result = DeadMoneyDetector().assess(
        "AAA", cps=30, total_return_percent=-10, hurdle=young
    )

    assert result.is_dead_money is True
    assert result.confidence == pytest.approx(2 / 5)
    assert any("confidence is reduced" in reason for reason in result.reasons)


def test_dead_money_reasons_are_safe_when_hurdle_figures_are_missing():
    hurdle = replace(
        _hurdle(), return_percent=None, hurdle_return_percent=None, forward_return_percent=None
    )

    result = DeadMoneyDetector().assess("AAA", cps=30, hurdle=hurdle)

    assert result.is_dead_money is True
    assert any("n/a" in reason for reason in result.reasons)


def test_lifecycle_reports_price_return_without_dividends_and_total_return_with_them():
    analyzer = PositionLifecycleAnalyzer()

    price_only = analyzer.summarize_position(
        "AAA", entry_date="2025-01-01", cost_basis=100, market_value=90
    )
    assert price_only.price_return_percent == pytest.approx(-10)
    assert price_only.total_return_percent is None

    total = analyzer.summarize_position(
        "AAA", entry_date="2025-01-01", cost_basis=100, market_value=90, dividends=4
    )
    assert total.price_return_percent == pytest.approx(-10)
    assert total.total_return_percent == pytest.approx(-6)

    zero_cost = analyzer.summarize_position(
        "AAA", cost_basis=0, market_value=90, dividends=1
    )
    assert zero_cost.price_return_percent is None
    assert zero_cost.total_return_percent is None


def test_days_since_accepts_dates_datetimes_and_iso_strings():
    analyzer = PositionLifecycleAnalyzer()
    analyzer.snapshot_time = datetime(2027, 1, 1, tzinfo=timezone.utc)

    assert analyzer.days_since("2025-01-01T00:00:00+00:00") == 730
    assert analyzer.days_since(date(2025, 1, 1)) == 730
    assert analyzer.days_since(datetime(2025, 1, 1, 12, tzinfo=timezone.utc)) == 730
    assert analyzer.days_since("2028-01-01") == 0
    assert analyzer.days_since("not a date") is None
    assert analyzer.days_since(None) is None

import json
import math
from datetime import date, datetime, timedelta

import pytest

from stockscanner.pip.research_scores import (
    RESEARCH_SCORE_RULES,
    RESEARCH_SCORES_VERSION,
    build_research_scores,
    map_value_to_score,
    score_relative_performance,
    score_revisions,
    score_technical_health,
    score_tsr,
)

END = date(2026, 1, 30)
TOO_BIG_FOR_A_FLOAT = 10**400


def daily(values, end=END):
    """One close per calendar day, ending on `end`."""
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=offset), float(value)) for offset, value in enumerate(values)]


def flat(count, value=100.0, **replacements):
    """`count` equal closes; `replacements` maps a position counted from the last close (1 = last) to a value."""
    values = [value] * count
    for position, replacement in replacements.items():
        values[-int(position.lstrip("p"))] = replacement
    return values


def revisions(up, down, **extra):
    return {"up_last_30_days": up, "down_last_30_days": down, **extra}


def test_every_limit_and_minimum_lives_in_one_versioned_table():
    assert RESEARCH_SCORES_VERSION == "research-1"
    assert RESEARCH_SCORE_RULES == {
        "version": "research-1",
        "tsr": {"limit_percent": 40.0, "min_history_days": 330},
        "relative_performance": {"limit_points": 20.0, "min_history_days": 330},
        "revisions": {"min_revisions": 3, "periods": ("0q", "+1q", "0y", "+1y")},
        "technical_health": {
            "min_closes": 200,
            "long_average": {"days": 200, "limit_percent": 15.0},
            "short_average": {"days": 50, "limit_percent": 10.0},
            "high": {"window_days": 365, "limit_percent": 40.0},
        },
    }


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        (0, 40, 50.0),
        (20, 40, 75.0),
        (-20, 40, 25.0),
        (12, 40, 65.0),
        (-6, 20, 35.0),
        (40, 40, 100.0),
        (-40, 40, 0.0),
        (39.9, 40, 99.875),
        (-39.9, 40, 0.125),
        (40.1, 40, 100.0),
        (-40.1, 40, 0.0),
        (1e9, 40, 100.0),
        (-1e9, 40, 0.0),
        (0.5, 1, 75.0),
    ],
)
def test_the_mapping_is_linear_around_a_neutral_fifty_and_clamped_at_the_limits(value, limit, expected):
    assert map_value_to_score(value, limit) == pytest.approx(expected)


@pytest.mark.parametrize(
    "limit",
    [0, -1, math.nan, math.inf, pytest.param(TOO_BIG_FOR_A_FLOAT, id="too-big-for-a-float")],
)
def test_the_mapping_rejects_a_limit_that_is_not_positive_and_finite(limit):
    with pytest.raises(ValueError):
        map_value_to_score(1.0, limit)


@pytest.mark.parametrize(
    "value",
    [
        math.nan,
        math.inf,
        -math.inf,
        pytest.param(TOO_BIG_FOR_A_FLOAT, id="too-big-for-a-float"),
        pytest.param(-TOO_BIG_FOR_A_FLOAT, id="too-small-for-a-float"),
    ],
)
def test_the_mapping_rejects_a_value_that_is_not_finite(value):
    with pytest.raises(ValueError):
        map_value_to_score(value, 40)


# ---- TSR


def test_tsr_worked_example():
    assert score_tsr(12.0, 364) == {
        "score": 65.0,
        "raw": {"return_percent": 12.0, "history_days": 364},
        "reason": None,
    }


@pytest.mark.parametrize(
    ("return_percent", "expected"),
    [
        (40.0, 100.0),
        (38.0, 97.5),
        (4.0, 55.0),
        (0.0, 50.0),
        (-4.0, 45.0),
        (-38.0, 2.5),
        (-40.0, 0.0),
        (41.0, 100.0),
        (-41.0, 0.0),
        (400.0, 100.0),
        (-400.0, 0.0),
    ],
)
def test_tsr_reaches_100_at_plus_40_percent_and_0_at_minus_40_percent(return_percent, expected):
    assert score_tsr(return_percent, 365)["score"] == expected


def test_tsr_needs_330_days_of_history_and_never_annualises_a_short_one():
    assert score_tsr(20.0, 330)["score"] == 75.0
    short = score_tsr(20.0, 329)
    assert short["score"] is None
    assert short["raw"] == {"return_percent": 20.0, "history_days": 329}
    assert short["reason"] == "Yahoo history covers 329 days; at least 330 are needed to score a 1-year total return."
    assert score_tsr(20.0, 0)["score"] is None
    assert score_tsr(20.0, -5)["score"] is None


@pytest.mark.parametrize(
    ("return_percent", "history_days"),
    [
        (None, 365),
        (20.0, None),
        (None, None),
        (math.nan, 365),
        (math.inf, 365),
        (20.0, math.nan),
        (20.0, math.inf),
        (True, 365),
        (20.0, True),
        ("20", 365),
        (20.0, "365"),
        (20.0, 364.5),
        pytest.param(TOO_BIG_FOR_A_FLOAT, 365, id="return-too-big-for-a-float"),
        pytest.param(20.0, TOO_BIG_FOR_A_FLOAT, id="days-too-big-for-a-float"),
    ],
)
def test_tsr_is_not_available_without_a_usable_return_and_history(return_percent, history_days):
    result = score_tsr(return_percent, history_days)
    assert result["score"] is None
    assert result["reason"]
    json.dumps(result, allow_nan=False)


def test_tsr_does_not_echo_unusable_inputs():
    result = score_tsr(math.nan, True)
    assert result["raw"] == {"return_percent": None, "history_days": None}


def test_the_reasons_for_missing_inputs_read_as_plain_text():
    assert score_tsr(None, None)["reason"] == (
        "Yahoo did not return enough price history to measure a 1-year total return."
    )
    assert score_relative_performance(None, None)["reason"] == (
        "Yahoo did not return enough overlapping price history for this symbol and SPY to compare their returns."
    )
    assert score_revisions(None)["reason"] == "Yahoo did not provide 30-day EPS revision counts for this symbol."
    assert score_tsr(5.0, 1)["reason"] == (
        "Yahoo history covers 1 day; at least 330 are needed to score a 1-year total return."
    )


def test_numbers_from_numpy_are_accepted_and_come_back_as_plain_python_numbers():
    numpy = pytest.importorskip("numpy")
    result = score_tsr(numpy.float64(12.0), numpy.int64(364))
    assert result["score"] == 65.0
    json.dumps(result, allow_nan=False)
    assert type(result["raw"]["history_days"]) is int
    assert type(result["raw"]["return_percent"]) is float


def test_tsr_shows_the_return_to_two_decimals():
    assert score_tsr(12.3456, 364)["raw"]["return_percent"] == 12.35


def test_a_return_that_rounds_to_zero_is_shown_as_a_plain_zero():
    shown = score_tsr(-0.001, 365)["raw"]["return_percent"]
    assert shown == 0.0
    assert math.copysign(1.0, shown) == 1.0


# ---- relative performance


def test_relative_performance_worked_example():
    assert score_relative_performance(-6.0, 364) == {
        "score": 35.0,
        "raw": {"gap_points": -6.0, "history_days": 364},
        "reason": None,
    }


def test_relative_performance_shows_the_gap_to_two_decimals():
    assert score_relative_performance(-6.7891, 364)["raw"]["gap_points"] == -6.79


@pytest.mark.parametrize(
    ("gap_points", "expected"),
    [
        (20.0, 100.0),
        (19.0, 97.5),
        (10.0, 75.0),
        (0.0, 50.0),
        (-10.0, 25.0),
        (-19.0, 2.5),
        (-20.0, 0.0),
        (21.0, 100.0),
        (-21.0, 0.0),
        (500.0, 100.0),
        (-500.0, 0.0),
    ],
)
def test_relative_performance_reaches_100_at_plus_20_points_and_0_at_minus_20_points(gap_points, expected):
    assert score_relative_performance(gap_points, 365)["score"] == expected


def test_relative_performance_needs_330_days_of_shared_history():
    assert score_relative_performance(10.0, 330)["score"] == 75.0
    short = score_relative_performance(10.0, 329)
    assert short["score"] is None
    assert short["raw"] == {"gap_points": 10.0, "history_days": 329}
    assert short["reason"] == (
        "This symbol and SPY share 329 days of price history; at least 330 are needed to score performance against SPY."
    )


@pytest.mark.parametrize(
    ("gap_points", "history_days"),
    [(None, 365), (5.0, None), (math.nan, 365), (math.inf, 365), (5.0, math.nan), (True, 365), (5.0, True), ("5", 365)],
)
def test_relative_performance_is_not_available_without_a_usable_gap_and_history(gap_points, history_days):
    result = score_relative_performance(gap_points, history_days)
    assert result["score"] is None
    assert result["reason"]
    assert "SPY" in result["reason"]
    json.dumps(result, allow_nan=False)


# ---- analyst revisions


def test_revisions_worked_example_sums_the_periods_in_the_rules_order():
    periods = {"+1q": revisions(1, 0), "0q": revisions(3, 1)}
    assert score_revisions(periods) == {
        "score": 80.0,
        "raw": {"up": 4, "down": 1, "breadth": 0.6, "periods_counted": ["0q", "+1q"]},
        "reason": None,
    }


@pytest.mark.parametrize(
    ("up", "down", "expected"),
    [
        (3, 0, 100.0),
        (0, 3, 0.0),
        (2, 2, 50.0),
        (1, 2, 33.3),
        (2, 1, 66.7),
        (9, 1, 90.0),
        (1, 9, 10.0),
        (10, 0, 100.0),
    ],
)
def test_revisions_score_the_breadth_of_up_against_down(up, down, expected):
    assert score_revisions({"0q": revisions(up, down)})["score"] == expected


def test_revisions_show_the_breadth_to_four_decimals():
    assert score_revisions({"0q": revisions(2, 1)})["raw"]["breadth"] == 0.3333


def test_revisions_add_up_all_four_periods():
    periods = {"0q": revisions(1, 0), "+1q": revisions(0, 1), "0y": revisions(2, 0), "+1y": revisions(0, 2)}
    result = score_revisions(periods)
    assert result["raw"] == {"up": 3, "down": 3, "breadth": 0.0, "periods_counted": ["0q", "+1q", "0y", "+1y"]}
    assert result["score"] == 50.0


def test_revisions_need_three_in_total():
    assert score_revisions({"0q": revisions(2, 1)})["score"] == pytest.approx(66.7)
    thin = score_revisions({"0q": revisions(1, 1)})
    assert thin["score"] is None
    assert thin["raw"] == {"up": 1, "down": 1, "breadth": None, "periods_counted": ["0q"]}
    assert thin["reason"] == (
        "Yahoo shows 2 EPS revisions in the last 30 days; at least 3 are needed to score analyst revisions."
    )
    assert score_revisions({"0q": revisions(1, 0)})["reason"] == (
        "Yahoo shows 1 EPS revision in the last 30 days; at least 3 are needed to score analyst revisions."
    )
    assert score_revisions({"0q": revisions(0, 0)})["reason"] == (
        "Yahoo shows 0 EPS revisions in the last 30 days; at least 3 are needed to score analyst revisions."
    )


def test_revisions_use_only_the_last_30_day_counts_and_only_the_four_named_periods():
    periods = {
        "0q": revisions(1, 1, up_last_7_days=9, down_last_7_days=0),
        "-1q": revisions(5, 0),
        "5y": revisions(5, 0),
    }
    result = score_revisions(periods)
    assert result["score"] is None
    assert result["raw"]["up"] == 1 and result["raw"]["down"] == 1
    assert result["raw"]["periods_counted"] == ["0q"]


@pytest.mark.parametrize("bad", [None, -1, 2.5, math.nan, math.inf, True, "3", [3]])
def test_a_period_with_an_unusable_count_is_not_counted_at_all(bad):
    for broken in (revisions(bad, 1), revisions(1, bad)):
        result = score_revisions({"0q": broken, "+1q": revisions(3, 0)})
        assert result["raw"]["periods_counted"] == ["+1q"]
        assert (result["raw"]["up"], result["raw"]["down"]) == (3, 0)
        assert result["score"] == 100.0


def test_a_missing_count_is_not_read_as_zero():
    result = score_revisions({"0q": {"up_last_30_days": 5}, "+1q": {"down_last_30_days": 5}})
    assert result["score"] is None
    assert result["raw"] == {"up": 0, "down": 0, "breadth": None, "periods_counted": []}


def test_whole_number_floats_are_valid_counts():
    assert score_revisions({"0q": revisions(3.0, 1.0)})["raw"]["up"] == 3


@pytest.mark.parametrize("periods", [None, {}, [], "0q", 5, {"0q": None}, {"0q": "3 up"}, {"0q": [3, 1]}])
def test_revisions_are_not_available_without_usable_periods(periods):
    result = score_revisions(periods)
    assert result["score"] is None
    assert result["raw"] == {"up": 0, "down": 0, "breadth": None, "periods_counted": []}
    assert "did not provide" in result["reason"]
    json.dumps(result, allow_nan=False)


# ---- technical health


def test_a_flat_year_is_level_with_both_averages_and_at_its_high():
    result = score_technical_health(daily(flat(250)))
    assert result == {
        "score": 66.7,
        "raw": {
            "closes": 250,
            "long_average_days": 200,
            "close_vs_long_average_percent": 0.0,
            "short_average_days": 50,
            "close_vs_short_average_percent": 0.0,
            "high_window_days": 365,
            "below_high_percent": 0.0,
            "parts": {"long_average": 50.0, "short_average": 50.0, "high": 100.0},
        },
        "reason": None,
    }


def test_the_long_average_covers_exactly_the_last_200_closes():
    # The 200th and 201st closes from the end are low. Only the first of them is inside a 200-close average.
    result = score_technical_health(daily(flat(260, p200=50.0, p201=50.0)))
    assert result["raw"]["close_vs_long_average_percent"] == 0.25
    assert result["raw"]["close_vs_short_average_percent"] == 0.0
    assert result["raw"]["parts"] == {"long_average": 50.8, "short_average": 50.0, "high": 100.0}
    assert result["score"] == 66.9


def test_the_short_average_covers_exactly_the_last_50_closes():
    result = score_technical_health(daily(flat(260, p50=50.0, p51=50.0)))
    assert result["raw"]["close_vs_short_average_percent"] == 1.01
    assert result["raw"]["close_vs_long_average_percent"] == 0.5
    assert result["raw"]["parts"] == {"long_average": 51.7, "short_average": 55.1, "high": 100.0}
    assert result["score"] == 68.9


def test_the_52_week_high_covers_closes_up_to_365_days_before_the_last_one():
    spike = 140.0
    included = flat(400)
    included[399 - 365] = spike
    excluded = flat(400)
    excluded[399 - 366] = spike

    inside = score_technical_health(daily(included))
    assert inside["raw"]["below_high_percent"] == 28.57
    assert inside["raw"]["parts"]["high"] == 28.6
    assert inside["score"] == 42.9

    outside = score_technical_health(daily(excluded))
    assert outside["raw"]["below_high_percent"] == 0.0
    assert outside["raw"]["parts"]["high"] == 100.0
    assert outside["score"] == 66.7


def test_the_three_parts_are_averaged_with_equal_weight():
    # Last close 112 above a flat 100: well above both averages (long part 89.8, short part capped at 100) and at its high.
    result = score_technical_health(daily(flat(250, p1=112.0)))
    assert result["raw"]["parts"] == {"long_average": 89.8, "short_average": 100.0, "high": 100.0}
    assert result["score"] == 96.6


def test_a_strong_uptrend_at_its_high_scores_100_and_a_collapse_scores_0():
    rising = score_technical_health(daily(range(1, 251)))
    assert rising["raw"]["parts"] == {"long_average": 100.0, "short_average": 100.0, "high": 100.0}
    assert rising["score"] == 100.0

    falling = score_technical_health(daily(range(250, 0, -1)))
    assert falling["raw"]["parts"] == {"long_average": 0.0, "short_average": 0.0, "high": 0.0}
    assert falling["score"] == 0.0


@pytest.mark.parametrize(
    ("last", "part"),
    [(115.0, 100.0), (107.5, 75.0), (100.0, 50.0), (92.5, 25.0), (85.0, 0.0), (130.0, 100.0), (70.0, 0.0)],
)
def test_the_long_average_part_reaches_its_limits_at_15_percent_either_side(last, part):
    # The 200 closes average exactly 100, so the last close sits (last - 100)% from its long average.
    earlier = (200 * 100.0 - last) / 199
    result = score_technical_health(daily([earlier] * 199 + [last]))
    assert result["raw"]["parts"]["long_average"] == part


@pytest.mark.parametrize(
    ("last", "part"),
    [(110.0, 100.0), (105.0, 75.0), (100.0, 50.0), (95.0, 25.0), (90.0, 0.0), (120.0, 100.0), (80.0, 0.0)],
)
def test_the_short_average_part_reaches_its_limits_at_10_percent_either_side(last, part):
    # The last 50 closes average exactly 100.
    recent = (50 * 100.0 - last) / 49
    result = score_technical_health(daily([100.0] * 150 + [recent] * 49 + [last]))
    assert result["raw"]["parts"]["short_average"] == part


@pytest.mark.parametrize(
    ("last", "below", "part"),
    [(100.0, 0.0, 100.0), (90.0, 10.0, 75.0), (80.0, 20.0, 50.0), (70.0, 30.0, 25.0), (60.0, 40.0, 0.0), (50.0, 50.0, 0.0)],
)
def test_the_high_part_falls_from_100_at_the_high_to_0_at_40_percent_below_it(last, below, part):
    result = score_technical_health(daily([100.0] * 199 + [last]))
    assert result["raw"]["below_high_percent"] == below
    assert result["raw"]["parts"]["high"] == part


def test_the_first_close_on_or_after_200_is_enough_and_199_is_not():
    enough = score_technical_health(daily(flat(200)))
    assert enough["score"] == 66.7
    assert enough["raw"]["closes"] == 200

    thin = score_technical_health(daily(flat(199)))
    assert thin["score"] is None
    assert thin["raw"] == {"closes": 199}
    assert thin["reason"] == "Yahoo returned 199 daily closes; at least 200 are needed to score technical health."
    assert score_technical_health([(END, 100.0)])["reason"] == (
        "Yahoo returned 1 daily close; at least 200 are needed to score technical health."
    )


def test_the_history_order_does_not_matter():
    points = daily(flat(260, p200=50.0, p201=50.0))
    assert score_technical_health(list(reversed(points))) == score_technical_health(points)


def test_dates_with_a_time_of_day_are_read_as_the_day_they_fall_on():
    points = daily(flat(260, p200=50.0, p201=50.0))
    stamped = [(datetime(day.year, day.month, day.day, 16, 0), price) for day, price in points]
    assert score_technical_health(stamped) == score_technical_health(points)


def test_plain_dates_and_dates_with_a_time_of_day_can_be_mixed_in_one_history():
    points = daily(flat(260, p200=50.0, p201=50.0))
    mixed = [
        (datetime(day.year, day.month, day.day, 16, 0) if index % 2 else day, price)
        for index, (day, price) in enumerate(points)
    ]
    assert score_technical_health(mixed) == score_technical_health(points)


@pytest.mark.parametrize(
    "bad_day",
    ["2026-01-31", 20260131, None, 1.5, ("2026", 1, 31)],
    ids=["text", "number", "none", "float", "tuple"],
)
def test_a_close_without_a_real_date_is_ignored_not_counted(bad_day):
    thin = score_technical_health(daily(flat(199)) + [(bad_day, 100.0)])
    assert thin["score"] is None
    assert thin["raw"] == {"closes": 199}


def test_closes_that_are_not_positive_and_finite_are_ignored_not_counted():
    points = daily(flat(201))
    assert score_technical_health(points)["raw"]["closes"] == 201
    assert score_technical_health(points[:-1] + [(END + timedelta(days=1), 0.0)])["raw"]["closes"] == 200
    for bad in (0.0, -5.0, math.nan, math.inf, None, True, "100"):
        thin = score_technical_health(daily(flat(199)) + [(END + timedelta(days=1), bad)])
        assert thin["score"] is None, bad
        assert thin["raw"] == {"closes": 199}, bad


@pytest.mark.parametrize("points", [None, [], [(END, 100.0)], [("not a pair",)], 5])
def test_technical_health_is_not_available_without_enough_history(points):
    result = score_technical_health(points)
    assert result["score"] is None
    assert result["reason"]
    json.dumps(result, allow_nan=False)


# ---- the four together


def test_all_four_scores_are_built_from_one_set_of_inputs():
    scores = build_research_scores(
        return_percent=12.0,
        history_days=364,
        relative_gap_points=-6.0,
        relative_history_days=364,
        revision_periods={"0q": revisions(3, 1), "+1q": revisions(1, 0)},
        points=daily(flat(250)),
    )
    assert list(scores) == ["version", "tsr", "relative_performance", "revisions", "technical_health"]
    assert scores["version"] == "research-1"
    assert scores["tsr"]["score"] == 65.0
    assert scores["relative_performance"]["score"] == 35.0
    assert scores["revisions"]["score"] == 80.0
    assert scores["technical_health"]["score"] == 66.7


def test_each_score_is_judged_on_its_own_inputs():
    scores = build_research_scores(
        return_percent=None,
        history_days=None,
        relative_gap_points=10.0,
        relative_history_days=365,
        revision_periods={},
        points=daily(flat(250)),
    )
    assert scores["tsr"]["score"] is None
    assert scores["relative_performance"]["score"] == 75.0
    assert scores["revisions"]["score"] is None
    assert scores["technical_health"]["score"] == 66.7


def test_nothing_is_replaced_by_a_neutral_50_when_there_is_no_data():
    scores = build_research_scores(
        return_percent=None,
        history_days=None,
        relative_gap_points=None,
        relative_history_days=None,
        revision_periods=None,
        points=None,
    )
    assert [scores[name]["score"] for name in ("tsr", "relative_performance", "revisions", "technical_health")] == [None] * 4
    assert all(scores[name]["reason"] for name in ("tsr", "relative_performance", "revisions", "technical_health"))
    json.dumps(scores, allow_nan=False)

from __future__ import annotations

import pytest

from stockscanner.pip.scoring import (
    SELL_SCORE_DIRECTION,
    SELL_SCORE_INVERTED_INPUTS,
    SELL_SCORE_WEIGHTS,
    calculate_cps,
    calculate_sell_score,
    calculate_sell_score_result,
)

HEALTH_INPUTS = (
    "tsr",
    "relative_performance",
    "revisions",
    "dividend_quality",
    "technical_health",
    "earnings_growth",
)


def test_cps_formula():
    score = calculate_cps(
        tsr=80,
        relative_performance=70,
        dividend_growth=60,
        earnings_growth=75,
        analyst_revisions=65,
    )
    assert 60 <= score <= 75


def test_sell_score_formula():
    score = calculate_sell_score(
        tsr=80,
        relative_performance=65,
        revisions=70,
        dividend_quality=50,
        technical_health=45,
        earnings_growth=55,
        opportunity_cost=80,
    )
    # The six health inputs count as 100 minus their score (20, 35, 30, 50, 55, 45);
    # opportunity cost counts as entered.
    expected = (20 * 20 + 20 * 35 + 20 * 30 + 15 * 50 + 15 * 55 + 10 * 45 + 15 * 80) / 115
    assert score == pytest.approx(expected)
    assert score == pytest.approx(4925 / 115)


def test_the_sell_score_direction_and_flipped_inputs_are_documented_constants():
    assert SELL_SCORE_DIRECTION == "higher_means_sell"
    assert SELL_SCORE_INVERTED_INPUTS == HEALTH_INPUTS
    assert set(SELL_SCORE_INVERTED_INPUTS) | {"opportunity_cost"} == set(SELL_SCORE_WEIGHTS)
    assert "opportunity_cost" not in SELL_SCORE_INVERTED_INPUTS


@pytest.mark.parametrize("name", HEALTH_INPUTS)
def test_a_healthier_input_lowers_the_sell_score(name):
    weak = calculate_sell_score_result({name: 20})
    strong = calculate_sell_score_result({name: 80})

    assert weak.score == pytest.approx(80)
    assert strong.score == pytest.approx(20)
    assert weak.component_scores == {name: pytest.approx(80)}
    assert strong.component_scores == {name: pytest.approx(20)}
    assert strong.confidence == pytest.approx(SELL_SCORE_WEIGHTS[name] / 115)


def test_a_larger_opportunity_cost_raises_the_sell_score():
    low = calculate_sell_score_result({"opportunity_cost": 20})
    high = calculate_sell_score_result({"opportunity_cost": 80})

    assert low.score == pytest.approx(20)
    assert high.score == pytest.approx(80)
    assert high.component_scores == {"opportunity_cost": 80}
    assert high.confidence == pytest.approx(15 / 115)


def test_a_healthy_holding_scores_zero_and_an_unhealthy_one_scores_one_hundred():
    healthy = {**{name: 100 for name in HEALTH_INPUTS}, "opportunity_cost": 0}
    unhealthy = {**{name: 0 for name in HEALTH_INPUTS}, "opportunity_cost": 100}

    assert calculate_sell_score_result(healthy).score == pytest.approx(0)
    assert calculate_sell_score_result(unhealthy).score == pytest.approx(100)
    assert calculate_sell_score_result(healthy).confidence == 1


def test_a_neutral_holding_scores_fifty_in_either_direction():
    assert calculate_sell_score_result({name: 50 for name in SELL_SCORE_WEIGHTS}).score == pytest.approx(50)


def test_inputs_are_clamped_before_they_are_flipped():
    assert calculate_sell_score_result({"tsr": 150}).score == pytest.approx(0)
    assert calculate_sell_score_result({"tsr": -50}).score == pytest.approx(100)
    assert calculate_sell_score_result({"opportunity_cost": 150}).score == pytest.approx(100)
    assert calculate_sell_score_result({"opportunity_cost": -50}).score == pytest.approx(0)


def test_missing_and_invalid_inputs_are_left_out_not_flipped_into_scores():
    result = calculate_sell_score_result({
        "tsr": None,
        "relative_performance": float("nan"),
        "revisions": "not a number",
        "opportunity_cost": 40,
    })

    assert result.component_scores == {"opportunity_cost": 40}
    assert result.score == pytest.approx(40)
    assert result.confidence == pytest.approx(15 / 115)
    assert result.reasons[:3] == (
        "Tsr data is missing.",
        "Relative Performance data is invalid.",
        "Revisions data is invalid.",
    )
    assert len(result.reasons) == 6


def test_custom_weights_flip_the_same_inputs():
    result = calculate_sell_score_result(
        {"tsr": 80, "opportunity_cost": 80},
        {"tsr": 1, "opportunity_cost": 1},
    )

    assert result.score == pytest.approx((20 + 80) / 2)


def test_the_capital_productivity_score_is_not_flipped():
    score = calculate_cps(
        tsr=90,
        relative_performance=None,
        dividend_growth=None,
        earnings_growth=None,
        analyst_revisions=None,
    )

    assert score == 90


def test_decision_engine_sell_recommendation():
    from stockscanner.pip.decision_engine import DecisionEngine
    from stockscanner.pip.repository import InMemoryPortfolioRepository

    engine = DecisionEngine(repository=InMemoryPortfolioRepository())
    result = engine.analyze_position(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        tsr=80,
        relative_performance=30,
        dividend_growth=40,
        earnings_growth=35,
        analyst_revisions=30,
        dividend_quality=35,
        technical_health=25,
        opportunity_cost=80,
        revisions=40,
        recommendation_threshold=60,
    )

    assert result.recommendation in {"sell", "partial-sell", "watch", "hold"}
    assert result.sell_score >= 0
    assert isinstance(result.rationale, list)

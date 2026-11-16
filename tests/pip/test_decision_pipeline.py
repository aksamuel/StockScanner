from __future__ import annotations

import pytest

from stockscanner.pip.decision_engine import DecisionEngine


def _analyze(health, opportunity_cost, **overrides):
    """Run one holding whose every health score is `health` (higher means healthier)."""
    engine = DecisionEngine()
    result = engine.analyze_position(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        tsr=health,
        relative_performance=health,
        dividend_growth=health,
        earnings_growth=health,
        analyst_revisions=health,
        dividend_quality=health,
        technical_health=health,
        opportunity_cost=opportunity_cost,
        revisions=health,
        **overrides,
    )
    return engine, result


def test_decision_engine_builds_replacement_pipeline():
    engine = DecisionEngine()
    result = engine.analyze_position(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        tsr=60,
        relative_performance=35,
        dividend_growth=50,
        earnings_growth=45,
        analyst_revisions=30,
        dividend_quality=40,
        technical_health=35,
        opportunity_cost=80,
        revisions=50,
        peer_scores=[("MSFT", 75), ("NVDA", 90), ("AAPL", 60)],
    )

    assert result.recommendation in {"sell", "partial-sell", "watch", "hold"}
    assert result.metadata["replacement_candidates"]
    assert result.metadata["replacement_candidates"][0].symbol in {"MSFT", "NVDA"}
    assert engine.repository.recommendations[-1].replacement_candidates


def test_replacement_quality_compares_candidate_scores_to_cps_not_sell_score():
    engine = DecisionEngine()
    result = engine.analyze_position(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        tsr=80,
        relative_performance=80,
        dividend_growth=80,
        earnings_growth=80,
        analyst_revisions=80,
        dividend_quality=80,
        technical_health=80,
        opportunity_cost=0,
        revisions=80,
        peer_scores=[("MSFT", 50)],
    )

    # The candidate (50) beats the sell score (about 17) but not the CPS (80), so it is not a replacement.
    assert result.cps == 80
    assert result.sell_score < 50
    assert result.metadata["replacement_candidates"] == []


def test_recommendation_confidence_is_data_completeness_not_score_strength():
    weak_engine, weak = _analyze(10, 10)
    strong_engine, strong = _analyze(90, 10)

    # Six inputs flip, so health 10 counts as 90 and health 90 counts as 10; opportunity cost stays 10.
    assert weak.sell_score == pytest.approx(9150 / 115)
    assert strong.sell_score == pytest.approx(1150 / 115)
    for engine, result in ((weak_engine, weak), (strong_engine, strong)):
        assert result.confidence == 1
        assert engine.last_recommendation.confidence == 1


def test_a_healthy_holding_is_held_and_a_weak_one_is_flagged_for_sale():
    _, healthy = _analyze(80, 10)
    _, weak = _analyze(20, 90)

    assert healthy.sell_score == pytest.approx(2150 / 115)
    assert healthy.recommendation == "hold"
    assert weak.sell_score == pytest.approx(9350 / 115)
    assert weak.recommendation == "sell"


def test_a_middling_holding_with_a_high_opportunity_cost_is_flagged_for_a_partial_sale():
    _, result = _analyze(40, 80)

    assert result.sell_score == pytest.approx(7200 / 115)
    assert result.recommendation == "partial-sell"


def test_results_and_recommendations_say_which_way_the_sell_score_runs():
    engine, result = _analyze(60, 40)

    assert result.metadata["sell_score_direction"] == "higher_means_sell"
    assert engine.repository.scores["portfolio-1:AAPL"]["sell_score_direction"] == "higher_means_sell"
    assert engine.last_recommendation.sell_score_direction == "higher_means_sell"
    assert engine.repository.recommendations[-1].sell_score_direction == "higher_means_sell"

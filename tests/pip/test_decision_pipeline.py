from __future__ import annotations

from stockscanner.pip.decision_engine import DecisionEngine


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
        dividend_quality=0,
        technical_health=0,
        opportunity_cost=0,
        revisions=0,
        peer_scores=[("MSFT", 50)],
    )

    assert result.cps == 80
    assert result.sell_score < 50
    assert result.metadata["replacement_candidates"] == []


def test_recommendation_confidence_is_data_completeness_not_score_strength():
    engine = DecisionEngine()
    result = engine.analyze_position(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        tsr=10,
        relative_performance=10,
        dividend_growth=10,
        earnings_growth=10,
        analyst_revisions=10,
        dividend_quality=10,
        technical_health=10,
        opportunity_cost=10,
        revisions=10,
    )

    assert result.sell_score == 10
    assert result.confidence == 1
    assert engine.last_recommendation.confidence == 1

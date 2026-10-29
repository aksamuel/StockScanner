from __future__ import annotations

from stockscanner.pip.scoring import calculate_cps, calculate_sell_score


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
    assert 55 <= score <= 75


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

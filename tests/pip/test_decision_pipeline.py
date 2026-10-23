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

    assert result.recommendation in {"sell", "watch", "hold"}
    assert result.metadata["replacement_candidates"]
    assert result.metadata["replacement_candidates"][0].symbol in {"MSFT", "NVDA"}
    assert engine.repository.recommendations[-1].replacement_candidates

from __future__ import annotations

from stockscanner.pip.opportunity_cost import OpportunityCostEngine


def test_opportunity_cost_engine():
    engine = OpportunityCostEngine()
    results = engine.compare(
        symbol="AAPL",
        current_value=10000,
        current_score=55,
        alternatives=[("MSFT", 85, 11000), ("NVDA", 90, 12000)],
    )

    assert len(results) == 2
    assert results[0].expected_benefit >= 0
    assert results[0].alternative_symbol in {"MSFT", "NVDA"}

    summary = engine.summary(results)
    assert summary["total_expected_benefit"] >= 0
    assert 0 <= summary["average_confidence"] <= 1

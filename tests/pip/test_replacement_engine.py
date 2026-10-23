from __future__ import annotations

from stockscanner.pip.opportunity_cost import OpportunityCostEngine


def test_replacement_engine_candidates_are_ranked_by_improvement():
    engine = OpportunityCostEngine()
    candidates = engine.compare(
        symbol="AAPL",
        current_value=10000,
        current_score=55,
        alternatives=[("MSFT", 82, 12000), ("NVDA", 90, 13000), ("AAPL", 55, 10000)],
    )

    assert len(candidates) == 2
    assert candidates[0].alternative_symbol in {"MSFT", "NVDA"}
    assert candidates[0].expected_benefit >= 0

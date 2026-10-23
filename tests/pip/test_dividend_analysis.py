from __future__ import annotations

from .dividend_analysis import DividendAnalysisEngine


def test_dividend_analysis_basic():
    engine = DividendAnalysisEngine()

    class DividendStub:
        def __init__(self, amount: float):
            self.amount = amount

    dividends = [DividendStub(1.40), DividendStub(1.50)]

    result = engine.analyze(
        dividend_records=dividends,
        current_price=100.0,
        payout_ratio=0.65,
        dividend_growth_rate=0.12,
        consistency_score=0.9,
    )

    assert result["annualized_income"] > 0
    assert result["current_yield_pct"] > 0
    assert 0 <= result["dividend_quality_score"] <= 100
    assert result["growth_score"] > 0

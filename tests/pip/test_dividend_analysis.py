from __future__ import annotations

from datetime import date

from stockscanner.pip.dividend_analysis import DividendAnalysisEngine


def test_dividend_analysis_basic():
    engine = DividendAnalysisEngine()

    class DividendStub:
        def __init__(self, amount: float, pay_date: date):
            self.amount = amount
            self.pay_date = pay_date

    dividends = [
        DividendStub(1.40, date.today()),
        DividendStub(1.50, date.today()),
    ]

    result = engine.analyze(
        dividend_records=dividends,
        current_price=100.0,
        payout_ratio=0.65,
        dividend_growth_rate=0.12,
        consistency_score=0.9,
    )

    assert result["trailing_twelve_month_income"] == 2.9
    assert result["current_yield_pct"] > 0
    assert 0 <= result["dividend_quality_score"] <= 100
    assert result["growth_score"] > 0


def test_dividend_income_requires_dates_inside_trailing_year():
    class DividendStub:
        amount = 2.0
        ex_date = None
        pay_date = None

    result = DividendAnalysisEngine().analyze([DividendStub()], 100, None, None, None)
    assert result["trailing_twelve_month_income"] is None
    assert result["current_yield_pct"] is None

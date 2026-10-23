from stockscanner.pip.dividend_analysis import DividendAnalysisEngine


def test_dividend_analysis_basic():
    engine = DividendAnalysisEngine()
    dividends = [
        type("DividendRecord", (), {"amount": 1.40})(),
        type("DividendRecord", (), {"amount": 1.50})(),
    ]

    result = engine.analyze(dividends, current_price=100.0, payout_ratio=0.65, dividend_growth_rate=0.12, consistency_score=0.9)

    assert result["annualized_income"] > 0
    assert result["current_yield_pct"] > 0
    assert 0 <= result["dividend_quality_score"] <= 100
    assert result["growth_score"] > 0

from datetime import date

import pandas as pd
import pytest

from stockscanner.pip.research import ResearchDataUnavailable, collect_research_data


def no_fundamentals(_symbol):
    return {
        "earnings_growth_percent": None,
        "revenue_growth_percent": None,
        "revision_periods": {},
        "warnings": [],
    }


@pytest.mark.parametrize("provider", ["Alpaca", "Twelve Data"])
def test_research_uses_shared_quote_yahoo_history_and_analyst_data(provider):
    stock = pd.DataFrame(
        {
            "Close": [10.0, 12.0],
            "Dividends": [0.5, 0.5],
        },
        index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
    )
    benchmark = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
    )
    history_calls = []
    analyst_calls = []

    def load_history(symbol):
        history_calls.append(symbol)
        return stock if symbol == "ABC" else benchmark

    def load_analyst(symbol, current_price, *, include_target_price):
        analyst_calls.append((symbol, current_price, include_target_price))
        return {
            "Analyst Rating": "Buy",
            "Target Price": 15.0,
            "Target Upside": 15.38,
        }

    result = collect_research_data(
        "abc",
        market_snapshot={
            "generated_at": "2026-01-01T15:00:00Z",
            "prices": {"ABC": 13.0},
            "price_timestamps": {"ABC": "2026-01-01T14:59:00Z"},
            "provider_by_symbol": {"ABC": provider},
            "stale_symbols": ["ABC"],
        },
        history_loader=load_history,
        analyst_loader=load_analyst,
        fundamental_loader=no_fundamentals,
        today=date(2025, 12, 31),
    )

    assert history_calls == ["ABC", "SPY"]
    assert analyst_calls == [("ABC", 13.0, True)]
    assert result["price"] == {
        "price": 13.0,
        "source": provider,
        "as_of": "2026-01-01T14:59:00Z",
        "stale": True,
    }
    assert result["returns"]["price_return_percent"] == 20.0
    assert result["returns"]["spy_return_percent"] == 10.0
    assert result["returns"]["relative_performance_percentage_points"] == 10.0
    assert result["dividends"]["trailing_365_days_per_share"] == 1.0
    assert result["analyst"]["rating"] == "Buy"
    assert result["analyst"]["target_price"] == 15.0
    assert result["unavailable_metrics"]["earnings_growth_percent"]
    assert result["unavailable_metrics"]["revenue_growth_percent"]
    assert result["unavailable_metrics"]["analyst_revisions_score"]
    assert "not portfolio cash income" in result["dividends"]["note"]


def test_research_includes_growth_and_raw_revision_counts_without_scoring_them():
    history = pd.DataFrame(
        {"Close": [10.0, 12.0], "Dividends": [0.0, 0.0]},
        index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
    )
    fundamentals = {
        "source": "Yahoo Finance",
        "earnings_growth_percent": 28.7,
        "revenue_growth_percent": 16.4,
        "revision_periods": {
            "0q": {
                "up_last_7_days": 1,
                "up_last_30_days": 3,
                "down_last_7_days": 0,
                "down_last_30_days": 1,
            },
        },
        "warnings": [],
    }

    result = collect_research_data(
        "ABC",
        history_loader=lambda symbol: history,
        analyst_loader=lambda *_args, **_kwargs: {},
        fundamental_loader=lambda _symbol: fundamentals,
        today=date(2026, 1, 1),
    )

    assert result["growth"] == {
        "earnings_growth_percent": 28.7,
        "revenue_growth_percent": 16.4,
        "source": "Yahoo Finance",
    }
    assert result["analyst_revisions"]["periods"] == fundamentals["revision_periods"]
    assert "no approved 0–100 score mapping" in result["unavailable_metrics"]["analyst_revisions_score"]
    assert result["warnings"]


def test_research_falls_back_to_yahoo_history_when_shared_quote_is_missing():
    history = pd.DataFrame(
        {"Close": [20.0, 22.0], "Dividends": [0.0, 0.0]},
        index=pd.to_datetime(["2025-12-01", "2025-12-31"]),
    )

    def analyst(_symbol, current_price, *, include_target_price):
        assert current_price == 22.0
        assert include_target_price is True
        return {"Analyst Rating": "Unavailable", "Target Price": None, "Target Upside": None}

    result = collect_research_data(
        "ABC",
        history_loader=lambda _symbol: history,
        analyst_loader=analyst,
        fundamental_loader=no_fundamentals,
        today=date(2026, 1, 1),
    )

    assert result["price"] == {
        "price": 22.0,
        "source": "Yahoo Finance historical close",
        "as_of": "2025-12-31",
        "stale": False,
    }
    assert result["returns"]["price_return_percent"] == 10.0
    assert result["analyst"]["rating"] is None


def test_relative_performance_uses_common_trading_dates():
    stock = pd.DataFrame(
        {"Close": [110.0, 121.0]},
        index=pd.to_datetime(["2025-07-01", "2025-12-31"]),
    )
    benchmark = pd.DataFrame(
        {"Close": [100.0, 200.0, 220.0]},
        index=pd.to_datetime(["2025-01-01", "2025-07-01", "2025-12-31"]),
    )
    result = collect_research_data(
        "ABC",
        market_snapshot={"prices": {"ABC": 121.0}},
        history_loader=lambda symbol: stock if symbol == "ABC" else benchmark,
        analyst_loader=lambda *_args, **_kwargs: {},
        today=date(2025, 12, 31),
    )

    assert result["returns"]["price_return_percent"] == 10.0
    assert result["returns"]["spy_return_percent"] == 120.0
    assert result["returns"]["relative_performance_percentage_points"] == 0.0


def test_dividend_history_requires_dividend_data_column():
    history = pd.DataFrame(
        {"Close": [10.0, 11.0]},
        index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
    )
    result = collect_research_data(
        "ABC",
        history_loader=lambda _symbol: history,
        analyst_loader=lambda *_args, **_kwargs: {},
        today=date(2025, 12, 31),
    )

    assert result["dividends"]["history_complete"] is False
    assert result["dividends"]["trailing_365_days_per_share"] is None


def test_relative_performance_is_unavailable_without_shared_trading_dates():
    stock = pd.DataFrame(
        {"Close": [10.0, 11.0]},
        index=pd.to_datetime(["2025-01-01", "2025-12-30"]),
    )
    benchmark = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2025-01-02", "2025-12-31"]),
    )
    result = collect_research_data(
        "ABC",
        market_snapshot={"prices": {"ABC": 11.0}},
        history_loader=lambda symbol: stock if symbol == "ABC" else benchmark,
        analyst_loader=lambda *_args, **_kwargs: {},
        today=date(2025, 12, 31),
    )

    assert result["returns"]["relative_performance_percentage_points"] is None


def test_research_reports_provider_failure_instead_of_fabricating_scores():
    def unavailable_history(_symbol):
        raise RuntimeError("provider unavailable")

    def unavailable_analyst(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    with pytest.raises(ResearchDataUnavailable, match="No market research data"):
        collect_research_data(
            "ABC",
            history_loader=unavailable_history,
            analyst_loader=unavailable_analyst,
            fundamental_loader=no_fundamentals,
            today=date(2026, 1, 1),
        )

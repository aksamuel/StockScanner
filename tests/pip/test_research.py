import json
from datetime import date
from types import MappingProxyType

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
    assert result["unavailable_metrics"]["analyst_revisions_score"] == (
        "Yahoo did not provide 30-day EPS revision counts for this symbol."
    )
    assert "not portfolio cash income" in result["dividends"]["note"]


def test_research_includes_growth_and_raw_revision_counts_and_scores_the_revisions():
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
    assert result["scores"]["revisions"] == {
        "score": 75.0,
        "raw": {"up": 3, "down": 1, "breadth": 0.5, "periods_counted": ["0q"]},
        "reason": None,
    }
    assert result["unavailable_metrics"]["analyst_revisions_score"] is None
    assert result["warnings"] == []


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
    assert result["returns"]["aligned_history_days"] == 183


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
    assert result["returns"]["aligned_history_days"] is None
    assert result["scores"]["relative_performance"]["score"] is None


YEAR = pd.bdate_range("2025-01-01", "2025-12-31")
REVISIONS = {
    "0q": {"up_last_30_days": 3, "down_last_30_days": 1},
    "+1q": {"up_last_30_days": 1, "down_last_30_days": 0},
}


def year_of_closes(last, *, adjusted_last=None, adjusted_first=None):
    """A flat 100 for a year of business days, ending at `last`."""
    frame = pd.DataFrame({"Close": [100.0] * (len(YEAR) - 1) + [last]}, index=YEAR)
    if adjusted_last is not None:
        frame["Adj Close"] = [adjusted_first] * (len(YEAR) - 1) + [adjusted_last]
    return frame


def research_for(stock, benchmark, revision_periods=None):
    fundamentals = {**no_fundamentals("ABC"), "revision_periods": revision_periods or {}}
    return collect_research_data(
        "ABC",
        history_loader=lambda symbol: stock if symbol == "ABC" else benchmark,
        analyst_loader=lambda *_args, **_kwargs: {},
        fundamental_loader=lambda _symbol: fundamentals,
        today=date(2025, 12, 31),
    )


def test_research_scores_a_full_year_from_the_same_numbers_it_returns():
    result = research_for(year_of_closes(112.0), year_of_closes(118.0), REVISIONS)

    returns = result["returns"]
    assert returns["price_return_percent"] == 12.0
    assert returns["spy_return_percent"] == 18.0
    assert returns["relative_performance_percentage_points"] == -6.0
    assert returns["history_days"] == 364
    assert returns["aligned_history_days"] == 364
    assert returns["basis"] == "adjusted_close"

    scores = result["scores"]
    assert scores["version"] == "research-1"
    assert scores["tsr"]["score"] == 65.0
    assert scores["tsr"]["raw"] == {"return_percent": 12.0, "history_days": 364}
    assert scores["relative_performance"]["score"] == 35.0
    assert scores["relative_performance"]["raw"] == {"gap_points": -6.0, "history_days": 364}
    assert scores["revisions"]["score"] == 80.0
    assert scores["technical_health"]["score"] == 96.6
    assert scores["technical_health"]["raw"]["closes"] == len(YEAR)
    assert all(scores[name]["reason"] is None for name in ("tsr", "relative_performance", "revisions", "technical_health"))

    assert result["unavailable_metrics"]["tsr_score"] is None
    assert result["unavailable_metrics"]["relative_performance_score"] is None
    assert result["unavailable_metrics"]["analyst_revisions_score"] is None
    assert result["unavailable_metrics"]["technical_health_score"] is None
    assert "normalized_return_scores" not in result["unavailable_metrics"]
    assert not any("score conversion" in warning for warning in result["warnings"])
    assert "0–100 score built from them" in result["analyst_revisions"]["note"]
    json.dumps(result["scores"], allow_nan=False)


def test_research_says_why_a_score_cannot_be_given_instead_of_guessing():
    stock = pd.DataFrame({"Close": [20.0, 22.0]}, index=pd.to_datetime(["2025-12-01", "2025-12-31"]))
    result = research_for(stock, stock)

    scores = result["scores"]
    assert [scores[name]["score"] for name in ("tsr", "relative_performance", "revisions", "technical_health")] == [None] * 4
    assert scores["tsr"]["reason"] == (
        "Yahoo history covers 30 days; at least 330 are needed to score a 1-year total return."
    )
    assert scores["relative_performance"]["reason"] == (
        "This symbol and SPY share 30 days of price history; at least 330 are needed to score performance against SPY."
    )
    assert scores["revisions"]["reason"] == "Yahoo did not provide 30-day EPS revision counts for this symbol."
    assert scores["technical_health"]["reason"] == (
        "Yahoo returned 2 daily closes; at least 200 are needed to score technical health."
    )
    unavailable = result["unavailable_metrics"]
    assert unavailable["tsr_score"] == scores["tsr"]["reason"]
    assert unavailable["relative_performance_score"] == scores["relative_performance"]["reason"]
    assert unavailable["analyst_revisions_score"] == scores["revisions"]["reason"]
    assert unavailable["technical_health_score"] == scores["technical_health"]["reason"]


def test_a_single_shared_trading_date_is_not_a_window_to_compare():
    stock = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.to_datetime(["2025-01-01", "2025-12-31"]))
    benchmark = pd.DataFrame({"Close": [100.0, 110.0]}, index=pd.to_datetime(["2025-06-02", "2025-12-31"]))

    result = research_for(stock, benchmark)

    assert result["returns"]["aligned_history_days"] is None
    assert result["returns"]["relative_performance_percentage_points"] is None
    assert result["scores"]["relative_performance"]["score"] is None
    assert result["scores"]["relative_performance"]["raw"] == {"gap_points": None, "history_days": None}


@pytest.mark.parametrize(
    "revision_periods",
    [
        pytest.param(MappingProxyType(REVISIONS), id="container-is-not-a-dict"),
        pytest.param({name: MappingProxyType(counts) for name, counts in REVISIONS.items()}, id="periods-are-not-dicts"),
    ],
)
def test_the_revision_score_reads_only_the_periods_the_answer_returns(revision_periods):
    result = research_for(year_of_closes(112.0), year_of_closes(118.0), revision_periods)

    assert result["analyst_revisions"]["periods"] == {}
    assert result["scores"]["revisions"]["score"] is None
    assert result["scores"]["revisions"]["raw"]["periods_counted"] == []


def test_a_short_spy_history_blocks_only_the_relative_score():
    result = research_for(year_of_closes(112.0), year_of_closes(118.0).iloc[-100:])

    assert result["scores"]["tsr"]["score"] == 65.0
    assert result["scores"]["relative_performance"]["score"] is None
    assert result["returns"]["relative_performance_percentage_points"] == -6.0
    assert result["returns"]["aligned_history_days"] == (YEAR[-1] - YEAR[-100]).days
    assert result["unavailable_metrics"]["tsr_score"] is None
    assert result["unavailable_metrics"]["relative_performance_score"]


def test_the_total_return_uses_the_dividend_adjusted_close_when_yahoo_returns_both():
    stock = year_of_closes(100.0, adjusted_first=90.0, adjusted_last=99.0)
    result = research_for(stock, year_of_closes(100.0))

    assert result["returns"]["price_return_percent"] == 10.0
    assert result["returns"]["basis"] == "adjusted_close"
    assert result["scores"]["tsr"]["score"] == 62.5
    assert result["scores"]["tsr"]["raw"]["return_percent"] == 10.0


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

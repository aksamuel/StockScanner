import pandas as pd

from stockscanner.analyst_data import get_pip_research_metrics


def test_pip_research_metrics_normalize_yahoo_growth_and_keep_revision_counts_raw(tmp_path, monkeypatch):
    calls = {"ticker": 0, "info": 0, "revisions": 0}

    class FakeTicker:
        def __init__(self, symbol):
            assert symbol == "AAPL"
            calls["ticker"] += 1

        def get_info(self):
            calls["info"] += 1
            return {"earningsGrowth": 0.287, "revenueGrowth": 0.164}

        def get_eps_revisions(self):
            calls["revisions"] += 1
            return pd.DataFrame(
                {
                    "upLast7days": [0, 1],
                    "upLast30days": [1, 5],
                    "downLast7Days": [1, 0],
                    "downLast30days": [1, 3],
                },
                index=["0q", "+1y"],
            )

    monkeypatch.setattr("stockscanner.analyst_data.yf.Ticker", FakeTicker)

    result = get_pip_research_metrics("aapl", cache_directory=str(tmp_path))

    assert result["source"] == "Yahoo Finance"
    assert result["earnings_growth_percent"] == 28.7
    assert result["revenue_growth_percent"] == 16.4
    assert result["revision_periods"] == {
        "0q": {
            "up_last_7_days": 0,
            "up_last_30_days": 1,
            "down_last_7_days": 1,
            "down_last_30_days": 1,
        },
        "+1y": {
            "up_last_7_days": 1,
            "up_last_30_days": 5,
            "down_last_7_days": 0,
            "down_last_30_days": 3,
        },
    }
    assert not result["warnings"]
    assert get_pip_research_metrics("AAPL", cache_directory=str(tmp_path)) == result
    assert calls == {"ticker": 1, "info": 1, "revisions": 1}

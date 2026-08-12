import pandas as pd
import pytest

from stockscanner import report
from stockscanner.config import MIN_PRICE
from stockscanner.add_exception import add_exceptions
from stockscanner.exceptions_dashboard import export_exceptions_dashboard
from stockscanner.html_report import _generate_html
from stockscanner.ranking import rank_stocks, setup_priority
from stockscanner.remove_exception import remove_exception, remove_exceptions
from stockscanner.scoring import score_stock
from stockscanner.signals import generate_signal


def test_score_stock_basic():
    df = pd.DataFrame([
        {
            'Close': 120.0,
            'MA200': 100.0,
            'MA20': 110.0,
            'MA50': 105.0,
            'RSI': 60.0,
            'MACD': 1.0,
            'MACD_SIGNAL': 0.5,
            'AVG_VOLUME': 1000000.0,
            'Volume': 1200000.0,
            'High': 130.0,
        }
    ])
    score = score_stock(df, relative_strength=25)
    assert score >= 50


def test_minimum_share_price_is_one_dollar():
    assert MIN_PRICE == 1.0


def test_generate_signal_neutral():
    df = pd.DataFrame([
        {
            'Close': 100.0,
            'High': 100.0,
            'MA20': 95.0,
            'MA50': 96.0,
            'MA200': 97.0,
            'RSI': 50.0,
            'MACD': -1.0,
            'MACD_SIGNAL': -0.5,
        }
    ])
    assert generate_signal(df) == "⚪ Neutral"


def test_report_indexes_link_to_dated_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_FOLDER", str(tmp_path / "reports"))
    date_folder = tmp_path / "reports" / "2026-08-03"
    date_folder.mkdir(parents=True)

    html_report = date_folder / "StockScanner_Combined_2026-08-03_16-40-23.html"
    html_report.write_text("<html><body>report</body></html>", encoding="utf-8")

    report._write_date_index(
        str(date_folder),
        [{"path": str(html_report), "label": "Combined HTML", "type": "HTML"}],
    )
    report._write_root_index()

    date_index = (date_folder / "index.html").read_text(encoding="utf-8")
    root_index = (tmp_path / "reports" / "index.html").read_text(encoding="utf-8")

    assert "StockScanner Reports for 2026-08-03" in date_index
    assert "href='StockScanner_Combined_2026-08-03_16-40-23.html'" in date_index
    assert "href='2026-08-03/index.html'" in root_index
    assert "href='2026-08-03/StockScanner_Combined_2026-08-03_16-40-23.html'" in root_index


def test_export_exceptions_dashboard(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    exception_list.write_text(
        "Symbol,Date From,Date To,Reason\n"
        "ABC,01/Aug/2026,31/Aug/2026,Bought & held\n"
        ",,,\n"
        "XYZ,02/Aug/2026,01/Sep/2026,<review>\n",
        encoding="utf-8",
    )
    output = tmp_path / "exceptions.html"

    result = export_exceptions_dashboard(
        str(exception_list), str(output), "08 August 2026, 04:00 PM"
    )
    page = output.read_text(encoding="utf-8")

    assert result == str(output)
    assert "<strong>2</strong>" in page
    assert "ABC" in page
    assert "Bought &amp; held" in page
    assert "&lt;review&gt;" in page
    assert "Back to Scanner Dashboard" in page
    assert 'id="selectAll"' in page
    assert 'class="ticker-select"' in page
    assert 'id="deleteSelected"' in page
    assert "[Remove Exceptions]" in page
    assert page.index("ABC") < page.index("XYZ")


def test_remove_exception_matches_complete_symbol_case_insensitively(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    exception_list.write_text(
        "Symbol,Reason\nABC,First\nABCD,Second\nabc,Duplicate\n",
        encoding="utf-8",
    )

    removed_count = remove_exception("AbC", str(exception_list))
    remaining = exception_list.read_text(encoding="utf-8")

    assert removed_count == 2
    assert "ABC," not in remaining
    assert "abc," not in remaining
    assert "ABCD,Second" in remaining


def test_remove_exceptions_removes_multiple_tickers_atomically(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    original = "Symbol,Reason\nABC,First\nDEF,Second\nGHI,Third\n"
    exception_list.write_text(original, encoding="utf-8")

    removed_count = remove_exceptions(["ABC", "ghi"], str(exception_list))
    remaining = exception_list.read_text(encoding="utf-8")

    assert removed_count == 2
    assert "DEF,Second" in remaining
    assert "ABC,First" not in remaining
    assert "GHI,Third" not in remaining

    exception_list.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="MISSING"):
        remove_exceptions(["ABC", "MISSING"], str(exception_list))
    assert exception_list.read_text(encoding="utf-8") == original


def test_add_exceptions_adds_permanent_rows_atomically(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    original = "Symbol,Date From,Date To,Reason\nABC,,,Existing\n"
    exception_list.write_text(original, encoding="utf-8")

    added_count = add_exceptions(["def", "GHI"], str(exception_list))
    updated = exception_list.read_text(encoding="utf-8")

    assert added_count == 2
    assert "DEF,,,Added from scanner dashboard" in updated
    assert "GHI,,,Added from scanner dashboard" in updated
    assert updated.index("ABC") < updated.index("DEF") < updated.index("GHI")

    with pytest.raises(ValueError, match="ABC"):
        add_exceptions(["JKL", "ABC"], str(exception_list))
    assert "JKL" not in exception_list.read_text(encoding="utf-8")


def test_exception_updates_sort_symbols_alphabetically(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    exception_list.write_text(
        "Symbol,Date From,Date To,Reason\n"
        "XYZ,,,Last\n"
        "DEF,,,Remove\n"
        "ABC,,,First\n",
        encoding="utf-8",
    )

    remove_exceptions(["DEF"], str(exception_list))
    add_exceptions(["mno"], str(exception_list))
    symbols = pd.read_csv(exception_list)["Symbol"].tolist()

    assert symbols == ["ABC", "MNO", "XYZ"]


def test_scan_dashboard_supports_selecting_top_and_all_results():
    dataframe = pd.DataFrame(
        [
            {"Symbol": "ABC", "Score": 90, "Recommendation": "BUY"},
            {"Symbol": "XYZ", "Score": 80, "Recommendation": "WATCH"},
        ]
    )

    page = _generate_html(dataframe, "08 August 2026, 04:00 PM")

    assert page.count('class="exception-select"') == 4
    assert page.count('class="select-all"') == 2
    assert 'id="addExceptions"' in page
    assert "[Add Exceptions]" in page


def test_setup_priority_orders_supported_entry_setups():
    assert setup_priority("Strong Uptrend") > setup_priority("Pullback to 20 MA")
    assert setup_priority("Pullback to 20 MA") > setup_priority("Pullback to 50 MA")
    assert setup_priority("Pullback to 50 MA") > setup_priority("Breakout Candidate")
    assert setup_priority("Breakout Candidate") > setup_priority("Neutral")


def test_setup_priority_is_secondary_to_score(monkeypatch):
    monkeypatch.setattr("stockscanner.ranking.load_exceptions", lambda: set())
    results = [
        {
            "Symbol": "LOW",
            "Score": 89,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 10,
            "Relative Strength": 50,
        },
        {
            "Symbol": "BREAK",
            "Score": 90,
            "Signal": "Breakout Candidate",
            "Risk/Reward": 1,
            "Relative Strength": 5,
        },
        {
            "Symbol": "PULL50",
            "Score": 90,
            "Signal": "Pullback to 50 MA",
            "Risk/Reward": 1,
            "Relative Strength": 5,
        },
        {
            "Symbol": "PULL20",
            "Score": 90,
            "Signal": "Pullback to 20 MA",
            "Risk/Reward": 1,
            "Relative Strength": 5,
        },
        {
            "Symbol": "UP",
            "Score": 90,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 1,
            "Relative Strength": 5,
        },
    ]

    ranked = rank_stocks(results)
    prepared = report.prepare_results_dataframe(results)
    expected = ["UP", "PULL20", "PULL50", "BREAK", "LOW"]

    assert ranked["Symbol"].tolist() == expected
    assert prepared["Symbol"].tolist() == expected

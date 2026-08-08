import pandas as pd
import pytest

from stockscanner import report
from stockscanner.exceptions_dashboard import export_exceptions_dashboard
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

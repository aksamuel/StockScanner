import pandas as pd

from stockscanner import report
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

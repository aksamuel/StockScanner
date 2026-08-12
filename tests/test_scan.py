from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from openpyxl import load_workbook

from stockscanner import html_report, report
from stockscanner.add_exception import add_exceptions
from stockscanner.analyst_data import (
    analyst_rating_priority,
    get_analyst_data,
)
from stockscanner.config import MIN_PRICE
from stockscanner.exceptions_dashboard import export_exceptions_dashboard
from stockscanner.html_report import _generate_html
from stockscanner.market_data import (
    CACHE_DAYS,
    completed_daily_data,
    download_intraday_snapshot,
)
from stockscanner.ranking import rank_stocks, setup_priority
from stockscanner.remove_exception import remove_exception, remove_exceptions
from stockscanner.scan import process_stock
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


def test_daily_cache_is_limited_to_one_day():
    assert CACHE_DAYS == 1


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
        str(exception_list),
        str(output),
        "08 August 2026, 04:00 PM",
        today=date(2026, 8, 15),
    )
    page = output.read_text(encoding="utf-8")

    assert result == str(output)
    assert "<strong>2</strong>" in page
    assert "ABC" in page
    assert "Bought &amp; held" in page
    assert "&lt;review&gt;" in page
    assert "Technical Analysis" in page
    assert "Analysts Rating" in page
    assert "Bought Selection" in page
    assert 'id="selectAll"' in page
    assert 'class="ticker-select"' in page
    assert 'id="deleteSelected"' in page
    assert "[Remove Exceptions]" in page
    assert page.index("ABC") < page.index("XYZ")
    assert 'class="expired-date" title="Expired">31/Aug/2026' not in page


def test_expired_date_to_is_highlighted(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    exception_list.write_text(
        "Symbol,Date From,Date To,Reason\n"
        "OLD,01/Jul/2026,31/Jul/2026,Expired\n"
        "LIVE,01/Aug/2026,31/Aug/2026,Active\n",
        encoding="utf-8",
    )
    output = tmp_path / "exceptions.html"

    export_exceptions_dashboard(
        str(exception_list),
        str(output),
        "15 August 2026, 04:00 PM",
        today=date(2026, 8, 15),
    )
    page = output.read_text(encoding="utf-8")

    assert 'class="expired-date" title="Expired">31/Jul/2026</td>' in page
    assert 'class="expired-date" title="Expired">31/Aug/2026</td>' not in page


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


def test_add_exceptions_adds_thirty_day_rows_atomically(tmp_path):
    exception_list = tmp_path / "exceptions.csv"
    original = "Symbol,Date From,Date To,Reason\nABC,,,Existing\n"
    exception_list.write_text(original, encoding="utf-8")

    added_count = add_exceptions(
        ["def", "GHI"], str(exception_list), date_from=date(2026, 8, 12)
    )
    updated = exception_list.read_text(encoding="utf-8")

    assert added_count == 2
    assert "DEF,12/Aug/2026,11/Sep/2026,Added from scanner dashboard" in updated
    assert "GHI,12/Aug/2026,11/Sep/2026,Added from scanner dashboard" in updated
    assert updated.index("ABC") < updated.index("DEF") < updated.index("GHI")

    with pytest.raises(ValueError, match="ABC"):
        add_exceptions(
            ["JKL", "ABC"], str(exception_list), date_from=date(2026, 8, 12)
        )
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
    add_exceptions(["mno"], str(exception_list), date_from=date(2026, 8, 12))
    symbols = pd.read_csv(exception_list)["Symbol"].tolist()

    assert symbols == ["ABC", "MNO", "XYZ"]


def test_scan_dashboard_supports_selecting_top_and_all_results():
    dataframe = pd.DataFrame(
        [
            {
                "Symbol": "ABC",
                "Score": 90,
                "Recommendation": "BUY",
                "Analyst Rating": "Buy",
                "Target Upside": 25,
            },
            {
                "Symbol": "XYZ",
                "Score": 80,
                "Recommendation": "WATCH",
                "Analyst Rating": "Hold",
                "Target Upside": None,
            },
        ]
    )

    page = _generate_html(dataframe, "08 August 2026, 04:00 PM")

    assert page.count('class="exception-select"') == 4
    assert page.count('class="select-all"') == 2
    assert 'id="addExceptions"' in page
    assert "[Add Exceptions]" in page
    assert "25.00%" in page


def test_current_price_cells_use_rsi_background_colors(tmp_path):
    dataframe = report.prepare_results_dataframe(
        [
            {"Symbol": "HIGH", "Current Price": 10, "RSI": 70, "Score": 90},
            {"Symbol": "UPPER", "Current Price": 11, "RSI": 60, "Score": 80},
            {"Symbol": "NEUTRAL", "Current Price": 12, "RSI": 50, "Score": 70},
            {"Symbol": "LOWER", "Current Price": 13, "RSI": 40, "Score": 60},
            {"Symbol": "LOW", "Current Price": 14, "RSI": 30, "Score": 50},
        ]
    )

    page = _generate_html(dataframe, "12 August 2026, 10:00 PM")
    for css_class in [
        "price-rsi-overbought",
        "price-rsi-upper",
        "price-rsi-neutral",
        "price-rsi-lower",
        "price-rsi-oversold",
    ]:
        assert page.count(f'class="{css_class}"') == 2

    workbook_path = tmp_path / "rsi-colors.xlsx"
    report.export_excel_workbook(workbook_path, dataframe)
    worksheet = load_workbook(workbook_path)["Complete Scan"]
    headers = {cell.value: cell.column for cell in worksheet[1]}
    price_column = headers["Current Price"]
    assert [
        worksheet.cell(row=row_number, column=price_column).fill.fgColor.rgb
        for row_number in range(2, 7)
    ] == [
        "004FB52A",
        "00D8EDCC",
        "00BFE7F5",
        "00F8DDCC",
        "00F47732",
    ]


def test_symbol_cells_use_relative_strength_background_colors(tmp_path):
    dataframe = report.prepare_results_dataframe(
        [
            {"Symbol": "STRONG", "Relative Strength": 6, "Score": 90},
            {"Symbol": "UPPER", "Relative Strength": 5, "Score": 80},
            {"Symbol": "NEUTRAL", "Relative Strength": 0, "Score": 70},
            {"Symbol": "LOWER", "Relative Strength": -5, "Score": 60},
            {"Symbol": "WEAK", "Relative Strength": -6, "Score": 50},
        ]
    )

    page = _generate_html(dataframe, "12 August 2026, 10:00 PM")
    for css_class in [
        "symbol-rs-strong",
        "symbol-rs-upper",
        "symbol-rs-neutral",
        "symbol-rs-lower",
        "symbol-rs-weak",
    ]:
        assert page.count(f'class="{css_class}"') == 2

    workbook_path = tmp_path / "relative-strength-colors.xlsx"
    report.export_excel_workbook(workbook_path, dataframe)
    worksheet = load_workbook(workbook_path)["Complete Scan"]
    headers = {cell.value: cell.column for cell in worksheet[1]}
    symbol_column = headers["Symbol"]
    assert [
        worksheet.cell(row=row_number, column=symbol_column).fill.fgColor.rgb
        for row_number in range(2, 7)
    ] == [
        "004FB52A",
        "00D8EDCC",
        "00BFE7F5",
        "00F8DDCC",
        "00F47732",
    ]


def test_reports_replace_price_as_of_column_with_refresh_time_near_graph():
    dataframe = report.prepare_results_dataframe(
        [
            {
                "Symbol": "ABC",
                "Price As Of": "2026-08-12T15:15:00-04:00",
                "Score": 90,
            }
        ]
    )

    assert "Price As Of" not in dataframe.columns
    page = _generate_html(dataframe, "12 August 2026, 10:00 PM")
    marker = "Page refreshed as of: 12 August 2026, 10:00 PM"
    assert page.count(marker) == 1
    assert page.index(marker) < page.index('<canvas id="recChart"')


def test_current_price_is_displayed_below_symbol_in_smaller_text(tmp_path):
    dataframe = report.prepare_results_dataframe(
        [{"Symbol": "ABC", "Current Price": 123.45, "Score": 90}]
    )

    page = _generate_html(dataframe, "12 August 2026, 10:00 PM")
    assert page.count(
        '<span class="symbol-name">ABC</span>'
        '<span class="symbol-price">($123.45)</span>'
    ) == 2

    workbook_path = tmp_path / "symbol-price.xlsx"
    report.export_excel_workbook(workbook_path, dataframe)
    worksheet = load_workbook(workbook_path, rich_text=True)["Complete Scan"]
    headers = {str(cell.value): cell.column for cell in worksheet[1]}
    symbol_cell = worksheet.cell(row=2, column=headers["Symbol"])
    assert str(symbol_cell.value) == "ABC\n($123.45)"
    assert symbol_cell.value[0].font.sz == 11
    assert symbol_cell.value[1].font.sz == 9


def test_three_report_pages_have_requested_columns_navigation_and_selection():
    dataframe = report.prepare_results_dataframe(
        [
            {
                "Symbol": "ABC",
                "Sector": "Technology",
                "Market": "NYSE",
                "Current Price": 123.45,
                "RSI": 55,
                "Relative Strength": 70,
                "Score": 90,
                "Recommendation": "BUY",
                "Signal": "Strong Uptrend",
                "Trend": "Bullish",
                "MACD": 1.2,
                "Analyst Rating": "Buy",
                "Target Upside": 20,
                "Zone Status": "Between Zones",
                "Suggested Shares": 10,
                "Risk/Reward": 2,
                "Investment": 1234.5,
            }
        ]
    )

    pages = {
        key: _generate_html(dataframe, "12 August 2026, 10:00 PM", page_key=key)
        for key in ["technical", "analysts", "bought-selection"]
    }
    for page in pages.values():
        assert 'href="index.html">Technical Analysis</a>' in page
        assert 'href="analysts.html">Analysts Rating</a>' in page
        assert 'href="bought-selection.html">Bought Selection</a>' in page
        assert 'href="exceptions.html">Exception List</a>' in page

    technical_headers = pages["technical"].split("<thead><tr>", 1)[1].split(
        "</tr></thead>", 1
    )[0]
    assert "<th>RSI</th>" in technical_headers
    assert "<th>Recommendation</th>" in technical_headers
    assert "<th>Analyst Rating</th>" not in technical_headers
    assert 'id="sortTargetUpside"' in pages["technical"]
    assert 'data-current-price="123.45"' in pages["technical"]
    assert 'data-target-one=""' in pages["technical"]
    assert "(leftTarget - leftPrice) / leftPrice" in pages["technical"]
    assert "Temporarily ranked by Target 1 percentage upside" in pages["technical"]

    analysts_headers = pages["analysts"].split("<thead><tr>", 1)[1].split(
        "</tr></thead>", 1
    )[0]
    assert "<th>Analyst Rating</th>" in analysts_headers
    assert "<th>Zone Status</th>" in analysts_headers
    assert "<th>MACD</th>" not in analysts_headers

    bought_headers = pages["bought-selection"].split("<thead><tr>", 1)[1].split(
        "</tr></thead>", 1
    )[0]
    assert "<th>Suggested Shares</th>" in bought_headers
    assert "<th>Investment</th>" in bought_headers
    assert pages["technical"].count('class="exception-select"') == 0
    assert pages["analysts"].count('class="exception-select"') == 0
    assert pages["bought-selection"].count('class="exception-select"') == 2
    assert '<button id="sortTargetUpside"' not in pages["analysts"]
    assert '<button id="sortTargetUpside"' not in pages["bought-selection"]


def test_html_export_creates_three_stable_linked_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(html_report, "REPORT_FOLDER", str(tmp_path))

    archived_page = html_report.export_html_report(
        [{"Symbol": "ABC", "Score": 90, "Current Price": 10}],
        quiet=True,
    )

    date_folder = Path(archived_page).parent
    assert (date_folder / "technical.html").exists()
    assert (date_folder / "analysts.html").exists()
    assert (date_folder / "bought-selection.html").exists()


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


def test_analyst_data_calculates_target_upside_and_uses_cache(tmp_path, monkeypatch):
    calls = []

    class FakeTicker:
        def get_info(self):
            calls.append("requested")
            return {
                "recommendationKey": "buy",
                "targetMeanPrice": 125,
            }

    monkeypatch.setattr(
        "stockscanner.analyst_data.yf.Ticker", lambda symbol: FakeTicker()
    )

    first = get_analyst_data("ABC", 100, cache_directory=str(tmp_path))
    second = get_analyst_data("ABC", 100, cache_directory=str(tmp_path))

    assert first == {"Analyst Rating": "Buy", "Target Upside": 25.0}
    assert second == first
    assert calls == ["requested"]


def test_analyst_data_only_breaks_complete_technical_ties(monkeypatch):
    monkeypatch.setattr("stockscanner.ranking.load_exceptions", lambda: set())
    results = [
        {
            "Symbol": "BETTER_TECHNICAL",
            "Score": 90,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 2,
            "Relative Strength": 20,
            "Analyst Rating": "Hold",
            "Target Upside": 5,
        },
        {
            "Symbol": "STRONG_BUY",
            "Score": 90,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 1,
            "Relative Strength": 20,
            "Analyst Rating": "Strong Buy",
            "Target Upside": 30,
        },
        {
            "Symbol": "BUY_HIGH_TARGET",
            "Score": 90,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 1,
            "Relative Strength": 20,
            "Analyst Rating": "Buy",
            "Target Upside": 25,
        },
        {
            "Symbol": "BUY_LOW_TARGET",
            "Score": 90,
            "Signal": "Strong Uptrend",
            "Risk/Reward": 1,
            "Relative Strength": 20,
            "Analyst Rating": "Buy",
            "Target Upside": 10,
        },
    ]

    ranked = rank_stocks(results)

    assert ranked["Symbol"].tolist() == [
        "BETTER_TECHNICAL",
        "STRONG_BUY",
        "BUY_HIGH_TARGET",
        "BUY_LOW_TARGET",
    ]
    assert analyst_rating_priority("Strong Buy") > analyst_rating_priority("Buy")


def test_scan_result_places_analyst_and_risk_columns_after_sector(monkeypatch):
    history = pd.DataFrame(
        {
            "Close": [10.0] * 200,
            "High": [11.0] * 200,
            "Volume": [1_000_000] * 200,
            "MA20": [9.5] * 200,
            "MA50": [9.0] * 200,
            "MA200": [8.0] * 200,
            "RSI": [60.0] * 200,
            "MACD": [1.0] * 200,
            "MACD_SIGNAL": [0.5] * 200,
            "AVG_VOLUME": [900_000] * 200,
        }
    )
    monkeypatch.setattr("stockscanner.scan.download_data", lambda symbol: history)
    monkeypatch.setattr("stockscanner.scan.calculate_indicators", lambda data: data)
    monkeypatch.setattr("stockscanner.scan.calculate_relative_strength", lambda symbol: 10)
    monkeypatch.setattr("stockscanner.scan.download_intraday_snapshot", lambda symbol: None)
    monkeypatch.setattr("stockscanner.scan.score_stock", lambda data, strength: 90)
    monkeypatch.setattr("stockscanner.scan.generate_signal", lambda data: "Strong Uptrend")
    monkeypatch.setattr(
        "stockscanner.scan.generate_trade_plan",
        lambda data, available_cash, risk_percent: {
            "Trend": "Strong Uptrend",
            "Entry": 10,
            "Stop": 9,
            "Target1": 11,
            "Target2": 12,
            "Target3": 13,
            "RR": 2,
            "Shares": 25,
            "Investment": 250,
        },
    )
    monkeypatch.setattr(
        "stockscanner.scan.get_analyst_data",
        lambda symbol, current_price: {
            "Analyst Rating": "Buy",
            "Target Upside": 20,
        },
    )

    result = process_stock(
        {"Symbol": "ABC", "Market": "NYSE", "Sector": "Technology"},
        quiet=True,
    )
    columns = list(result)

    sector_index = columns.index("Sector")
    assert columns[sector_index : sector_index + 6] == [
        "Sector",
        "Analyst Rating",
        "Target Upside",
        "Suggested Shares",
        "Risk/Reward",
        "Priority",
    ]


def test_completed_daily_data_drops_current_session_candle():
    index = pd.to_datetime(["2026-08-11", "2026-08-12"]).tz_localize(
        "America/New_York"
    )
    history = pd.DataFrame({"Close": [10, 11]}, index=index)
    now = datetime(2026, 8, 12, 12, tzinfo=ZoneInfo("America/New_York"))

    completed = completed_daily_data(history, now=now)

    assert completed["Close"].tolist() == [10]


def test_intraday_snapshot_uses_latest_current_session_quote(monkeypatch):
    index = pd.to_datetime(
        ["2026-08-12 09:00", "2026-08-12 10:15"]
    ).tz_localize("America/New_York")
    intraday = pd.DataFrame(
        {"Close": [10.0, 10.5], "Volume": [100, 250]},
        index=index,
    )

    class FakeTicker:
        def history(self, **kwargs):
            assert kwargs == {"period": "1d", "interval": "1m", "prepost": True}
            return intraday

    monkeypatch.setattr(
        "stockscanner.market_data.yf.Ticker", lambda symbol: FakeTicker()
    )
    now = datetime(2026, 8, 12, 10, 16, tzinfo=ZoneInfo("America/New_York"))

    snapshot = download_intraday_snapshot("ABC", now=now)

    assert snapshot["price"] == 10.5
    assert snapshot["volume"] == 350
    assert snapshot["timestamp"].startswith("2026-08-12T10:15:00")


def test_process_stock_overlays_intraday_price_after_daily_indicators(monkeypatch):
    index = pd.date_range(
        "2025-10-01",
        periods=200,
        freq="B",
        tz="America/New_York",
    )
    history = pd.DataFrame(
        {
            "Close": [10.0] * 200,
            "High": [11.0] * 200,
            "Volume": [1_000_000] * 200,
            "MA20": [9.5] * 200,
            "MA50": [9.0] * 200,
            "MA200": [8.0] * 200,
            "RSI": [60.0] * 200,
            "MACD": [1.0] * 200,
            "MACD_SIGNAL": [0.5] * 200,
            "AVG_VOLUME": [900_000] * 200,
        },
        index=index,
    )
    observed = {}
    monkeypatch.setattr("stockscanner.scan.download_data", lambda symbol: history)
    monkeypatch.setattr("stockscanner.scan.completed_daily_data", lambda data: data)
    monkeypatch.setattr("stockscanner.scan.calculate_indicators", lambda data: data)
    monkeypatch.setattr(
        "stockscanner.scan.download_intraday_snapshot",
        lambda symbol: {
            "price": 12.5,
            "volume": 1_500_000,
            "timestamp": "2026-08-12T10:15:00-04:00",
        },
    )
    monkeypatch.setattr("stockscanner.scan.calculate_relative_strength", lambda symbol: 10)
    monkeypatch.setattr(
        "stockscanner.scan.analyze_support_resistance",
        lambda data, current_price: observed.setdefault(
            "zone_input", (data["Close"].iloc[-1], current_price)
        )
        and {
            "Zone Status": "Between Zones",
            "Support Low": 9,
            "Support High": 10,
            "Resistance Low": 13,
            "Resistance High": 14,
        },
    )
    monkeypatch.setattr(
        "stockscanner.scan.score_stock",
        lambda data, strength: observed.setdefault(
            "score_input", (data["Close"].iloc[-1], data["Volume"].iloc[-1])
        )
        and 90,
    )
    monkeypatch.setattr("stockscanner.scan.generate_signal", lambda data: "Strong Uptrend")
    monkeypatch.setattr(
        "stockscanner.scan.generate_trade_plan",
        lambda data, available_cash, risk_percent: {
            "Trend": "Strong Uptrend",
            "Entry": 10,
            "Stop": 9,
            "Target1": 11,
            "Target2": 12,
            "Target3": 13,
            "RR": 2,
            "Shares": 25,
            "Investment": 250,
        },
    )
    monkeypatch.setattr(
        "stockscanner.scan.get_analyst_data",
        lambda symbol, current_price: {
            "Analyst Rating": "Buy",
            "Target Upside": 20,
        },
    )

    result = process_stock(
        {"Symbol": "ABC", "Market": "NYSE", "Sector": "Technology"},
        quiet=True,
    )

    assert observed["score_input"] == (12.5, 1_500_000)
    assert observed["zone_input"] == (10.0, 12.5)
    assert result["Current Price"] == 12.5
    assert result["Zone Status"] == "Between Zones"
    assert result["Price As Of"] == "2026-08-12T10:15:00-04:00"

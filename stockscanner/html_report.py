"""Generate a self-contained static HTML dashboard from scan results."""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from curl_cffi.requests.exceptions import RequestException
from yfinance.exceptions import YFException

from .market_data import completed_daily_data, download_data
from .price_snapshot import SnapshotError, write_snapshot_from_results
from .ranking import setup_priority
from .report import REPORT_FOLDER, TOP_RESULTS, prepare_results_dataframe

NEW_YORK = ZoneInfo("America/New_York")
PRICE_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "prices.json"


def _format_new_york_time(moment=None):
    """Format a timestamp in New York local time with its DST abbreviation."""
    moment = moment or datetime.now(NEW_YORK)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)
    else:
        moment = moment.astimezone(NEW_YORK)
    return moment.strftime("%d %B %Y, %I:%M %p %Z")


def _escape_html(text):
    """Escape HTML special characters."""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _recommendation_class(recommendation):
    """Return a CSS class based on the recommendation text."""
    rec = str(recommendation).upper()
    if "STRONG BUY" in rec:
        return "rec-strong-buy"
    if "BUY" in rec:
        return "rec-buy"
    if "ACCUMULATE" in rec or "HOLD" in rec:
        return "rec-hold"
    if "WATCH" in rec:
        return "rec-watch"
    if "AVOID" in rec:
        return "rec-avoid"
    return ""


def _score_class(score):
    """Return a CSS class based on the score value."""
    try:
        s = float(score)
    except (ValueError, TypeError):
        return ""
    if s >= 90:
        return "score-excellent"
    if s >= 70:
        return "score-good"
    if s >= 50:
        return "score-fair"
    return "score-poor"


def _current_price_rsi_class(rsi):
    """Return the Current Price colour class for the row's RSI."""
    try:
        value = float(rsi)
    except (ValueError, TypeError):
        return ""
    if value >= 70:
        return "price-rsi-overbought"
    if value > 50:
        return "price-rsi-upper"
    if value == 50:
        return "price-rsi-neutral"
    if value > 30:
        return "price-rsi-lower"
    return "price-rsi-oversold"


def _symbol_relative_strength_class(relative_strength):
    """Return the Symbol colour class for the row's Relative Strength."""
    try:
        value = float(relative_strength)
    except (ValueError, TypeError):
        return ""
    if value > 5:
        return "symbol-rs-weak"
    if value > 0:
        return "symbol-rs-lower"
    if value == 0:
        return "symbol-rs-neutral"
    if value >= -5:
        return "symbol-rs-upper"
    return "symbol-rs-strong"


def _analyst_support_gap_class(current_price, support_low):
    """Return the Analyst-page Symbol colour from price versus support."""
    try:
        current_price = float(current_price)
        support_low = float(support_low)
    except (ValueError, TypeError):
        return ""
    if current_price <= 0:
        return ""

    gap_percent = (current_price - support_low) / current_price * 100
    if gap_percent > 5:
        return "symbol-support-above-five"
    if gap_percent > 0:
        return "symbol-support-above-zero"
    if gap_percent == 0:
        return "symbol-support-zero"
    if gap_percent >= -5:
        return "symbol-support-below-zero"
    return "symbol-support-below-five"


def _analyst_support_gap_class(current_price, support_low):
    """Return the Analyst-page Symbol colour from price versus support."""
    try:
        current_price = float(current_price)
        support_low = float(support_low)
    except (ValueError, TypeError):
        return ""
    if current_price <= 0:
        return ""

    gap_percent = (current_price - support_low) / current_price * 100
    if gap_percent > 5:
        return "symbol-support-above-five"
    if gap_percent > 0:
        return "symbol-support-above-zero"
    if gap_percent == 0:
        return "symbol-support-zero"
    if gap_percent >= -5:
        return "symbol-support-below-zero"
    return "symbol-support-below-five"


def _format_symbol_with_price(symbol, current_price):
    """Display the current price below the symbol."""
    formatted_symbol = _escape_html(symbol)
    try:
        formatted_price = f"${float(current_price):,.2f}"
    except (ValueError, TypeError):
        return formatted_symbol
    return (
        f'<span class="symbol-name">{formatted_symbol}</span>'
        f'<span class="symbol-price">({formatted_price})</span>'
    )


def _format_currency(value):
    """Format a number as currency."""
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return _escape_html(value)


def _format_price_level_with_direction(price_level, current_price):
    """Format a price level with its direction relative to Current Price."""
    formatted_level = _format_currency(price_level)
    try:
        price_level = float(price_level)
        current_price = float(current_price)
    except (ValueError, TypeError):
        return formatted_level
    if price_level > current_price:
        return f'{formatted_level} <span class="target-arrow-up" title="Above current price">&#8593;</span>'
    if price_level < current_price:
        return f'{formatted_level} <span class="target-arrow-down" title="Below current price">&#8595;</span>'
    return formatted_level


def _format_number(value, decimals=2):
    """Format a number with specified decimal places."""
    try:
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return _escape_html(value)


def _format_integer(value):
    """Format a number as an integer."""
    try:
        return f"{int(float(value)):,}"
    except (ValueError, TypeError):
        return _escape_html(value)


def _data_number(value):
    """Format a numeric value for an HTML data attribute."""
    try:
        return str(float(value))
    except (ValueError, TypeError):
        return ""


def _optional_number(value):
    """Return a finite float or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _build_top_twenty_details(dataframe):
    """Build up to 20 qualifying detail rows in default scanner order."""
    details = []
    if dataframe.empty or "Symbol" not in dataframe.columns:
        return details
    for _, row in dataframe.iterrows():
        symbol = str(row.get("Symbol", "")).strip()
        if not symbol:
            continue
        entry = _optional_number(row.get("Entry"))
        current = _optional_number(row.get("Current Price"))
        support_low = _optional_number(row.get("Support Low"))
        resistance_low = _optional_number(row.get("Resistance Low"))
        if (
            current is not None
            and resistance_low is not None
            and current >= resistance_low
        ):
            continue
        difference = (
            current - entry
            if entry is not None and entry > 0 and current is not None
            else None
        )
        change_percent = (
            difference / entry * 100
            if difference is not None
            else None
        )
        details.append(
            {
                "symbol": symbol,
                "entry": entry,
                "current": current,
                "support_low": support_low,
                "resistance_low": resistance_low,
                "difference": difference,
                "change_percent": change_percent,
            }
        )
        if len(details) == TOP_RESULTS:
            break
    return details


def _completed_close_series(history, now=None):
    """Return valid completed closes indexed by date."""
    history = completed_daily_data(history, now=now)
    if (
        history is None
        or not isinstance(history, pd.DataFrame)
        or history.empty
        or "Close" not in history.columns
    ):
        return None

    dates = pd.to_datetime(history.index, errors="coerce", utc=True)
    closes = pd.to_numeric(history["Close"], errors="coerce")
    series = pd.Series(closes.to_numpy(), index=dates).dropna()
    series = series[series > 0]
    if series.empty:
        return None
    series.index = series.index.tz_convert(None).normalize()
    return series.groupby(level=0).last().sort_index()


def _build_kpi_chart_data(dataframe, history_loader=None, now=None):
    """Build an indexed S&P 500 versus equal-weight Top 20 comparison."""
    if dataframe.empty or "Symbol" not in dataframe.columns:
        return None
    history_loader = history_loader or download_data

    selected_symbols = []
    seen = set()
    for value in dataframe["Symbol"].head(TOP_RESULTS):
        if pd.isna(value):
            continue
        symbol = str(value).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        selected_symbols.append(symbol)

    def load_close(symbol):
        try:
            history = history_loader(symbol, period="1y")
        except (
            OSError,
            RequestException,
            RuntimeError,
            TypeError,
            ValueError,
            YFException,
        ) as exc:
            print(
                f"KPI performance history unavailable for {symbol}: {exc}",
                file=sys.stderr,
            )
            return None
        close = _completed_close_series(history, now=now)
        if close is None or len(close) < 2:
            print(
                f"KPI performance history unavailable for {symbol}: "
                "fewer than two valid completed closes.",
                file=sys.stderr,
            )
            return None
        return close

    benchmark = load_close("^GSPC")
    if benchmark is None:
        return None

    aligned = benchmark.rename("S&P 500").to_frame()
    included_symbols = []
    for symbol in selected_symbols:
        close = load_close(symbol)
        if close is None:
            continue
        candidate = aligned.join(close.rename(symbol), how="inner")
        if len(candidate) < 2:
            print(
                f"KPI performance history unavailable for {symbol}: "
                "fewer than two dates overlap the benchmark and other constituents.",
                file=sys.stderr,
            )
            continue
        aligned = candidate
        included_symbols.append(symbol)

    if not included_symbols or len(aligned) < 2:
        print(
            "KPI performance chart unavailable: fewer than two aligned points "
            "or no usable Top 20 histories.",
            file=sys.stderr,
        )
        return None

    normalized = aligned.divide(aligned.iloc[0]).multiply(100)
    top_twenty = normalized[included_symbols].mean(axis=1)
    return {
        "labels": [timestamp.date().isoformat() for timestamp in normalized.index],
        "sp500": normalized["S&P 500"].round(4).tolist(),
        "top20": top_twenty.round(4).tolist(),
        "constituents": included_symbols,
        "selected_count": len(selected_symbols),
    }


CURRENCY_COLUMNS = {
    "Current Price", "20 MA", "50 MA", "200 MA",
    "Support Low", "Support High", "Resistance Low", "Resistance High",
    "Zone Tolerance",
    "Entry", "Stop Loss", "Target 1", "Target 2", "Target 3", "Investment",
}
DECIMAL_COLUMNS = {"RSI", "MACD", "Relative Strength", "Risk/Reward"}
PERCENT_COLUMNS = {
    "Target Upside", "Support Distance %", "Resistance Distance %",
    "Zone Tolerance %",
}
INTEGER_COLUMNS = {
    "Rank", "Score", "Suggested Shares", "Average Volume",
    "Average Dollar Volume", "Support Tests", "Resistance Tests",
}
TECHNICAL_DIRECTION_COLUMNS = {
    "Target 1", "Target 2", "Target 3", "20 MA", "50 MA", "200 MA", "Stop Loss",
}
ANALYST_DIRECTION_COLUMNS = {
    "Support Low", "Support High", "Resistance Low", "Resistance High",
}
PAGE_CONFIGS = {
    "landing": {
        "title": "StockScanner KPI Dashboard",
        "columns": [],
        "accent": "#1f4e78",
        "selection": False,
    },
    "technical": {
        "title": "Technical Analysis Page",
        "columns": [
            "Rank", "Symbol", "Sector", "Score", "Recommendation", "Signal",
            "Trend", "Entry", "Target 1", "Target 2", "Target 3", "20 MA",
            "50 MA", "200 MA", "Stop Loss", "RSI", "MACD",
        ],
        "accent": "#c6efce",
        "selection": False,
    },
    "analysts": {
        "title": "Analysts Rating Page",
        "columns": [
            "Rank", "Symbol", "Sector", "Analyst Rating", "Target Upside",
            "Zone Status", "Support Low", "Support High", "Support Tests",
            "Support Confidence", "Support Details", "Resistance Low",
            "Resistance High", "Resistance Distance %", "Resistance Tests",
            "Resistance Confidence", "Resistance Details", "Zone Tolerance",
            "Zone Tolerance %",
        ],
        "accent": "#f4cccc",
        "selection": False,
    },
    "bought-selection": {
        "title": "Bought Selection Page",
        "columns": [
            "Symbol", "Sector", "Market", "Suggested Shares", "Risk/Reward",
            "Priority", "Market Cap", "Average Volume",
            "Average Dollar Volume", "Liquidity Status", "Investment",
        ],
        "accent": "#fff200",
        "selection": True,
    },
}
NAV_ITEMS = (
    ("landing", "index.html", "KPI Dashboard"),
    ("technical", "technical.html", "Technical Analysis"),
    ("analysts", "analysts.html", "Analysts Rating"),
    ("bought-selection", "bought-selection.html", "Bought Selection"),
    ("exceptions", "exceptions.html", "Exception List"),
)


def _navigation_html(page_key):
    """Build navigation with the current page presented as disabled."""
    items = []
    for key, href, label in NAV_ITEMS:
        if key == page_key:
            items.append(
                f'<span class="nav-current" aria-current="page">{label}</span>'
            )
        else:
            items.append(f'<a href="{href}">{label}</a>')
    return "\n            ".join(items)


def _format_cell(column, value):
    """Format a cell value based on its column."""
    if pd.isna(value):
        return ""
    if column in CURRENCY_COLUMNS:
        return _format_currency(value)
    if column in DECIMAL_COLUMNS:
        return _format_number(value)
    if column in PERCENT_COLUMNS:
        return f"{_format_number(value)}%"
    if column in INTEGER_COLUMNS:
        return _format_integer(value)
    return _escape_html(value)


def _build_summary(dataframe):
    """Build summary statistics from the dataframe."""
    total_stocks = len(dataframe)
    average_score = dataframe["Score"].mean() if "Score" in dataframe.columns else 0
    highest_score = dataframe["Score"].max() if "Score" in dataframe.columns else 0

    recommendation_counts = (
        dataframe["Recommendation"].value_counts()
        if "Recommendation" in dataframe.columns
        else pd.Series(dtype=int)
    )

    def _count(label):
        return int(sum(v for k, v in recommendation_counts.items() if label in str(k).upper()))

    return {
        "total_stocks": total_stocks,
        "strong_buy": _count("STRONG BUY"),
        "buy": _count("BUY") - _count("STRONG BUY"),
        "accumulate": _count("ACCUMULATE"),
        "hold": _count("HOLD"),
        "watch": _count("WATCH"),
        "avoid": _count("AVOID"),
        "average_score": round(average_score, 2),
        "highest_score": round(highest_score, 2),
    }


def _sort_analysts_by_support_proximity(dataframe):
    """Sort the Analysts page by absolute price-to-support percentage gap."""
    sorted_data = dataframe.copy()
    current_price = (
        pd.to_numeric(sorted_data["Current Price"], errors="coerce")
        if "Current Price" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    support_low = (
        pd.to_numeric(sorted_data["Support Low"], errors="coerce")
        if "Support Low" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    valid_price = current_price > 0
    sorted_data["_support_proximity"] = (
        ((current_price - support_low) / current_price * 100).abs()
        .where(valid_price)
        .fillna(float("inf"))
    )
    sorted_data = sorted_data.sort_values(
        "_support_proximity",
        ascending=True,
        kind="stable",
    ).drop(columns="_support_proximity")
    sorted_data = sorted_data.reset_index(drop=True)
    if "Rank" in sorted_data.columns:
        sorted_data["Rank"] = range(1, len(sorted_data) + 1)
    return sorted_data


def _recommendation_priority(recommendation):
    normalized = str(recommendation).upper()
    if "STRONG BUY" in normalized:
        return 6
    if "BUY" in normalized:
        return 5
    if "ACCUMULATE" in normalized:
        return 4
    if "HOLD" in normalized:
        return 3
    if "WATCH" in normalized:
        return 2
    if "AVOID" in normalized:
        return 1
    return 0


def _trend_priority(trend):
    normalized = str(trend).casefold()
    if "strong uptrend" in normalized:
        return 3
    if "healthy pullback" in normalized:
        return 2
    if "breakout" in normalized:
        return 1
    return 0


def _sort_technical_by_hierarchy(dataframe):
    """Sort the Technical page by the requested display-only hierarchy."""
    sorted_data = dataframe.copy()
    sorted_data["_scanner_rank"] = (
        pd.to_numeric(sorted_data["Rank"], errors="coerce")
        if "Rank" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    current_price = (
        pd.to_numeric(sorted_data["Current Price"], errors="coerce")
        if "Current Price" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    target_one = (
        pd.to_numeric(sorted_data["Target 1"], errors="coerce")
        if "Target 1" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    relative_strength = (
        pd.to_numeric(sorted_data["Relative Strength"], errors="coerce")
        if "Relative Strength" in sorted_data.columns
        else pd.Series(float("nan"), index=sorted_data.index)
    )
    sorted_data["_target_gap"] = (target_one - current_price).fillna(float("-inf"))
    sorted_data["_relative_strength_order"] = relative_strength.fillna(float("-inf"))
    sorted_data["_recommendation_priority"] = (
        sorted_data["Recommendation"].map(_recommendation_priority)
        if "Recommendation" in sorted_data.columns
        else 0
    )
    sorted_data["_signal_priority"] = (
        sorted_data["Signal"].map(setup_priority)
        if "Signal" in sorted_data.columns
        else 0
    )
    sorted_data["_trend_priority"] = (
        sorted_data["Trend"].map(_trend_priority)
        if "Trend" in sorted_data.columns
        else 0
    )
    sort_columns = [
        "_recommendation_priority",
        "_signal_priority",
        "_trend_priority",
        "_relative_strength_order",
        "_target_gap",
    ]
    sorted_data = sorted_data.sort_values(
        sort_columns,
        ascending=[False] * len(sort_columns),
        kind="stable",
    )
    sorted_data = sorted_data.loc[~relative_strength.lt(0)].drop(columns=sort_columns)
    sorted_data = sorted_data.reset_index(drop=True)
    if "Rank" in sorted_data.columns:
        sorted_data["Rank"] = range(1, len(sorted_data) + 1)
    return sorted_data


def _generate_html(dataframe, scan_time, page_key=None, chart_data=None):
    """Generate the complete HTML dashboard string."""
    if page_key == "analysts":
        dataframe = _sort_analysts_by_support_proximity(dataframe)
    elif page_key == "technical":
        dataframe = _sort_technical_by_hierarchy(dataframe)
    summary = _build_summary(dataframe)
    top_df = dataframe.head(TOP_RESULTS)
    config = PAGE_CONFIGS.get(page_key)
    display_columns = (
        [column for column in config["columns"] if column in dataframe.columns]
        if config
        else list(dataframe.columns)
    )
    page_title = config["title"] if config else "AI Stock Scanner Dashboard"
    page_accent = config["accent"] if config else "#1f4e78"
    selection_enabled = config["selection"] if config else True
    navigation_html = _navigation_html(page_key)
    top_twenty_details = _build_top_twenty_details(dataframe)
    detail_rows = []
    for detail in top_twenty_details:
        difference = detail["difference"]
        change_percent = detail["change_percent"]
        change_class = (
            "price-gain"
            if difference is not None and difference > 0
            else "price-loss"
            if difference is not None and difference < 0
            else ""
        )
        difference_text = (
            f"{difference:+,.2f}"
            if difference is not None
            else "Unavailable"
        )
        percent_text = (
            f"{change_percent:+,.2f}%"
            if change_percent is not None
            else "Unavailable"
        )
        entry_text = (
            f"${detail['entry']:,.2f}"
            if detail["entry"] is not None
            else "Unavailable"
        )
        current_text = (
            f"${detail['current']:,.2f}"
            if detail["current"] is not None
            else "Unavailable"
        )
        support_low_text = (
            f"${detail['support_low']:,.2f}"
            if detail["support_low"] is not None
            else "Unavailable"
        )
        resistance_low_text = (
            f"${detail['resistance_low']:,.2f}"
            if detail["resistance_low"] is not None
            else "Unavailable"
        )
        current_class = (
            " below-support"
            if (
                detail["current"] is not None
                and detail["support_low"] is not None
                and detail["current"] < detail["support_low"]
            )
            else ""
        )
        entry_class = (
            " entry-opportunity"
            if (
                detail["current"] is not None
                and detail["entry"] is not None
                and detail["current"] < detail["entry"]
            )
            else ""
        )
        detail_rows.append(
            f'<tr data-symbol="{_escape_html(detail["symbol"])}" '
            f'data-entry="{_data_number(detail["entry"])}" '
            f'data-support-low="{_data_number(detail["support_low"])}" '
            f'data-resistance-low="{_data_number(detail["resistance_low"])}">'
            f'<td>{_escape_html(detail["symbol"])} '
            f'<span class="detail-current{current_class}">({current_text})</span></td>'
            f'<td class="detail-entry{entry_class}">{entry_text}</td>'
            f'<td class="detail-support-low">{support_low_text}</td>'
            f'<td class="detail-resistance-low">{resistance_low_text}</td>'
            f'<td class="detail-difference {change_class}">{difference_text}</td>'
            f'<td class="detail-percent {change_class}">{percent_text}</td>'
            "</tr>"
        )
    top_twenty_details_markup = (
        '<details class="top20-drilldown">'
        "<summary>Top 20 Qualifying Stocks: Suggested Entry vs Current Price</summary>"
        '<p class="chart-explanation">Entry is the scanner suggestion, not an '
        "actual purchase price. Symbols at or above Resistance Low are excluded.</p>"
        '<div class="table-wrapper"><table id="top20DetailsTable">'
        "<thead><tr><th>Symbol</th><th>Suggested Entry</th>"
        "<th>Support Low</th><th>Resistance Low</th>"
        "<th>Difference</th><th>Change %</th></tr></thead>"
        f"<tbody>{''.join(detail_rows)}</tbody></table></div></details>"
        if detail_rows
        else ""
    )

    # Build table rows for top opportunities
    top_rows_html = []
    for _, row in top_df.iterrows():
        symbol = _escape_html(row.get("Symbol", ""))
        cells = []
        if selection_enabled:
            cells.append(
                '<td class="select-column">'
                f'<input class="exception-select" type="checkbox" value="{symbol}" '
                f'aria-label="Select {symbol}"></td>'
            )
        for col in display_columns:
            value = row[col]
            direction_column = (
                page_key == "technical" and col in TECHNICAL_DIRECTION_COLUMNS
            ) or (
                page_key == "analysts" and col in ANALYST_DIRECTION_COLUMNS
            )
            formatted = (
                _format_symbol_with_price(value, row.get("Current Price"))
                if col == "Symbol"
                else _format_price_level_with_direction(
                    value, row.get("Current Price")
                )
                if direction_column
                else _format_cell(col, value)
            )
            css_class = ""
            if col == "Recommendation":
                css_class = _recommendation_class(value)
            elif col == "Score":
                css_class = _score_class(value)
            elif col == "Current Price":
                css_class = _current_price_rsi_class(row.get("RSI"))
            elif col == "Symbol":
                css_class = (
                    _analyst_support_gap_class(
                        row.get("Current Price"), row.get("Support Low")
                    )
                    if page_key == "analysts"
                    else _symbol_relative_strength_class(row.get("Relative Strength"))
                )
            price_level = (
                f' data-price-level="{_data_number(value)}"'
                if direction_column
                else ""
            )
            cells.append(
                f'<td class="{css_class}"{price_level}>{formatted}</td>'
            )
        top_rows_html.append(
            '<tr '
            f'data-current-price="{_data_number(row.get("Current Price"))}" '
            f'data-target-one="{_data_number(row.get("Target 1"))}" '
            f'data-scanner-rank="{_data_number(row.get("_scanner_rank"))}">'
            f'{"".join(cells)}</tr>'
        )

    # Build table rows for complete results
    all_rows_html = []
    for _, row in dataframe.iterrows():
        symbol = _escape_html(row.get("Symbol", ""))
        cells = []
        if selection_enabled:
            cells.append(
                '<td class="select-column">'
                f'<input class="exception-select" type="checkbox" value="{symbol}" '
                f'aria-label="Select {symbol}"></td>'
            )
        for col in display_columns:
            value = row[col]
            direction_column = (
                page_key == "technical" and col in TECHNICAL_DIRECTION_COLUMNS
            ) or (
                page_key == "analysts" and col in ANALYST_DIRECTION_COLUMNS
            )
            formatted = (
                _format_symbol_with_price(value, row.get("Current Price"))
                if col == "Symbol"
                else _format_price_level_with_direction(
                    value, row.get("Current Price")
                )
                if direction_column
                else _format_cell(col, value)
            )
            css_class = ""
            if col == "Recommendation":
                css_class = _recommendation_class(value)
            elif col == "Score":
                css_class = _score_class(value)
            elif col == "Current Price":
                css_class = _current_price_rsi_class(row.get("RSI"))
            elif col == "Symbol":
                css_class = (
                    _analyst_support_gap_class(
                        row.get("Current Price"), row.get("Support Low")
                    )
                    if page_key == "analysts"
                    else _symbol_relative_strength_class(row.get("Relative Strength"))
                )
            price_level = (
                f' data-price-level="{_data_number(value)}"'
                if direction_column
                else ""
            )
            cells.append(
                f'<td class="{css_class}"{price_level}>{formatted}</td>'
            )
        all_rows_html.append(
            '<tr '
            f'data-current-price="{_data_number(row.get("Current Price"))}" '
            f'data-target-one="{_data_number(row.get("Target 1"))}" '
            f'data-scanner-rank="{_data_number(row.get("_scanner_rank"))}">'
            f'{"".join(cells)}</tr>'
        )

    selection_header_top = (
        '<th class="select-column no-sort"><input class="select-all" '
        'type="checkbox" aria-label="Select all top results"></th>'
        if selection_enabled
        else ""
    )
    selection_header_all = (
        '<th class="select-column no-sort"><input class="select-all" '
        'type="checkbox" aria-label="Select all scan results"></th>'
        if selection_enabled
        else ""
    )
    top_headers = selection_header_top + "".join(
        f"<th>{_escape_html(column)}</th>" for column in display_columns
    )
    all_headers = selection_header_all + "".join(
        f"<th>{_escape_html(column)}</th>" for column in display_columns
    )
    add_exceptions_button = (
        '<button id="addExceptions" type="button" disabled>'
        "Add Selected to Exceptions (0)</button>"
        if selection_enabled
        else '<button id="addExceptions" type="button" hidden disabled></button>'
    )
    target_sort_controls = (
        '<div class="target-sort-controls">'
        '<button id="requestYahooRefresh" type="button">'
        "Refresh Latest Prices</button>"
        '<span id="targetSortStatus" role="status" aria-live="polite">'
        "Loads the latest backend Yahoo price snapshot.</span>"
        "</div>"
        if page_key == "technical"
        else ""
    )

    chart_available = (
        chart_data is not None
        and len(chart_data.get("labels", [])) >= 2
        and len(chart_data.get("labels", [])) == len(chart_data.get("sp500", []))
        and len(chart_data.get("labels", [])) == len(chart_data.get("top20", []))
    )
    chart_markup = (
        '<canvas id="performanceChart" height="200" '
        'aria-label="One-year indexed performance comparison"></canvas>'
        if chart_available
        else (
            '<p class="chart-unavailable" role="status">'
            "Performance chart unavailable: at least two aligned completed "
            "daily closes are required.</p>"
        )
    )
    chart_constituent_copy = (
        f"Equal-weight index uses {len(chart_data['constituents'])} of "
        f"{chart_data['selected_count']} selected Top 20 symbols with usable "
        "aligned history."
        if chart_available
        else ""
    )
    chart_json = json.dumps(chart_data if chart_available else None)
    chart_library = (
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js">'
        "</script>"
        if page_key == "landing"
        else ""
    )
    chart_initialization = (
        f"""
    const chartData = {chart_json};
    const ctx = document.getElementById('performanceChart');
    if (ctx && chartData && typeof Chart !== 'undefined') {{
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: chartData.labels,
                datasets: [
                    {{
                        label: 'S&P 500',
                        data: chartData.sp500,
                        borderColor: '#4fc3f7',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1
                    }},
                    {{
                        label: 'Equal-weight Top 20',
                        data: chartData.top20,
                        borderColor: '#66bb6a',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1
                    }}
                ]
            }},
            options: {{
                responsive: true,
                interaction: {{ mode: 'index', intersect: false }},
                plugins: {{
                    legend: {{ labels: {{ color: '#e0e0e0' }} }},
                    tooltip: {{
                        callbacks: {{
                            label: context => `${{context.dataset.label}}: ${{context.parsed.y.toFixed(2)}}`
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        title: {{ display: true, text: 'Indexed to 100', color: '#b0bec5' }},
                        ticks: {{ color: '#90a4ae' }},
                        grid: {{ color: '#263d50' }}
                    }},
                    x: {{
                        ticks: {{ color: '#90a4ae', maxTicksLimit: 12 }},
                        grid: {{ display: false }}
                    }}
                }}
            }}
        }});
    }}
"""
        if page_key == "landing"
        else ""
    )
    dashboard_content = (
        f"""
    <div class="cards">
        <div class="card"><div class="value">{summary['total_stocks']}</div><div class="label">Stocks Scanned</div></div>
        <div class="card"><div class="value" style="color:#4caf50">{summary['strong_buy']}</div><div class="label">Strong Buy</div></div>
        <div class="card"><div class="value" style="color:#66bb6a">{summary['buy']}</div><div class="label">Buy</div></div>
        <div class="card"><div class="value" style="color:#fdd835">{summary['accumulate']}</div><div class="label">Accumulate</div></div>
        <div class="card"><div class="value" style="color:#ffa726">{summary['watch']}</div><div class="label">Watch</div></div>
        <div class="card"><div class="value" style="color:#ef5350">{summary['avoid']}</div><div class="label">Avoid</div></div>
        <div class="card"><div class="value">{summary['average_score']}</div><div class="label">Avg Score</div></div>
        <div class="card"><div class="value">{summary['highest_score']}</div><div class="label">Best Score</div></div>
    </div>

    <div class="section">
        <h2>One-Year Performance: S&amp;P 500 vs Equal-Weight Top 20</h2>
        <div class="chart-container">
            <div class="refresh-time">Scan completed: {scan_time}</div>
            <div class="refresh-time" id="yahooPriceTime">
                Latest Yahoo price: Loading snapshot time...
            </div>
            <div class="refresh-time" id="backendRefreshTime">
                Backend price refresh: Loading snapshot time...
            </div>
            <div class="price-notice">Manual Yahoo refreshes run securely on GitHub Actions and redeploy these pages.</div>
            <p class="chart-explanation">Completed daily closes, normalized to 100 on the first common date. Values are indexed performance, not raw dollars.</p>
            <p class="chart-explanation">{chart_constituent_copy}</p>
            {chart_markup}
            {top_twenty_details_markup}
        </div>
    </div>
"""
        if page_key == "landing"
        else ""
    )
    results_content = (
        f"""
    <div class="section">
        <h2>{page_title}</h2>
        <div class="tabs">
            <div class="tab active" onclick="switchTab('top', this)">Top {TOP_RESULTS}</div>
            <div class="tab" onclick="switchTab('all', this)">All Results ({summary['total_stocks']})</div>
        </div>

        <div class="filter-bar">
            <input type="text" id="filterInput" placeholder="Filter by symbol or sector..." onkeyup="filterTable()">
            {target_sort_controls}
            {add_exceptions_button}
        </div>

        <div id="tab-top" class="tab-content active">
            <div class="table-wrapper">
                <table id="topTable">
                    <thead><tr>{top_headers}</tr></thead>
                    <tbody>{''.join(top_rows_html)}</tbody>
                </table>
            </div>
        </div>
        <div id="tab-all" class="tab-content">
            <div class="table-wrapper">
                <table id="allTable">
                    <thead><tr>{all_headers}</tr></thead>
                    <tbody>{''.join(all_rows_html)}</tbody>
                </table>
            </div>
        </div>
    </div>
"""
        if page_key != "landing"
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockScanner Dashboard - {scan_time}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1923;
    color: #e0e0e0;
    line-height: 1.6;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
header {{
    background: linear-gradient(135deg, #1a2a3a 0%, #0f1923 100%);
    border-bottom: 2px solid #1f4e78;
    padding: 24px 0;
    margin-bottom: 24px;
}}
header h1 {{ color: #4fc3f7; font-size: 1.8rem; text-align: center; }}
header .subtitle {{ color: #90a4ae; text-align: center; margin-top: 4px; font-size: 0.9rem; }}
.dashboard-nav {{ margin-top: 14px; text-align: center; }}
.dashboard-nav a,
.dashboard-nav .nav-current {{
    display: inline-block;
    padding: 7px 14px;
    color: #4fc3f7;
    border: 1px solid #1f4e78;
    border-radius: 6px;
    text-decoration: none;
}}
.dashboard-nav .nav-current {{
    color: #607d8b;
    background: #162534;
    border-color: #263d50;
    cursor: not-allowed;
    opacity: 0.65;
}}
.cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}}
.card {{
    background: #1a2a3a;
    border: 1px solid #263d50;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}}
.card .value {{ font-size: 1.8rem; font-weight: 700; color: #4fc3f7; }}
.card .label {{ font-size: 0.8rem; color: #90a4ae; margin-top: 4px; text-transform: uppercase; }}
.section {{ margin-bottom: 32px; }}
.section h2 {{
    color: #4fc3f7;
    font-size: 1.2rem;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #263d50;
}}
.chart-container {{
    background: #1a2a3a;
    border: 1px solid #263d50;
    border-radius: 8px;
    padding: 20px;
    width: 100%;
    max-width: none;
    margin: 0 auto 32px;
}}
.refresh-time {{
    color: #90a4ae;
    font-size: 0.8rem;
    margin-bottom: 10px;
    text-align: right;
}}
.price-notice {{
    color: #fdd835;
    font-size: 0.85rem;
    margin-bottom: 12px;
    text-align: right;
}}
.chart-explanation {{ color: #b0bec5; font-size: 0.85rem; margin: 4px 0; }}
.chart-unavailable {{
    color: #ffcc80;
    margin-top: 20px;
    padding: 18px;
    text-align: center;
    border: 1px solid #6d4c2f;
    border-radius: 6px;
}}
.top20-drilldown {{ margin-top: 20px; }}
.top20-drilldown summary {{
    color: #4fc3f7;
    cursor: pointer;
    font-weight: 600;
    padding: 10px 0;
}}
.top20-drilldown .table-wrapper {{ margin-top: 10px; }}
.price-gain {{ color: #66bb6a; font-weight: 600; }}
.price-loss {{ color: #ef5350; font-weight: 600; }}
.below-support {{ color: #66bb6a; font-weight: 600; }}
.entry-opportunity {{ background: #1b5e20; color: #fff; font-weight: 600; }}
.table-wrapper {{
    overflow-x: auto;
    border-radius: 8px;
    border: 1px solid #263d50;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
}}
th {{
    background: {page_accent};
    color: #172217;
    padding: 10px 12px;
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    position: sticky;
    top: 0;
}}
th:hover {{ filter: brightness(0.92); }}
th::after {{ content: ' ⇅'; opacity: 0.4; font-size: 0.7rem; }}
th.no-sort::after {{ content: none; }}
td {{
    padding: 8px 12px;
    border-bottom: 1px solid #1a2a3a;
    white-space: nowrap;
}}
tr:nth-child(even) {{ background: #162330; }}
tr:hover {{ background: #1e3348; }}
.rec-strong-buy {{ background: #1b5e20 !important; color: #c8e6c9; font-weight: 600; }}
.rec-buy {{ background: #2e7d32 !important; color: #c8e6c9; }}
.rec-hold {{ background: #f9a825 !important; color: #1a1a1a; }}
.rec-watch {{ background: #e65100 !important; color: #fff3e0; }}
.rec-avoid {{ background: #b71c1c !important; color: #ffcdd2; }}
.score-excellent {{ background: #1b5e20 !important; color: #c8e6c9; font-weight: 700; }}
.score-good {{ background: #2e7d32 !important; color: #c8e6c9; }}
.score-fair {{ background: #f9a825 !important; color: #1a1a1a; }}
.score-poor {{ background: #b71c1c !important; color: #ffcdd2; }}
.price-rsi-overbought {{ background: #4fb52a !important; color: #102000; font-weight: 600; }}
.price-rsi-upper {{ background: #d8edcc !important; color: #172217; }}
.price-rsi-neutral {{ background: #bfe7f5 !important; color: #10242d; }}
.price-rsi-lower {{ background: #f8ddcc !important; color: #352015; }}
.price-rsi-oversold {{ background: #f47732 !important; color: #2b1105; font-weight: 600; }}
.symbol-rs-strong {{ background: #4fb52a !important; color: #102000; font-weight: 600; }}
.symbol-rs-upper {{ background: #d8edcc !important; color: #172217; }}
.symbol-rs-neutral {{ background: #bfe7f5 !important; color: #10242d; }}
.symbol-rs-lower {{ background: #f8ddcc !important; color: #352015; }}
.symbol-rs-weak {{ background: #f47732 !important; color: #2b1105; font-weight: 600; }}
.symbol-support-above-five {{ background: #f47732 !important; color: #2b1105; font-weight: 600; }}
.symbol-support-above-zero {{ background: #f8ddcc !important; color: #352015; }}
.symbol-support-zero {{ background: #bfe7f5 !important; color: #10242d; }}
.symbol-support-below-zero {{ background: #d8edcc !important; color: #172217; }}
.symbol-support-below-five {{ background: #4fb52a !important; color: #102000; font-weight: 600; }}
.symbol-name {{ display: block; font-weight: 600; }}
.symbol-price {{ display: block; font-size: 0.78em; font-weight: 400; margin-top: -2px; }}
.target-arrow-up {{ color: #66bb6a; font-size: 1.1em; font-weight: 700; }}
.target-arrow-down {{ color: #ef5350; font-size: 1.1em; font-weight: 700; }}
.tabs {{
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
}}
.tab {{
    padding: 8px 20px;
    background: #1a2a3a;
    border: 1px solid #263d50;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    cursor: pointer;
    color: #90a4ae;
    font-size: 0.85rem;
}}
.tab.active {{ background: {page_accent}; color: #172217; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.filter-bar {{
    margin-bottom: 12px;
    display: flex;
    gap: 12px;
    align-items: center;
}}
.filter-bar input {{
    background: #1a2a3a;
    border: 1px solid #263d50;
    border-radius: 4px;
    padding: 6px 12px;
    color: #e0e0e0;
    font-size: 0.85rem;
    width: 250px;
}}
.filter-bar input::placeholder {{ color: #607d8b; }}
.filter-bar {{ justify-content: space-between; flex-wrap: wrap; }}
#addExceptions {{
    padding: 7px 14px;
    color: #fff;
    background: #1b5e20;
    border: 1px solid #66bb6a;
    border-radius: 5px;
    cursor: pointer;
}}
#addExceptions:hover:not(:disabled) {{ background: #2e7d32; }}
#addExceptions:disabled {{ cursor: not-allowed; opacity: 0.45; }}
#requestYahooRefresh {{
    padding: 7px 14px;
    color: #172217;
    background: #c6efce;
    border: 1px solid #70ad47;
    border-radius: 5px;
    cursor: pointer;
}}
#requestYahooRefresh:hover:not(:disabled) {{ filter: brightness(0.92); }}
#requestYahooRefresh:disabled {{ cursor: wait; opacity: 0.65; }}
.target-sort-controls {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
#targetSortStatus {{ color: #90a4ae; font-size: 0.8rem; }}
#targetSortStatus.refresh-error {{ color: #ef9a9a; }}
#targetSortStatus.refresh-success {{ color: #a5d6a7; }}
.select-column {{ width: 48px; text-align: center; }}
.select-column input {{ width: 18px; height: 18px; cursor: pointer; accent-color: #4caf50; }}
@media (max-width: 720px) {{
    .container {{ padding: 12px; }}
    header {{ padding: 18px 0; margin-bottom: 16px; }}
    header h1 {{ font-size: 1.45rem; }}
    .dashboard-nav a,
    .dashboard-nav .nav-current {{ margin: 3px 1px; padding: 7px 10px; }}
    .cards {{ grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .chart-container {{ padding: 12px; }}
    .filter-bar {{ align-items: stretch; }}
    .filter-bar input {{ width: 100%; }}
    .target-sort-controls {{ width: 100%; }}
    .tabs {{ overflow-x: auto; }}
    .tab {{ flex: 0 0 auto; padding: 8px 14px; }}
    th {{ padding: 9px 10px; }}
    td {{ padding: 8px 10px; }}
}}
footer {{
    text-align: center;
    color: #607d8b;
    font-size: 0.75rem;
    margin-top: 40px;
    padding: 16px;
    border-top: 1px solid #263d50;
}}
</style>
</head>
<body>
<header>
    <div class="container">
        <h1>{page_title}</h1>
        <div class="dashboard-nav">
            {navigation_html}
        </div>
    </div>
</header>

<div class="container">
    {dashboard_content}
    {results_content}
</div>

<footer>
    Generated by StockScanner
    &nbsp;|&nbsp; <a href="https://github.com/aksamuel/StockScanner#readme" style="color: #4fc3f7;">Help &amp; FAQ</a>
</footer>

{chart_library}
<script>
// Chart
document.addEventListener('DOMContentLoaded', function() {{
    loadDashboardSnapshotTimes();
    loadRefreshButtonSnapshotTime();
    {chart_initialization}
}});

// Tabs
function switchTab(name, clickedTab) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    clickedTab.classList.add('active');
}}

// Filter
function filterTable() {{
    const filter = document.getElementById('filterInput').value.toUpperCase();
    const activeTab = document.querySelector('.tab-content.active');
    const rows = activeTab.querySelectorAll('tbody tr');
    rows.forEach(row => {{
        const text = row.textContent.toUpperCase();
        row.style.display = text.includes(filter) ? '' : 'none';
    }});
    renumberVisibleRanks(activeTab.querySelector('table'));
}}

function columnIndex(table, label) {{
    return [...table.querySelectorAll('thead th')]
        .findIndex(th => th.textContent.trim() === label);
}}

function renumberVisibleRanks(table) {{
    if (!table) return;
    const rankIndex = columnIndex(table, 'Rank');
    if (rankIndex < 0) return;
    let visibleRank = 0;
    table.querySelectorAll('tbody tr').forEach(row => {{
        if (row.style.display !== 'none') {{
            visibleRank += 1;
            row.children[rankIndex].textContent = visibleRank;
        }}
    }});
}}

function restoreScannerOrder(table) {{
    const tbody = table.querySelector('tbody');
    const rows = [...tbody.querySelectorAll('tr')];
    rows.sort((left, right) => {{
        const leftRank = Number(left.dataset.scannerRank);
        const rightRank = Number(right.dataset.scannerRank);
        return (Number.isFinite(leftRank) ? leftRank : Number.MAX_SAFE_INTEGER)
            - (Number.isFinite(rightRank) ? rightRank : Number.MAX_SAFE_INTEGER);
    }});
    rows.forEach(row => tbody.appendChild(row));
    table.querySelectorAll('th').forEach(header => delete header.dataset.sort);
    renumberVisibleRanks(table);
}}

function snapshotUrl() {{
    const marker = '/reports/';
    const path = window.location.pathname;
    const basePath = path.includes(marker)
        ? path.slice(0, path.indexOf(marker) + 1)
        : path.slice(0, path.lastIndexOf('/') + 1);
    const url = new URL(`${{basePath}}prices.json`, window.location.origin);
    url.searchParams.set('refresh', Date.now().toString());
    return url;
}}

async function loadDashboardSnapshotTimes() {{
    const yahooPriceTime = document.getElementById('yahooPriceTime');
    const backendRefreshTime = document.getElementById('backendRefreshTime');
    if (!yahooPriceTime || !backendRefreshTime) return;
    try {{
        const response = await fetch(snapshotUrl(), {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const snapshot = await response.json();
        if (typeof snapshot.generated_at_new_york !== 'string') {{
            throw new Error('snapshot schema is invalid');
        }}
        yahooPriceTime.textContent = snapshot.price_timestamp_new_york
            ? `Latest Yahoo price: ${{snapshot.price_timestamp_new_york}}`
            : 'Latest Yahoo price: Time unavailable';
        backendRefreshTime.textContent =
            `Backend price refresh: ${{snapshot.generated_at_new_york}}`;
        updateTop20Details(snapshot.prices);
    }} catch (error) {{
        yahooPriceTime.textContent = 'Latest Yahoo price: Unavailable';
        backendRefreshTime.textContent =
            `Backend price refresh: Unavailable (${{error.message}})`;
    }}
}}

function updateTop20Details(prices) {{
    if (!prices || typeof prices !== 'object') return;
    document.querySelectorAll('#top20DetailsTable tbody tr').forEach(row => {{
        const current = Number(prices[row.dataset.symbol]);
        if (!Number.isFinite(current) || current <= 0) return;
        const entry = Number(row.dataset.entry);
        const supportLow = Number(row.dataset.supportLow);
        const resistanceLow = Number(row.dataset.resistanceLow);
        if (
            row.dataset.resistanceLow !== ''
            && Number.isFinite(resistanceLow)
            && current >= resistanceLow
        ) {{
            row.remove();
            return;
        }}
        const currentCell = row.querySelector('.detail-current');
        const entryCell = row.querySelector('.detail-entry');
        currentCell.textContent =
            `($${{current.toLocaleString('en-US', {{
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }})}})`;
        currentCell.classList.toggle(
            'below-support',
            row.dataset.supportLow !== ''
                && Number.isFinite(supportLow)
                && current < supportLow
        );
        entryCell.classList.toggle(
            'entry-opportunity',
            row.dataset.entry !== ''
                && Number.isFinite(entry)
                && entry > 0
                && current < entry
        );
        if (!Number.isFinite(entry) || entry <= 0 || row.dataset.entry === '') return;
        const difference = current - entry;
        const changePercent = difference / entry * 100;
        const changeClass = difference > 0
            ? 'price-gain'
            : difference < 0
            ? 'price-loss'
            : '';
        const differenceCell = row.querySelector('.detail-difference');
        const percentCell = row.querySelector('.detail-percent');
        differenceCell.className = `detail-difference ${{changeClass}}`;
        percentCell.className = `detail-percent ${{changeClass}}`;
        const sign = difference > 0 ? '+' : '';
        differenceCell.textContent =
            `${{sign}}${{difference.toLocaleString('en-US', {{
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }})}}`;
        percentCell.textContent =
            `${{sign}}${{changePercent.toLocaleString('en-US', {{
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }})}}%`;
    }});
}}

function setRefreshButtonTime(button, snapshot) {{
    button.textContent = snapshot.price_timestamp_new_york
        ? `Refresh Latest Prices · ${{snapshot.price_timestamp_new_york}}`
        : 'Refresh Latest Prices · Time unavailable';
}}

async function loadRefreshButtonSnapshotTime() {{
    const button = document.getElementById('requestYahooRefresh');
    if (!button) return;
    try {{
        const response = await fetch(snapshotUrl(), {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const snapshot = await response.json();
        setRefreshButtonTime(button, snapshot);
    }} catch (error) {{
        button.textContent = 'Refresh Latest Prices · Time unavailable';
    }}
}}

function updatePriceRow(row, price) {{
    row.dataset.currentPrice = price.toString();
    const symbolPrice = row.querySelector('.symbol-price');
    if (symbolPrice) {{
        symbolPrice.textContent = `($${{price.toLocaleString('en-US', {{
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }})}})`;
    }}

    const table = row.closest('table');
    const currentPriceIndex = columnIndex(table, 'Current Price');
    if (currentPriceIndex >= 0) {{
        row.children[currentPriceIndex].textContent = price.toLocaleString('en-US', {{
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }});
    }}

    row.querySelectorAll('[data-price-level]').forEach(levelCell => {{
        const level = Number(levelCell.dataset.priceLevel);
        if (!Number.isFinite(level) || levelCell.dataset.priceLevel === '') return;
        levelCell.textContent = `$${{level.toLocaleString('en-US', {{
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }})}}`;
        if (level !== price) {{
            const arrow = document.createElement('span');
            const above = level > price;
            arrow.className = above ? 'target-arrow-up' : 'target-arrow-down';
            arrow.title = above ? 'Above current price' : 'Below current price';
            arrow.textContent = above ? '↑' : '↓';
            levelCell.append(' ', arrow);
        }}
    }});
}}

const yahooRefreshButton = document.getElementById('requestYahooRefresh');
const yahooRefreshStatus = document.getElementById('targetSortStatus');
if (yahooRefreshButton) yahooRefreshButton.addEventListener('click', async () => {{
    yahooRefreshButton.disabled = true;
    yahooRefreshStatus.className = '';
    yahooRefreshStatus.textContent = 'Loading the latest backend price snapshot…';
    try {{
        const response = await fetch(snapshotUrl(), {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const snapshot = await response.json();
        if (
            snapshot?.schema_version !== 1
            || typeof snapshot.generated_at_new_york !== 'string'
            || !snapshot.prices
            || typeof snapshot.prices !== 'object'
            || Array.isArray(snapshot.prices)
        ) {{
            throw new Error('snapshot schema is invalid');
        }}
        setRefreshButtonTime(yahooRefreshButton, snapshot);

        let updatedRows = 0;
        document.querySelectorAll('table tbody tr').forEach(row => {{
            const symbol = row.querySelector('.symbol-name')?.textContent.trim();
            const price = Number(snapshot.prices[symbol]);
            if (symbol && Number.isFinite(price) && price > 0) {{
                updatePriceRow(row, price);
                updatedRows += 1;
            }}
        }});
        document.querySelectorAll('table').forEach(restoreScannerOrder);
        const failureCount = snapshot.failures
            && typeof snapshot.failures === 'object'
            ? Object.keys(snapshot.failures).length
            : 0;
        yahooRefreshStatus.className = 'refresh-success';
        yahooRefreshStatus.textContent =
            `Loaded ${{updatedRows}} displayed prices. Snapshot generated `
            + `${{snapshot.generated_at_new_york}}`
            + (failureCount ? `; ${{failureCount}} backend refresh failure(s) retained prior prices.` : '.');
    }} catch (error) {{
        yahooRefreshStatus.className = 'refresh-error';
        yahooRefreshStatus.textContent =
            `Could not load the latest price snapshot: ${{error.message}}`;
    }} finally {{
        yahooRefreshButton.disabled = false;
    }}
}});

// Add selected scan results to the 30-day exception list
const exceptionSelections = [...document.querySelectorAll('.exception-select')];
const addExceptions = document.getElementById('addExceptions');

function selectedSymbols() {{
    return [...new Set(
        exceptionSelections
            .filter(checkbox => checkbox.checked)
            .map(checkbox => checkbox.value)
    )];
}}

function updateExceptionSelection() {{
    const symbols = selectedSymbols();
    addExceptions.disabled = symbols.length === 0;
    addExceptions.textContent = `Add Selected to Exceptions (${{symbols.length}})`;
    document.querySelectorAll('.tab-content').forEach(tab => {{
        const checkboxes = [...tab.querySelectorAll('.exception-select')];
        const selected = checkboxes.filter(checkbox => checkbox.checked).length;
        const selectAll = tab.querySelector('.select-all');
        selectAll.checked = selected === checkboxes.length && selected > 0;
        selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
    }});
}}

exceptionSelections.forEach(checkbox => checkbox.addEventListener('change', () => {{
    exceptionSelections
        .filter(other => other.value === checkbox.value)
        .forEach(other => other.checked = checkbox.checked);
    updateExceptionSelection();
}}));

document.querySelectorAll('.select-all').forEach(selectAll => {{
    selectAll.addEventListener('change', event => {{
        event.stopPropagation();
        const tab = selectAll.closest('.tab-content');
        tab.querySelectorAll('.exception-select').forEach(checkbox => {{
            checkbox.checked = selectAll.checked;
            exceptionSelections
                .filter(other => other.value === checkbox.value)
                .forEach(other => other.checked = selectAll.checked);
        }});
        updateExceptionSelection();
    }});
}});

if (addExceptions) addExceptions.addEventListener('click', () => {{
    const symbols = selectedSymbols();
    if (symbols.length > 50) {{
        alert('Select no more than 50 tickers per request.');
        return;
    }}
    if (!symbols.length || !confirm(`Add ${{symbols.length}} selected ticker(s) to the exception list for 30 days?`)) return;

    const countLabel = symbols.length === 1 ? '1 ticker' : `${{symbols.length}} tickers`;
    const body = [
        'Please add these tickers to the StockScanner exception list for 30 days:',
        '',
        ...symbols.map(symbol => `- **${{symbol}}**`),
        '',
        `<!-- stockscanner-add-exceptions: ${{symbols.join(',')}} -->`,
    ].join('\\n');
    const query = new URLSearchParams({{
        title: `[Add Exceptions] ${{countLabel}}`,
        body,
    }});
    window.open(
        `https://github.com/aksamuel/StockScanner/issues/new?${{query}}`,
        '_blank',
        'noopener',
    );
}});

// Sortable columns
document.querySelectorAll('th:not(.no-sort)').forEach(th => {{
    th.addEventListener('click', function() {{
        const table = this.closest('table');
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const idx = Array.from(this.parentNode.children).indexOf(this);
        const asc = this.dataset.sort !== 'asc';
        this.parentNode.querySelectorAll('th').forEach(h => delete h.dataset.sort);
        this.dataset.sort = asc ? 'asc' : 'desc';
        rows.sort((a, b) => {{
            let av = a.children[idx].textContent.replace(/[$,%]/g, '').trim();
            let bv = b.children[idx].textContent.replace(/[$,%]/g, '').trim();
            const an = parseFloat(av.replace(/,/g, ''));
            const bn = parseFloat(bv.replace(/,/g, ''));
            if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
            return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        }});
        rows.forEach(row => tbody.appendChild(row));
    }});
}});
</script>
</body>
</html>"""
    return html


def export_html_report(results, quiet=False):
    """Export scan results as linked KPI and analysis pages.

    Each page is self-contained except for Chart.js, which is loaded from a CDN.
    Stable filenames provide navigation, while the timestamped landing page
    preserves compatibility with the report archive.

    Returns the path to the generated HTML file, or None if no data.
    """
    dataframe = prepare_results_dataframe(results)
    if dataframe.empty:
        if not quiet:
            print("No data available for HTML export.")
        return None

    now = datetime.now(NEW_YORK)
    scan_date = now.strftime("%Y-%m-%d")
    date_folder = os.path.join(REPORT_FOLDER, scan_date)
    os.makedirs(date_folder, exist_ok=True)

    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    scan_time = _format_new_york_time(now)
    try:
        write_snapshot_from_results(
            results,
            path=PRICE_SNAPSHOT_PATH,
            generated_at=now,
        )
    except SnapshotError as exc:
        print(f"Price snapshot was not updated: {exc}", file=sys.stderr)
    filename = os.path.join(date_folder, f"StockScanner_Dashboard_{timestamp}.html")
    pages = {
        "landing": os.path.join(date_folder, "landing.html"),
        "technical": os.path.join(date_folder, "technical.html"),
        "analysts": os.path.join(date_folder, "analysts.html"),
        "bought-selection": os.path.join(date_folder, "bought-selection.html"),
    }
    chart_data = _build_kpi_chart_data(dataframe, now=now)
    rendered_pages = {
        page_key: _generate_html(
            dataframe,
            scan_time,
            page_key=page_key,
            chart_data=chart_data if page_key == "landing" else None,
        )
        for page_key in pages
    }
    for page_key, page_filename in pages.items():
        with open(page_filename, "w", encoding="utf-8") as output:
            output.write(rendered_pages[page_key])
    with open(filename, "w", encoding="utf-8") as output:
        output.write(rendered_pages["landing"])

    if not quiet:
        print()
        print("=" * 80)
        print("Linked HTML dashboards created successfully")
        for page_filename in pages.values():
            print(page_filename)
        print("=" * 80)
    return filename

"""Generate a self-contained static HTML dashboard from scan results."""

import os
from datetime import datetime

import pandas as pd

from .report import REPORT_FOLDER, TOP_RESULTS, prepare_results_dataframe


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
        return "symbol-rs-strong"
    if value > 0:
        return "symbol-rs-upper"
    if value == 0:
        return "symbol-rs-neutral"
    if value >= -5:
        return "symbol-rs-lower"
    return "symbol-rs-weak"


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
PAGE_CONFIGS = {
    "technical": {
        "title": "Technical Analysis Page",
        "columns": [
            "Rank", "Symbol", "Sector", "RSI", "Score", "Recommendation",
            "Signal", "Trend", "MACD", "Entry", "Target 1", "Target 2",
            "Target 3", "20 MA", "50 MA", "200 MA", "Stop Loss",
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


def _generate_html(dataframe, scan_time, page_key=None):
    """Generate the complete HTML dashboard string."""
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
            formatted = (
                _format_symbol_with_price(value, row.get("Current Price"))
                if col == "Symbol"
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
                css_class = _symbol_relative_strength_class(
                    row.get("Relative Strength")
                )
            cells.append(f'<td class="{css_class}">{formatted}</td>')
        top_rows_html.append(
            '<tr '
            f'data-current-price="{_data_number(row.get("Current Price"))}" '
            f'data-target-one="{_data_number(row.get("Target 1"))}">'
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
            formatted = (
                _format_symbol_with_price(value, row.get("Current Price"))
                if col == "Symbol"
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
                css_class = _symbol_relative_strength_class(
                    row.get("Relative Strength")
                )
            cells.append(f'<td class="{css_class}">{formatted}</td>')
        all_rows_html.append(
            '<tr '
            f'data-current-price="{_data_number(row.get("Current Price"))}" '
            f'data-target-one="{_data_number(row.get("Target 1"))}">'
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
        '<button id="sortTargetUpside" type="button">'
        "Rank by Target 1 Upside</button>"
        '<span id="targetSortStatus" aria-live="polite"></span>'
        "</div>"
        if page_key == "technical"
        else ""
    )

    # Chart data
    chart_labels = ["Strong Buy", "Buy", "Accumulate", "Hold", "Watch", "Avoid"]
    chart_values = [
        summary["strong_buy"], summary["buy"], summary["accumulate"],
        summary["hold"], summary["watch"], summary["avoid"],
    ]

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
.dashboard-nav a {{
    display: inline-block;
    padding: 7px 14px;
    color: #4fc3f7;
    border: 1px solid #1f4e78;
    border-radius: 6px;
    text-decoration: none;
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
    max-width: 600px;
    margin: 0 auto 32px;
}}
.refresh-time {{
    color: #90a4ae;
    font-size: 0.8rem;
    margin-bottom: 10px;
    text-align: right;
}}
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
.symbol-name {{ display: block; font-weight: 600; }}
.symbol-price {{ display: block; font-size: 0.78em; font-weight: 400; margin-top: -2px; }}
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
#sortTargetUpside {{
    padding: 7px 14px;
    color: #172217;
    background: #c6efce;
    border: 1px solid #70ad47;
    border-radius: 5px;
    cursor: pointer;
}}
#sortTargetUpside:hover {{ filter: brightness(0.92); }}
.target-sort-controls {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
#targetSortStatus {{ color: #90a4ae; font-size: 0.8rem; }}
.select-column {{ width: 48px; text-align: center; }}
.select-column input {{ width: 18px; height: 18px; cursor: pointer; accent-color: #4caf50; }}
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
            <a href="index.html">Technical Analysis</a>
            <a href="analysts.html">Analysts Rating</a>
            <a href="bought-selection.html">Bought Selection</a>
            <a href="exceptions.html">Exception List</a>
        </div>
    </div>
</header>

<div class="container">
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
        <h2>Recommendation Breakdown</h2>
        <div class="chart-container">
            <div class="refresh-time">Page refreshed as of: {scan_time}</div>
            <canvas id="recChart" height="200"></canvas>
        </div>
    </div>

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
</div>

<footer>
    Generated by StockScanner
    &nbsp;|&nbsp; <a href="https://github.com/aksamuel/StockScanner#readme" style="color: #4fc3f7;">Help &amp; FAQ</a>
</footer>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
// Chart
document.addEventListener('DOMContentLoaded', function() {{
    const ctx = document.getElementById('recChart');
    if (ctx && typeof Chart !== 'undefined') {{
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {chart_labels},
                datasets: [{{
                    label: 'Stocks',
                    data: {chart_values},
                    backgroundColor: ['#1b5e20','#4caf50','#fdd835','#ff9800','#e65100','#b71c1c'],
                    borderWidth: 0,
                    borderRadius: 4,
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    y: {{ beginAtZero: true, ticks: {{ color: '#90a4ae' }}, grid: {{ color: '#263d50' }} }},
                    x: {{ ticks: {{ color: '#90a4ae' }}, grid: {{ display: false }} }}
                }}
            }}
        }});
    }}
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
}}

// Temporary display-only ranking by Target 1 percentage upside.
const sortTargetUpside = document.getElementById('sortTargetUpside');
if (sortTargetUpside) {{
    sortTargetUpside.addEventListener('click', () => {{
        document.querySelectorAll('.tab-content table').forEach(table => {{
            const tbody = table.querySelector('tbody');
            const rows = [...tbody.querySelectorAll('tr')];
            rows.sort((left, right) => {{
                const leftPrice = Number(left.dataset.currentPrice);
                const leftTarget = Number(left.dataset.targetOne);
                const rightPrice = Number(right.dataset.currentPrice);
                const rightTarget = Number(right.dataset.targetOne);
                const leftUpside = leftPrice > 0 && leftTarget > 0
                    ? (leftTarget - leftPrice) / leftPrice
                    : Number.NEGATIVE_INFINITY;
                const rightUpside = rightPrice > 0 && rightTarget > 0
                    ? (rightTarget - rightPrice) / rightPrice
                    : Number.NEGATIVE_INFINITY;
                return rightUpside - leftUpside;
            }});
            const rankIndex = [...table.querySelectorAll('thead th')]
                .findIndex(header => header.textContent.trim() === 'Rank');
            rows.forEach((row, index) => {{
                tbody.appendChild(row);
                if (rankIndex >= 0) row.children[rankIndex].textContent = index + 1;
            }});
        }});
        document.getElementById('targetSortStatus').textContent =
            'Temporarily ranked by Target 1 percentage upside using page-refresh prices.';
    }});
}}

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

addExceptions.addEventListener('click', () => {{
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
    """Export scan results as three linked HTML dashboard pages.

    Each page is self-contained except for Chart.js, which is loaded from a CDN.
    Stable filenames provide navigation, while the timestamped technical page
    preserves compatibility with the report archive.

    Returns the path to the generated HTML file, or None if no data.
    """
    dataframe = prepare_results_dataframe(results)
    if dataframe.empty:
        if not quiet:
            print("No data available for HTML export.")
        return None

    now = datetime.now()
    scan_date = now.strftime("%Y-%m-%d")
    date_folder = os.path.join(REPORT_FOLDER, scan_date)
    os.makedirs(date_folder, exist_ok=True)

    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    scan_time = now.strftime("%d %B %Y, %I:%M %p")
    filename = os.path.join(date_folder, f"StockScanner_Dashboard_{timestamp}.html")
    pages = {
        "technical": os.path.join(date_folder, "technical.html"),
        "analysts": os.path.join(date_folder, "analysts.html"),
        "bought-selection": os.path.join(date_folder, "bought-selection.html"),
    }
    rendered_pages = {
        page_key: _generate_html(dataframe, scan_time, page_key=page_key)
        for page_key in pages
    }
    for page_key, page_filename in pages.items():
        with open(page_filename, "w", encoding="utf-8") as output:
            output.write(rendered_pages[page_key])
    with open(filename, "w", encoding="utf-8") as output:
        output.write(rendered_pages["technical"])

    if not quiet:
        print()
        print("=" * 80)
        print("Linked HTML dashboards created successfully")
        for page_filename in pages.values():
            print(page_filename)
        print("=" * 80)
    return filename

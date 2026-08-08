"""Generate a static HTML dashboard for the stock exception list."""

import csv
import html
import os
from datetime import datetime

from .config import EXCEPTION_LIST


def _load_rows(csv_path):
    """Load non-empty exception rows while preserving the CSV columns."""
    with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        rows = [
            {column: (row.get(column) or "").strip() for column in columns}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]
    return columns, rows


def _generate_html(columns, rows, generated_at):
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(row.get(column, ''))}</td>" for column in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")

    table_body = "\n".join(body_rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockScanner Exception List</title>
<style>
* {{ box-sizing: border-box; }}
body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f1923;
    color: #e0e0e0;
    line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
header {{
    padding: 24px 0;
    margin-bottom: 24px;
    background: linear-gradient(135deg, #1a2a3a 0%, #0f1923 100%);
    border-bottom: 2px solid #1f4e78;
    text-align: center;
}}
h1 {{ margin: 0; color: #4fc3f7; font-size: 1.8rem; }}
.subtitle {{ color: #90a4ae; margin-top: 4px; font-size: 0.9rem; }}
.nav {{ margin-top: 14px; }}
.nav a {{
    display: inline-block;
    padding: 7px 14px;
    color: #4fc3f7;
    border: 1px solid #1f4e78;
    border-radius: 6px;
    text-decoration: none;
}}
.summary {{
    display: inline-block;
    margin-bottom: 18px;
    padding: 14px 20px;
    background: #1a2a3a;
    border: 1px solid #263d50;
    border-radius: 8px;
}}
.summary strong {{ color: #4fc3f7; font-size: 1.4rem; }}
input {{
    width: min(100%, 360px);
    margin-bottom: 14px;
    padding: 10px 12px;
    color: #e0e0e0;
    background: #162534;
    border: 1px solid #365069;
    border-radius: 6px;
}}
.table-wrap {{ overflow-x: auto; border: 1px solid #263d50; border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; background: #1a2a3a; }}
th, td {{ padding: 11px 14px; border-bottom: 1px solid #263d50; text-align: left; }}
th {{ color: #4fc3f7; background: #162534; cursor: pointer; white-space: nowrap; }}
tr:hover td {{ background: #203548; }}
.empty {{ padding: 24px; color: #90a4ae; text-align: center; }}
footer {{ margin-top: 30px; color: #607d8b; font-size: 0.8rem; text-align: center; }}
</style>
</head>
<body>
<header>
    <div class="container">
        <h1>Stock Exception List</h1>
        <div class="subtitle">Updated: {html.escape(generated_at)}</div>
        <div class="nav"><a href="index.html">Back to Scanner Dashboard</a></div>
    </div>
</header>
<main class="container">
    <div class="summary"><strong>{len(rows)}</strong><br>Listed exceptions</div>
    <div><input id="filter" type="search" placeholder="Filter exceptions..." aria-label="Filter exceptions"></div>
    <div class="table-wrap">
        <table id="exceptions">
            <thead><tr>{headers}</tr></thead>
            <tbody>{table_body}</tbody>
        </table>
        <div id="empty" class="empty" hidden>No matching exceptions found.</div>
    </div>
</main>
<footer>Generated from watchlists/exceptions.csv</footer>
<script>
const filter = document.getElementById("filter");
const rows = [...document.querySelectorAll("#exceptions tbody tr")];
const empty = document.getElementById("empty");
filter.addEventListener("input", () => {{
    const query = filter.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach(row => {{
        const show = row.textContent.toLowerCase().includes(query);
        row.hidden = !show;
        if (show) visible++;
    }});
    empty.hidden = visible !== 0;
}});
</script>
</body>
</html>
"""


def export_exceptions_dashboard(
    csv_path=EXCEPTION_LIST, output_path="exceptions.html", generated_at=None
):
    """Write the exception-list dashboard and return its output path."""
    columns, rows = _load_rows(csv_path)
    if not columns:
        raise ValueError(f"Exception list has no columns: {csv_path}")

    generated_at = generated_at or datetime.now().strftime("%d %B %Y, %I:%M %p")
    output_directory = os.path.dirname(output_path)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(_generate_html(columns, rows, generated_at))
    return output_path


if __name__ == "__main__":
    export_exceptions_dashboard()

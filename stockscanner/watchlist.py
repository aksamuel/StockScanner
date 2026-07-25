import datetime
import os

import pandas as pd

from stockscanner.config import EXCEPTION_LIST


def load_watchlist():
    df = pd.read_csv("watchlists/watchlist.csv")
    df = df[df["Enabled"] == "Yes"]
    return df


def _parse_date(value):
    """Parse a date value from the Excel file. Returns a date or None."""
    if pd.isna(value):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Normalize month abbreviation to title-case for strptime compatibility
    parts = text.split("/")
    if len(parts) == 3:
        parts[1] = parts[1].capitalize()
        text = "/".join(parts)
    try:
        return datetime.datetime.strptime(text, "%d/%b/%Y").date()
    except (ValueError, TypeError):
        return None


def _is_active_exception(date_from, date_to, today):
    """Check if an exception is active based on its date range and today's date."""
    if date_from is None and date_to is None:
        return True
    if date_from is not None and date_to is not None:
        return date_from <= today <= date_to
    if date_from is not None:
        return today >= date_from
    return today <= date_to


def load_exceptions():
    """Load excluded ticker symbols from the exceptions Excel file.

    Returns a set of uppercase ticker symbols to exclude from results.
    Skips rows where Symbol is empty or starts with 'EXAMPLE'.
    Respects optional Date From / Date To columns for time-bounded exclusions.
    Returns an empty set if the file doesn't exist or is empty.
    """
    if not os.path.exists(EXCEPTION_LIST):
        return set()

    try:
        df = pd.read_excel(EXCEPTION_LIST, sheet_name="Exceptions", engine="openpyxl")
    except Exception:
        return set()

    if "Symbol" not in df.columns or df.empty:
        return set()

    today = datetime.date.today()
    has_date_from = "Date From" in df.columns
    has_date_to = "Date To" in df.columns
    excluded = set()

    for _, row in df.iterrows():
        symbol = row.get("Symbol")
        if pd.isna(symbol):
            continue
        symbol = str(symbol).strip().upper()
        if not symbol or symbol.startswith("EXAMPLE"):
            continue

        date_from = _parse_date(row["Date From"]) if has_date_from else None
        date_to = _parse_date(row["Date To"]) if has_date_to else None

        if _is_active_exception(date_from, date_to, today):
            excluded.add(symbol)

    return excluded

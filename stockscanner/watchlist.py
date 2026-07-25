import os

import pandas as pd

from stockscanner.config import EXCEPTION_LIST


def load_watchlist():
    df = pd.read_csv("watchlists/watchlist.csv")
    df = df[df["Enabled"] == "Yes"]
    return df


def load_exceptions():
    """Load excluded ticker symbols from the exceptions Excel file.

    Returns a set of uppercase ticker symbols to exclude from results.
    Skips rows where Symbol is empty or starts with 'EXAMPLE'.
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

    symbols = df["Symbol"].dropna().astype(str).str.strip().str.upper()
    symbols = symbols[symbols != ""]
    symbols = symbols[~symbols.str.startswith("EXAMPLE")]

    return set(symbols)

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


CACHE_DAYS = 7


def _cache_path(symbol):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    history_dir = os.path.join(root, "history")
    os.makedirs(history_dir, exist_ok=True)
    safe = str(symbol).replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(history_dir, f"{safe}.csv")


def download_data(symbol, force=False, period="1y", cache_days=CACHE_DAYS):
    """Download historical data for `symbol` with a simple on-disk CSV cache.

    - `force`: bypass cache and re-download
    - `period`: yfinance period (default "1y")
    - `cache_days`: TTL in days for cached files
    """
    path = _cache_path(symbol)
    if not force and os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            age_days = (time.time() - mtime) / 86400.0
            if age_days <= cache_days:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                # ensure DataFrame has expected columns
                if not df.empty:
                    return df
        except Exception:
            # fall through to re-download on any cache read error
            pass

    stock = yf.Ticker(symbol)
    df = stock.history(period=period)

    if df is None:
        return df

    # persist to CSV (safe write)
    try:
        tmp = path + ".tmp"
        df.to_csv(tmp)
        os.replace(tmp, path)
    except Exception:
        # ignore cache write errors
        pass

    return df

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


CACHE_DAYS = 1
NEW_YORK = ZoneInfo("America/New_York")


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


def completed_daily_data(dataframe, now=None):
    """Remove today's incomplete daily candle, if Yahoo returned one."""
    if dataframe is None or dataframe.empty or not isinstance(
        dataframe.index, pd.DatetimeIndex
    ):
        return dataframe

    now = now or datetime.now(NEW_YORK)
    if now.tzinfo is None:
        now = now.replace(tzinfo=NEW_YORK)
    else:
        now = now.astimezone(NEW_YORK)

    latest_timestamp = dataframe.index[-1]
    if latest_timestamp.tzinfo is None:
        latest_date = latest_timestamp.date()
    else:
        latest_date = latest_timestamp.tz_convert(NEW_YORK).date()
    if latest_date >= now.date():
        return dataframe.iloc[:-1].copy()
    return dataframe


def download_intraday_snapshot(symbol, now=None):
    """Return today's latest extended-hours price and cumulative volume."""
    now = now or datetime.now(NEW_YORK)
    if now.tzinfo is None:
        now = now.replace(tzinfo=NEW_YORK)
    else:
        now = now.astimezone(NEW_YORK)

    intraday = yf.Ticker(symbol).history(
        period="1d",
        interval="1m",
        prepost=True,
    )
    if intraday is None or intraday.empty:
        return None

    valid = intraday.dropna(subset=["Close"])
    if valid.empty:
        return None
    timestamp = valid.index[-1]
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(NEW_YORK)
    else:
        timestamp = timestamp.tz_convert(NEW_YORK)
    if timestamp.date() != now.date():
        return None

    if "Volume" in valid.columns:
        volume = pd.to_numeric(valid["Volume"], errors="coerce").fillna(0).sum()
    else:
        volume = 0
    return {
        "price": float(valid["Close"].iloc[-1]),
        "volume": float(volume),
        "timestamp": timestamp.isoformat(),
    }


def _chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def download_data_bulk(symbols, force=False, period="1y", cache_days=CACHE_DAYS, chunk_size=100, pause_between_chunks=1.0, progress=False):
    """Download historical data for a list of `symbols` in chunks and cache each symbol to disk.

    - `symbols`: iterable of symbol strings
    - `force`: bypass cache and re-download for each symbol
    - `period`: yfinance period
    - `cache_days`: TTL used to decide whether to skip cached files
    - `chunk_size`: how many tickers to request in a single yfinance.download call
    - `pause_between_chunks`: seconds to sleep between chunk downloads to reduce rate pressure
    Returns: dict mapping symbol -> DataFrame (for successfully downloaded or cached symbols)
    """
    results = {}
    symbols = list(dict.fromkeys([str(s).strip().upper() for s in symbols if s]))
    if not symbols:
        return results

    to_download = []
    for s in symbols:
        path = _cache_path(s)
        if not force and os.path.exists(path):
            try:
                mtime = os.path.getmtime(path)
                age_days = (time.time() - mtime) / 86400.0
                if age_days <= cache_days:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                    if not df.empty:
                        results[s] = df
                        if progress:
                            try:
                                print(f"Skipping cached: {s}")
                            except Exception:
                                pass
                        continue
            except Exception:
                pass
        to_download.append(s)

    import yfinance as yf
    import time as _time

    total = len(to_download)
    if progress:
        try:
            print(f"Starting bulk download: {total} symbols, chunk_size={chunk_size}")
        except Exception:
            pass

    num_chunks = (total + chunk_size - 1) // chunk_size if total else 0
    chunk_idx = 0

    for chunk in _chunked(to_download, chunk_size):
        chunk_idx += 1
        if progress:
            try:
                print(f"Chunk {chunk_idx}/{num_chunks}: downloading {len(chunk)} symbols...")
            except Exception:
                pass
        try:
            df_all = yf.download(tickers=chunk, period=period, group_by="ticker", threads=True, progress=False)
        except Exception:
            df_all = None

        before_count = len(results)
        if df_all is None or df_all.empty:
            # try per-symbol fallback
            for s in chunk:
                try:
                    df = yf.Ticker(s).history(period=period)
                    if df is not None and not df.empty:
                        path = _cache_path(s)
                        try:
                            tmp = path + ".tmp"
                            df.to_csv(tmp)
                            os.replace(tmp, path)
                        except Exception:
                            pass
                        results[s] = df
                        if progress:
                            try:
                                print(f"Downloaded {s} (fallback)")
                            except Exception:
                                pass
                except Exception:
                    continue
        else:
            # df_all may be a multi-column DataFrame grouped by ticker
            # yfinance returns either a MultiIndex columns (ticker, field) or a flat DF for single-ticker
            if isinstance(df_all.columns, pd.MultiIndex):
                for s in chunk:
                    try:
                        if s in df_all.columns.levels[0]:
                            df = df_all[s].copy()
                        else:
                            # some tickers may have '.' suffixes in yfinance output, try case-insensitive match
                            matches = [c for c in df_all.columns.levels[0] if str(c).upper() == s]
                            if matches:
                                df = df_all[matches[0]].copy()
                            else:
                                df = None
                        if df is not None and not df.empty:
                            path = _cache_path(s)
                            try:
                                tmp = path + ".tmp"
                                df.to_csv(tmp)
                                os.replace(tmp, path)
                            except Exception:
                                pass
                            results[s] = df
                            if progress:
                                try:
                                    print(f"Downloaded {s}")
                                except Exception:
                                    pass
                    except Exception:
                        continue
            else:
                # flat DataFrame, assume single ticker requested
                # attempt to map chunk[0] to df_all
                for s in chunk:
                    try:
                        df = df_all.copy()
                        if df is not None and not df.empty:
                            path = _cache_path(s)
                            try:
                                tmp = path + ".tmp"
                                df.to_csv(tmp)
                                os.replace(tmp, path)
                            except Exception:
                                pass
                            results[s] = df
                            if progress:
                                try:
                                    print(f"Downloaded {s}")
                                except Exception:
                                    pass
                    except Exception:
                        continue

        after_count = len(results)
        chunk_downloaded = after_count - before_count
        if progress:
            try:
                print(f"Chunk {chunk_idx} complete: downloaded {chunk_downloaded}/{len(chunk)} this chunk (total cached so far: {after_count})")
            except Exception:
                pass

        if pause_between_chunks and len(to_download) > chunk_size:
            try:
                _time.sleep(pause_between_chunks)
            except Exception:
                pass

    return results

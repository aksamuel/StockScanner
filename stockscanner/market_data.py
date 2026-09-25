
import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

CACHE_DAYS = 7
_CACHE_LOCK = threading.RLock()


def _cache_path(symbol):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    history_dir = os.path.join(root, "history")
    os.makedirs(history_dir, exist_ok=True)
    safe = str(symbol).replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(history_dir, f"{safe}.csv")


def _initialize_cache_directory():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(os.path.join(root, "history"), exist_ok=True)


def _download_with_retry(symbol, fetcher, *, max_retries=3, base_delay=0.25):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return fetcher()
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(base_delay * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Download retry failed for {symbol!r}")


def download_data(symbol, force=False, period="1y", cache_days=CACHE_DAYS):
    """Download historical data for `symbol` with a simple on-disk CSV cache.

    - `force`: bypass cache and re-download
    - `period`: yfinance period (default "1y")
    - `cache_days`: TTL in days for cached files
    """
    _initialize_cache_directory()
    path = _cache_path(symbol)
    if not force and os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            age_days = (time.time() - mtime) / 86400.0
            if age_days <= cache_days:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                if not df.empty:
                    return df
        except Exception:
            pass

    with _CACHE_LOCK:
        if not force and os.path.exists(path):
            try:
                mtime = os.path.getmtime(path)
                age_days = (time.time() - mtime) / 86400.0
                if age_days <= cache_days:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                    if not df.empty:
                        return df
            except Exception:
                pass

        def fetcher():
            stock = yf.Ticker(symbol)
            df = stock.history(period=period)
            if df is None:
                return df
            tmp = path + ".tmp"
            df.to_csv(tmp)
            os.replace(tmp, path)
            return df

        return _download_with_retry(symbol, fetcher)


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

    _initialize_cache_directory()
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

    total = len(to_download)
    if progress:
        try:
            print(f"Starting bulk download: {total} symbols, chunk_size={chunk_size}")
        except Exception:
            pass

    import time as _time
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
            with _CACHE_LOCK:
                df_all = yf.download(tickers=chunk, period=period, group_by="ticker", threads=True, progress=False)
        except Exception:
            df_all = None

        before_count = len(results)
        if df_all is None or df_all.empty:
            for s in chunk:
                try:
                    def fetcher():
                        return yf.Ticker(s).history(period=period)

                    with _CACHE_LOCK:
                        df = _download_with_retry(s, fetcher)
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
            if isinstance(df_all.columns, pd.MultiIndex):
                for s in chunk:
                    try:
                        if s in df_all.columns.levels[0]:
                            df = df_all[s].copy()
                        else:
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

"""Store and load the current NYSE ticker universe in Supabase."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from .universe import fetch_current_nyse_tickers


DEFAULT_TIMEOUT_SECONDS = 30
NEW_YORK = ZoneInfo("America/New_York")
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")


class TickerUniverseStoreError(RuntimeError):
    """Raised when the Supabase ticker universe cannot be stored or loaded."""


def _headers(secret_key, *, content_type=False):
    headers = {
        "apikey": secret_key,
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    # Legacy service_role keys are JWTs and still require Authorization. New
    # sb_secret_* keys must be sent only through the apikey header.
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    return headers


def _request_json(request, *, opener, timeout):
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TickerUniverseStoreError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError) as exc:
        raise TickerUniverseStoreError(f"Unable to reach Supabase: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise TickerUniverseStoreError("Supabase returned invalid JSON") from exc


def _require_credentials(supabase_url, secret_key):
    if not supabase_url:
        raise TickerUniverseStoreError("SUPABASE_URL is required")
    if not secret_key:
        raise TickerUniverseStoreError("SUPABASE_SECRET_KEY is required")


def ticker_records(tickers):
    """Normalize a dataframe into the records accepted by the database RPC."""
    if not isinstance(tickers, pd.DataFrame) or tickers.empty:
        raise TickerUniverseStoreError("Ticker universe must be a non-empty dataframe")

    required = {"Symbol", "Security Name", "Exchange"}
    missing = sorted(required.difference(tickers.columns))
    if missing:
        raise TickerUniverseStoreError(
            f"Ticker universe is missing columns: {', '.join(missing)}"
        )

    normalized = tickers.copy()
    normalized["Symbol"] = normalized["Symbol"].fillna("").astype(str).str.strip().str.upper()
    normalized["Security Name"] = normalized["Security Name"].fillna("").astype(str)
    normalized["Exchange"] = normalized["Exchange"].fillna("").astype(str).str.strip().str.upper()
    if "Market Cap" not in normalized.columns:
        normalized["Market Cap"] = 0
    normalized["Market Cap"] = (
        pd.to_numeric(normalized["Market Cap"], errors="coerce")
        .fillna(0)
        .clip(lower=0)
        .astype("int64")
    )
    normalized = normalized.drop_duplicates(subset=["Symbol"])

    invalid = [
        symbol
        for symbol in normalized["Symbol"]
        if not TICKER_PATTERN.fullmatch(symbol)
    ]
    if invalid:
        raise TickerUniverseStoreError(
            f"Ticker universe contains invalid symbols: {', '.join(invalid[:5])}"
        )
    if (normalized["Exchange"] == "").any():
        raise TickerUniverseStoreError("Ticker universe contains a blank exchange")

    return [
        {
            "symbol": row["Symbol"],
            "security_name": row["Security Name"],
            "exchange": row["Exchange"],
            "market_cap": int(row["Market Cap"]),
        }
        for row in normalized.to_dict("records")
    ]


def store_ticker_universe(
    tickers,
    *,
    supabase_url,
    secret_key,
    refreshed_at=None,
    source="yahoo_screener",
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Atomically replace the current Supabase ticker universe."""
    _require_credentials(supabase_url, secret_key)
    refreshed_at = refreshed_at or datetime.now(timezone.utc)
    if refreshed_at.tzinfo is None:
        raise TickerUniverseStoreError("refreshed_at must be timezone-aware")

    payload = {
        "p_refreshed_at": refreshed_at.isoformat(),
        "p_source": source,
        "p_tickers": ticker_records(tickers),
    }
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/rpc/replace_nyse_tickers"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(secret_key, content_type=True),
        method="POST",
    )
    stored = _request_json(request, opener=opener, timeout=timeout)
    if not isinstance(stored, list) or len(stored) != 1:
        raise TickerUniverseStoreError(
            "Supabase did not confirm the ticker-universe replacement"
        )
    if stored[0].get("symbol_count") != len(payload["p_tickers"]):
        raise TickerUniverseStoreError("Supabase confirmed an unexpected ticker count")
    return stored[0]


def latest_ticker_refresh(
    *,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Return the newest ticker refresh metadata, or None when the table is empty."""
    _require_credentials(supabase_url, secret_key)
    query = urlencode(
        {
            "select": "refreshed_at,source",
            "order": "refreshed_at.desc",
            "limit": 1,
        }
    )
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/nyse_tickers?{query}"
    request = Request(endpoint, headers=_headers(secret_key), method="GET")
    rows = _request_json(request, opener=opener, timeout=timeout)
    if not isinstance(rows, list):
        raise TickerUniverseStoreError("Supabase returned invalid ticker metadata")
    return rows[0] if rows else None


def load_latest_ticker_universe(
    *,
    supabase_url,
    secret_key,
    limit=None,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    page_size=1000,
):
    """Load the current normalized NYSE universe from Supabase."""
    metadata = latest_ticker_refresh(
        supabase_url=supabase_url,
        secret_key=secret_key,
        opener=opener,
        timeout=timeout,
    )
    if metadata is None:
        raise TickerUniverseStoreError("Supabase NYSE ticker universe is empty")

    query = urlencode(
        {
            "select": "symbol,security_name,exchange,market_cap,refreshed_at",
            "order": "market_cap.desc,symbol.asc",
        }
    )
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/nyse_tickers?{query}"
    rows = []
    start = 0
    while True:
        headers = _headers(secret_key)
        headers["Range-Unit"] = "items"
        headers["Range"] = f"{start}-{start + page_size - 1}"
        request = Request(endpoint, headers=headers, method="GET")
        batch = _request_json(request, opener=opener, timeout=timeout)
        if not isinstance(batch, list):
            raise TickerUniverseStoreError("Supabase returned invalid ticker rows")
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size

    if not rows:
        raise TickerUniverseStoreError("Supabase NYSE ticker universe is empty")

    frame = pd.DataFrame(rows).rename(
        columns={
            "symbol": "Symbol",
            "security_name": "Security Name",
            "exchange": "Exchange",
            "market_cap": "Market Cap",
        }
    )
    frame["Market Cap"] = pd.to_numeric(
        frame["Market Cap"], errors="coerce"
    ).fillna(0).astype("int64")
    frame = frame[["Symbol", "Security Name", "Exchange", "Market Cap"]]
    if limit is not None:
        frame = frame.head(limit)
    return frame.reset_index(drop=True)


def refresh_ticker_universe(
    *,
    supabase_url,
    secret_key,
    force=False,
    now=None,
    not_before_hour=8,
    downloader=fetch_current_nyse_tickers,
    opener=urlopen,
):
    """Refresh once per New York date, never before the configured local hour."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise TickerUniverseStoreError("now must be timezone-aware")
    new_york_now = now.astimezone(NEW_YORK)

    if not force and new_york_now.hour < not_before_hour:
        return {
            "stored": False,
            "reason": "before_schedule",
            "new_york_date": new_york_now.date().isoformat(),
        }

    latest = latest_ticker_refresh(
        supabase_url=supabase_url,
        secret_key=secret_key,
        opener=opener,
    )
    if latest and not force:
        latest_time = datetime.fromisoformat(
            latest["refreshed_at"].replace("Z", "+00:00")
        )
        if latest_time.astimezone(NEW_YORK).date() == new_york_now.date():
            return {
                "stored": False,
                "reason": "already_refreshed",
                "new_york_date": new_york_now.date().isoformat(),
            }

    try:
        downloaded = downloader()
    except Exception as exc:
        raise TickerUniverseStoreError(
            "NYSE ticker download failed; the current Supabase list was preserved"
        ) from exc
    if isinstance(downloaded, tuple):
        tickers, source = downloaded
    else:
        tickers, source = downloaded, "yahoo_screener"
    stored = store_ticker_universe(
        tickers,
        supabase_url=supabase_url,
        secret_key=secret_key,
        refreshed_at=now,
        source=source,
        opener=opener,
    )
    return {
        "stored": True,
        "symbol_count": stored["symbol_count"],
        "refreshed_at": stored["refreshed_at"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh immediately, bypassing the daily time and duplicate guards.",
    )
    args = parser.parse_args(argv)

    try:
        result = refresh_ticker_universe(
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            secret_key=os.environ.get("SUPABASE_SECRET_KEY", ""),
            force=args.force,
        )
    except TickerUniverseStoreError as exc:
        parser.error(str(exc))

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

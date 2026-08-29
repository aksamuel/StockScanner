"""Free market-price provider clients used by the hourly snapshot job."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ALPACA_SNAPSHOT_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
TWELVE_DATA_PRICE_URL = "https://api.twelvedata.com/price"
ALPACA_BATCH_SIZE = 100
TWELVE_DATA_FREE_SYMBOLS_PER_RUN = 8
DEFAULT_TIMEOUT_SECONDS = 20


class PriceProviderError(RuntimeError):
    """Raised when a market-price provider cannot serve a request."""


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _read_json(request, *, opener, timeout):
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PriceProviderError(f"HTTP {exc.code}: {detail}") from exc
    except (OSError, URLError) as exc:
        raise PriceProviderError(str(exc)) from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PriceProviderError("provider returned invalid JSON") from exc


def _alpaca_symbol(symbol):
    # Alpaca represents share classes with a dot while Yahoo commonly uses a
    # hyphen (for example BRK.B versus BRK-B).
    return str(symbol).strip().upper().replace("-", ".")


def download_alpaca_snapshots(
    symbols,
    *,
    now=None,
    api_key_id=None,
    api_secret_key=None,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Download current IEX snapshots in small multi-symbol REST batches."""
    del now  # The provider timestamps each returned trade/bar.
    api_key_id = api_key_id or os.environ.get("ALPACA_API_KEY_ID", "")
    api_secret_key = api_secret_key or os.environ.get(
        "ALPACA_API_SECRET_KEY", ""
    )
    if not api_key_id or not api_secret_key:
        raise PriceProviderError("Alpaca credentials are not configured")

    original_by_provider = {
        _alpaca_symbol(symbol): str(symbol).strip().upper() for symbol in symbols
    }
    results = {}
    for batch in _chunks(sorted(original_by_provider), ALPACA_BATCH_SIZE):
        query = urlencode({"symbols": ",".join(batch), "feed": "iex"})
        request = Request(
            f"{ALPACA_SNAPSHOT_URL}?{query}",
            headers={
                "APCA-API-KEY-ID": api_key_id,
                "APCA-API-SECRET-KEY": api_secret_key,
                "Accept": "application/json",
                "User-Agent": "StockScanner-GitHub-Actions/1.0",
            },
        )
        payload = _read_json(request, opener=opener, timeout=timeout)
        if not isinstance(payload, dict):
            raise PriceProviderError("Alpaca returned an invalid snapshot object")

        for provider_symbol, snapshot in payload.items():
            original = original_by_provider.get(str(provider_symbol).upper())
            if original is None or not isinstance(snapshot, dict):
                continue
            latest_trade = snapshot.get("latestTrade") or {}
            minute_bar = snapshot.get("minuteBar") or {}
            daily_bar = snapshot.get("dailyBar") or {}
            previous_daily_bar = snapshot.get("prevDailyBar") or {}
            price = latest_trade.get("p")
            timestamp = latest_trade.get("t")
            if price is None:
                price = minute_bar.get("c")
                timestamp = minute_bar.get("t")
            if price is None:
                price = daily_bar.get("c")
                timestamp = daily_bar.get("t")
            results[original] = {
                "price": price,
                "daily_close": previous_daily_bar.get("c"),
                "timestamp": timestamp,
            }
    return results


def download_twelve_data_snapshots(
    symbols,
    *,
    now=None,
    api_key=None,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Use at most eight Twelve Data free credits as a final fallback."""
    api_key = api_key or os.environ.get("TWELVE_DATA_API_KEY", "")
    if not api_key:
        raise PriceProviderError("Twelve Data credentials are not configured")

    requested = [
        str(symbol).strip().upper()
        for symbol in symbols[:TWELVE_DATA_FREE_SYMBOLS_PER_RUN]
    ]
    if not requested:
        return {}
    query = urlencode({"symbol": ",".join(requested), "apikey": api_key})
    request = Request(
        f"{TWELVE_DATA_PRICE_URL}?{query}",
        headers={"User-Agent": "StockScanner-GitHub-Actions/1.0"},
    )
    payload = _read_json(request, opener=opener, timeout=timeout)
    timestamp = now.isoformat() if now is not None else None

    if len(requested) == 1 and isinstance(payload, dict) and "price" in payload:
        return {requested[0]: {"price": payload.get("price"), "timestamp": timestamp}}
    if not isinstance(payload, dict):
        raise PriceProviderError("Twelve Data returned an invalid price object")

    results = {}
    for symbol in requested:
        quote = payload.get(symbol)
        if isinstance(quote, dict):
            results[symbol] = {
                "price": quote.get("price"),
                "timestamp": timestamp,
            }
    return results

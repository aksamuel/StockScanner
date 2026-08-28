"""Load the distinct user-held ticker symbols needed by the hourly price job."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 30
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")


class PortfolioSymbolError(RuntimeError):
    """Raised when portfolio symbols cannot be loaded safely from Supabase."""


def _headers(secret_key, *, start, page_size):
    headers = {
        "apikey": secret_key,
        "Range-Unit": "items",
        "Range": f"{start}-{start + page_size - 1}",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    # Legacy service_role JWTs require Authorization. Supabase's newer
    # sb_secret_* keys are intentionally sent only through the apikey header.
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    return headers


def normalize_portfolio_symbols(symbols):
    """Return sorted, unique ticker symbols and reject unsafe values."""
    normalized = {
        str(symbol or "").strip().upper().replace(" ", "-")
        for symbol in symbols
    }
    normalized.discard("")
    invalid = sorted(symbol for symbol in normalized if not TICKER_PATTERN.fullmatch(symbol))
    if invalid:
        raise PortfolioSymbolError(
            f"Portfolio contains invalid ticker symbols: {', '.join(invalid[:5])}"
        )
    return sorted(normalized)


def _request_json(request, *, opener, timeout):
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PortfolioSymbolError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError) as exc:
        raise PortfolioSymbolError(f"Unable to reach Supabase: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise PortfolioSymbolError("Supabase returned invalid JSON") from exc


def load_portfolio_symbols(
    *,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    page_size=1000,
):
    """Load only distinct symbols across all user-owned portfolio rows."""
    if not supabase_url:
        raise PortfolioSymbolError("SUPABASE_URL is required")
    if not secret_key:
        raise PortfolioSymbolError("SUPABASE_SECRET_KEY is required")
    if page_size < 1:
        raise PortfolioSymbolError("page_size must be positive")

    query = urlencode({"select": "symbol", "order": "symbol.asc"})
    endpoint = (
        f"{supabase_url.rstrip('/')}/rest/v1/user_portfolio_holdings?{query}"
    )
    rows = []
    start = 0
    while True:
        request = Request(
            endpoint,
            headers=_headers(secret_key, start=start, page_size=page_size),
            method="GET",
        )
        batch = _request_json(request, opener=opener, timeout=timeout)
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise PortfolioSymbolError("Supabase returned invalid portfolio rows")
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size

    return normalize_portfolio_symbols(row.get("symbol") for row in rows)

"""Persist owner-gated portfolio technical-signal attempts in Supabase."""

from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 30


class TechnicalSignalStoreError(RuntimeError):
    """Raised when portfolio technical-signal attempts cannot be recorded."""


def _optional_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def technical_signal_attempt(symbol, result=None, reason="analysis_failure"):
    """Build one safe success or failure payload for the storage RPC."""
    normalized_symbol = str(symbol or "").strip().upper()
    if result is None:
        return {
            "symbol": normalized_symbol,
            "success": False,
            "failure_reason": str(reason or "analysis_failure")[:120],
        }
    return {
        "symbol": normalized_symbol,
        "success": True,
        "score": _optional_number(result.get("Score")),
        "recommendation": str(result.get("Recommendation", "")).strip(),
        "scanner_price": _optional_number(result.get("Current Price")),
        "technical_target": _optional_number(result.get("Target 1")),
        "resistance_target": _optional_number(result.get("Resistance Low")),
        "analyst_target_upside": _optional_number(result.get("Target Upside")),
    }


def publish_portfolio_technical_signals(
    attempts,
    *,
    market_date,
    supabase_url,
    secret_key,
    opener=urlopen,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Record all held-symbol attempts without exposing holdings in reports."""
    if not attempts:
        return 0
    if not supabase_url:
        raise TechnicalSignalStoreError("SUPABASE_URL is required")
    if not secret_key:
        raise TechnicalSignalStoreError("SUPABASE_SECRET_KEY is required")

    endpoint = (
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/"
        "record_portfolio_technical_signal_attempts"
    )
    headers = {
        "apikey": secret_key,
        "Content-Type": "application/json",
        "User-Agent": "StockScanner-GitHub-Actions/1.0",
    }
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    payload = json.dumps(
        {"p_market_date": str(market_date), "p_attempts": attempts}
    ).encode("utf-8")
    try:
        with opener(
            Request(endpoint, data=payload, headers=headers, method="POST"),
            timeout=timeout,
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TechnicalSignalStoreError(
            f"Supabase returned HTTP {exc.code}: {detail}"
        ) from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise TechnicalSignalStoreError(
            f"Unable to store portfolio technical signals: {exc}"
        ) from exc
    if not isinstance(result, int):
        raise TechnicalSignalStoreError("Supabase returned an invalid attempt count")
    return result

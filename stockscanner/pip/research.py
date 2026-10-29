from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Callable

from ..analyst_data import get_analyst_data
from ..market_data import download_data


PRICE_SOURCES = {"Yahoo", "Alpaca", "Twelve Data"}


class ResearchDataUnavailable(RuntimeError):
    """Raised when none of the configured market-data sources provides facts."""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_value(value: Any) -> date | None:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _history_points(frame: Any) -> list[tuple[date, float]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    columns = getattr(frame, "columns", ())
    price_column = "Adj Close" if "Adj Close" in columns else "Close"
    if price_column not in columns:
        return []
    points = []
    for timestamp, row in frame.iterrows():
        day = _date_value(timestamp)
        price = _number(row.get(price_column))
        if day is not None and price is not None and price > 0:
            points.append((day, price))
    return sorted(points)


def _return_percent(points: list[tuple[date, float]]) -> float | None:
    if len(points) < 2:
        return None
    first_price = points[0][1]
    last_price = points[-1][1]
    return round((last_price / first_price - 1) * 100, 2)


def _snapshot_price(snapshot: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    if not snapshot:
        return {"price": None, "source": None, "as_of": None, "stale": False}
    prices = snapshot.get("prices")
    price = _number(prices.get(symbol)) if isinstance(prices, dict) else None
    if price is None or price <= 0:
        return {"price": None, "source": None, "as_of": None, "stale": False}

    timestamps = snapshot.get("price_timestamps")
    provider_by_symbol = snapshot.get("provider_by_symbol")
    stale_symbols = snapshot.get("stale_symbols")
    source = (
        provider_by_symbol.get(symbol)
        if isinstance(provider_by_symbol, dict)
        else None
    )
    return {
        "price": round(price, 4),
        "source": source if source in PRICE_SOURCES else "shared market price snapshot",
        "as_of": (
            timestamps.get(symbol)
            if isinstance(timestamps, dict)
            else None
        ) or snapshot.get("generated_at"),
        "stale": isinstance(stale_symbols, list) and symbol in stale_symbols,
    }


def collect_research_data(
    symbol: str,
    *,
    market_snapshot: dict[str, Any] | None = None,
    history_loader: Callable[..., Any] = download_data,
    analyst_loader: Callable[..., dict[str, Any]] = get_analyst_data,
    today: date | None = None,
) -> dict[str, Any]:
    """Collect Yahoo research facts and the shared Yahoo/Alpaca/Twelve Data quote.

    Only public ticker symbols are passed to those data providers. This function
    does not call Alpaca or Twelve Data directly, convert raw returns into 0..100
    PIP scores, or treat per-share dividend events as portfolio cash income.
    """
    symbol = symbol.strip().upper()
    current_day = today or datetime.now(timezone.utc).date()
    warnings: list[str] = []

    try:
        history = history_loader(symbol)
    except Exception:
        history = None
        warnings.append("Yahoo historical prices and dividend history are unavailable.")
    try:
        benchmark_history = history_loader("SPY")
    except Exception:
        benchmark_history = None
        warnings.append("Yahoo SPY benchmark history is unavailable.")

    points = _history_points(history)
    benchmark_points = _history_points(benchmark_history)
    quote = _snapshot_price(market_snapshot, symbol)
    history_price = points[-1][1] if points else None
    if quote["price"] is None and history_price is not None:
        quote = {
            "price": round(history_price, 4),
            "source": "Yahoo Finance historical close",
            "as_of": points[-1][0].isoformat(),
            "stale": False,
        }
    if quote["price"] is None:
        warnings.append("No market price is available from the shared snapshot or Yahoo history.")

    stock_return = _return_percent(points)
    benchmark_return = _return_percent(benchmark_points)
    if stock_return is None:
        warnings.append("Yahoo history is insufficient to calculate the holding's return.")
    if benchmark_return is None:
        warnings.append("Yahoo history is insufficient to calculate SPY return.")
    stock_by_date = dict(points)
    benchmark_by_date = dict(benchmark_points)
    common_dates = sorted(stock_by_date.keys() & benchmark_by_date.keys())
    aligned_stock_return = _return_percent(
        [(day, stock_by_date[day]) for day in common_dates]
    )
    aligned_benchmark_return = _return_percent(
        [(day, benchmark_by_date[day]) for day in common_dates]
    )
    relative_performance = (
        round(aligned_stock_return - aligned_benchmark_return, 2)
        if aligned_stock_return is not None and aligned_benchmark_return is not None
        else None
    )
    if relative_performance is None:
        warnings.append("Yahoo history has no comparable common trading-date window for relative performance.")

    cutoff = current_day - timedelta(days=365)
    dividends = []
    has_dividend_column = (
        history is not None
        and not getattr(history, "empty", True)
        and "Dividends" in getattr(history, "columns", ())
    )
    if has_dividend_column:
        for timestamp, row in history.iterrows():
            event_date = _date_value(timestamp)
            amount = _number(row.get("Dividends"))
            if (
                event_date is not None
                and cutoff < event_date <= current_day
                and amount is not None
                and amount > 0
            ):
                dividends.append({
                    "ex_date": event_date.isoformat(),
                    "amount_per_share": round(amount, 6),
                })
    dividend_history_complete = bool(
        has_dividend_column
        and points
        and points[0][0] <= cutoff + timedelta(days=7)
        and points[-1][0] >= current_day - timedelta(days=7)
    )

    analyst: dict[str, Any] = {
        "rating": None,
        "target_price": None,
        "target_upside_percent": None,
    }
    try:
        result = analyst_loader(
            symbol,
            quote["price"],
            include_target_price=True,
        )
        rating = result.get("Analyst Rating")
        analyst = {
            "rating": rating if rating and rating != "Unavailable" else None,
            "target_price": _number(result.get("Target Price")),
            "target_upside_percent": _number(result.get("Target Upside")),
        }
    except Exception:
        warnings.append("Yahoo analyst consensus and target data are unavailable.")

    if not dividend_history_complete:
        warnings.append("Yahoo history does not cover the full trailing 365 days of dividends.")
    warnings.extend([
        "Earnings and revenue growth are not exposed by the current provider adapters.",
        "Analyst estimate revision history is not exposed by the current provider adapters.",
        "Raw return percentages are shown as evidence; no 0–100 score conversion is assumed.",
    ])
    has_analyst_data = any(value is not None for value in analyst.values())
    if (
        quote["price"] is None
        and stock_return is None
        and benchmark_return is None
        and not dividends
        and not has_analyst_data
    ):
        raise ResearchDataUnavailable(
            "No market research data was returned by Yahoo or the shared price snapshot."
        )

    history_start = points[0][0] if points else None
    history_end = points[-1][0] if points else None
    return {
        "symbol": symbol,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "price": quote,
        "returns": {
            "start_date": history_start.isoformat() if history_start else None,
            "end_date": history_end.isoformat() if history_end else None,
            "history_days": (
                (history_end - history_start).days
                if history_start and history_end
                else None
            ),
            "price_return_percent": stock_return,
            "spy_return_percent": benchmark_return,
            "relative_performance_percentage_points": relative_performance,
            "basis": "adjusted_close" if history is not None and "Adj Close" in getattr(history, "columns", ()) else "close",
        },
        "dividends": {
            "trailing_365_days_per_share": (
                round(sum(item["amount_per_share"] for item in dividends), 6)
                if dividend_history_complete
                else None
            ),
            "history_complete": dividend_history_complete,
            "events": dividends,
            "note": "Yahoo dividend amounts are per share, not portfolio cash income.",
        },
        "analyst": analyst,
        "unavailable_metrics": {
            "earnings_growth_percent": "Not exposed by the current provider adapters.",
            "revenue_growth_percent": "Not exposed by the current provider adapters.",
            "analyst_revisions_score": "Historical analyst estimate revisions are not exposed by the current provider adapters.",
            "normalized_return_scores": "No approved 0–100 score mapping exists for raw return percentages.",
        },
        "warnings": warnings,
    }

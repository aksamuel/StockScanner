"""Load analyst consensus and price-target data from Yahoo Finance."""

import json
import math
import os
import time

import yfinance as yf


RATING_PRIORITY = {
    "strong_buy": 5,
    "buy": 4,
    "hold": 3,
    "underperform": 2,
    "sell": 1,
}

RATING_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "underperform": "Underperform",
    "sell": "Sell",
}


def analyst_rating_priority(rating):
    """Return a sortable priority for an analyst consensus label."""
    normalized = str(rating or "").strip().casefold().replace(" ", "_")
    return RATING_PRIORITY.get(normalized, 0)


def _cache_path(symbol, cache_directory):
    safe_symbol = str(symbol).replace("/", "_").replace("\\", "_").replace(" ", "_")
    return os.path.join(cache_directory, f"{safe_symbol}.json")


def _read_cache(path, cache_hours):
    if not os.path.exists(path):
        return None
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    if age_hours > cache_hours:
        return None
    try:
        with open(path, encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as cache_file:
        json.dump(data, cache_file)
    os.replace(temporary_path, path)


def _public_analyst_data(cached, current_price, *, include_target_price):
    rating = cached.get("Analyst Rating", "Unavailable")
    target_price = cached.get("Target Mean Price")
    try:
        target_price = float(target_price) if target_price is not None else None
    except (TypeError, ValueError):
        target_price = None
    if target_price is not None and not math.isfinite(target_price):
        target_price = None

    target_upside = cached.get("Target Upside")
    try:
        price = float(current_price) if current_price is not None else None
        if target_price is not None and price is not None and price > 0:
            target_upside = ((target_price / price) - 1) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        target_upside = None
    try:
        target_upside = (
            round(float(target_upside), 2) if target_upside is not None else None
        )
    except (TypeError, ValueError):
        target_upside = None
    if target_upside is not None and not math.isfinite(target_upside):
        target_upside = None

    result = {"Analyst Rating": rating, "Target Upside": target_upside}
    if include_target_price:
        result["Target Price"] = target_price
    return result


def get_analyst_data(
    symbol,
    current_price,
    cache_directory=None,
    cache_hours=24,
    *,
    include_target_price=False,
):
    """Return analyst consensus and target upside without affecting technical scoring.

    Target mean price, rather than a price-dependent upside, is cached so each
    caller can calculate upside against its own current-price snapshot.
    """
    if cache_directory is None:
        cache_directory = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "data", "analyst")
        )
    path = _cache_path(symbol, cache_directory)
    cached = _read_cache(path, cache_hours)
    if cached is not None and "Target Mean Price" in cached:
        return _public_analyst_data(
            cached,
            current_price,
            include_target_price=include_target_price,
        )

    info = yf.Ticker(symbol).get_info() or {}
    recommendation_key = str(info.get("recommendationKey") or "").strip().casefold()
    rating = RATING_LABELS.get(recommendation_key, "Unavailable")

    target_mean_price = info.get("targetMeanPrice")
    try:
        target_mean_price = (
            float(target_mean_price) if target_mean_price is not None else None
        )
    except (TypeError, ValueError, ZeroDivisionError):
        target_mean_price = None
    if target_mean_price is not None and (
        not math.isfinite(target_mean_price) or target_mean_price <= 0
    ):
        target_mean_price = None

    result = {
        "Analyst Rating": rating,
        "Target Mean Price": target_mean_price,
    }
    try:
        _write_cache(path, result)
    except OSError:
        pass
    return _public_analyst_data(
        result,
        current_price,
        include_target_price=include_target_price,
    )


def _fraction_to_percent(value):
    if isinstance(value, bool):
        return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric_value):
        return None
    return round(numeric_value * 100, 2)


def _revision_periods(frame):
    if frame is None or getattr(frame, "empty", True):
        return {}
    columns = {
        str(column).casefold().replace("_", ""): column
        for column in getattr(frame, "columns", ())
    }
    count_columns = {
        "up_last_7_days": "uplast7days",
        "up_last_30_days": "uplast30days",
        "down_last_7_days": "downlast7days",
        "down_last_30_days": "downlast30days",
    }
    periods = {}
    for label, row in frame.iterrows():
        period = str(label).strip()
        if period not in {"0q", "+1q", "0y", "+1y"}:
            continue
        counts = {}
        for name, normalized_column in count_columns.items():
            column = columns.get(normalized_column)
            value = row.get(column) if column is not None else None
            if isinstance(value, bool):
                counts[name] = None
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                counts[name] = None
                continue
            counts[name] = (
                int(numeric_value)
                if math.isfinite(numeric_value)
                and numeric_value >= 0
                and numeric_value.is_integer()
                else None
            )
        if any(value is not None for value in counts.values()):
            periods[period] = counts
    return periods


def get_pip_research_metrics(symbol, cache_directory=None, cache_hours=24):
    """Return Yahoo growth percentages and raw EPS revision counts for PIP."""
    if cache_directory is None:
        cache_directory = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "data", "analyst")
        )
    cache_path = os.path.splitext(_cache_path(symbol, cache_directory))[0] + ".pip.json"
    cached = _read_cache(cache_path, cache_hours)
    if isinstance(cached, dict) and cached.get("schema_version") == 1:
        return {key: value for key, value in cached.items() if key != "schema_version"}

    ticker = yf.Ticker(str(symbol).strip().upper())
    warnings = []
    try:
        info = ticker.get_info() or {}
    except Exception:
        info = {}
        warnings.append("Yahoo company growth fields are unavailable.")
    earnings_growth = _fraction_to_percent(info.get("earningsGrowth"))
    revenue_growth = _fraction_to_percent(info.get("revenueGrowth"))
    if earnings_growth is None:
        warnings.append("Yahoo did not provide earnings growth for this symbol.")
    if revenue_growth is None:
        warnings.append("Yahoo did not provide revenue growth for this symbol.")

    try:
        revision_periods = _revision_periods(ticker.get_eps_revisions())
    except Exception:
        revision_periods = {}
        warnings.append("Yahoo EPS revision counts are unavailable.")
    if not revision_periods and not any("EPS revision" in warning for warning in warnings):
        warnings.append("Yahoo did not provide EPS revision counts for this symbol.")

    result = {
        "source": "Yahoo Finance",
        "earnings_growth_percent": earnings_growth,
        "revenue_growth_percent": revenue_growth,
        "revision_periods": revision_periods,
        "warnings": warnings,
    }
    try:
        _write_cache(cache_path, {"schema_version": 1, **result})
    except OSError:
        pass
    return result

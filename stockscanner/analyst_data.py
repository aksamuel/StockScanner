"""Load analyst consensus and price-target data from Yahoo Finance."""

import json
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


def get_analyst_data(symbol, current_price, cache_directory=None, cache_hours=24):
    """Return analyst rating and target upside without affecting technical scoring."""
    if cache_directory is None:
        cache_directory = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "data", "analyst")
        )
    path = _cache_path(symbol, cache_directory)
    cached = _read_cache(path, cache_hours)
    if cached is not None:
        return cached

    info = yf.Ticker(symbol).get_info() or {}
    recommendation_key = str(info.get("recommendationKey") or "").strip().casefold()
    rating = RATING_LABELS.get(recommendation_key, "Unavailable")

    target_mean_price = info.get("targetMeanPrice")
    try:
        target_upside = (
            ((float(target_mean_price) - float(current_price)) / float(current_price))
            * 100
        )
        target_upside = round(target_upside, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        target_upside = None

    result = {
        "Analyst Rating": rating,
        "Target Upside": target_upside,
    }
    try:
        _write_cache(path, result)
    except OSError:
        pass
    return result

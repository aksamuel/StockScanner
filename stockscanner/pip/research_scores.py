"""Research-based 0-100 scores for the PIP module runner.

Every score uses one mapping, ``score = clamp(50 + 50 * value / limit, 0, 100)``. A value of zero is neutral (50),
a value of ``+limit`` or more is 100 and a value of ``-limit`` or less is 0. When an input is missing or the history
is too thin to measure it, the score is ``None`` with a plain-text reason. It is never filled in with a neutral 50.

Every limit and minimum amount of history lives in ``RESEARCH_SCORE_RULES``, so a change is one reviewed edit, and
``RESEARCH_SCORES_VERSION`` tells a reader which rules produced a result. These functions only read the numbers they
are given: they never fetch data.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import math
import numbers
from typing import Any

RESEARCH_SCORES_VERSION = "research-1"

RESEARCH_SCORE_RULES: dict[str, Any] = {
    "version": RESEARCH_SCORES_VERSION,
    "tsr": {"limit_percent": 40.0, "min_history_days": 330},
    "relative_performance": {"limit_points": 20.0, "min_history_days": 330},
    "revisions": {"min_revisions": 3, "periods": ("0q", "+1q", "0y", "+1y")},
    "technical_health": {
        "min_closes": 200,
        "long_average": {"days": 200, "limit_percent": 15.0},
        "short_average": {"days": 50, "limit_percent": 10.0},
        "high": {"window_days": 365, "limit_percent": 40.0},
    },
}


def _finite(value: Any) -> float | None:
    """The value as a float if it is a real, finite number (not a bool); otherwise None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _whole_number(value: Any) -> int | None:
    """A count or a number of days: a finite, non-negative whole number such as 3 or 3.0."""
    number = _finite(value)
    if number is None or number < 0 or number != int(number):
        return None
    return int(number)


def _round(value: float | None, digits: int) -> float | None:
    """Round for display. Adding 0.0 turns a negative zero into a plain zero."""
    return None if value is None else round(value, digits) + 0.0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _result(score: float | None, raw: dict[str, Any], reason: str | None) -> dict[str, Any]:
    return {"score": _round(score, 1), "raw": raw, "reason": reason}


def map_value_to_score(value: float, limit: float) -> float:
    """Map a value onto 0-100 around a neutral 50, reaching 100 at ``+limit`` and 0 at ``-limit``."""
    number = _finite(value)
    bound = _finite(limit)
    if number is None:
        raise ValueError("value must be a finite number")
    if bound is None or bound <= 0:
        raise ValueError("limit must be a positive, finite number")
    return min(100.0, max(0.0, 50.0 + 50.0 * number / bound))


def score_tsr(return_percent: Any, history_days: Any) -> dict[str, Any]:
    """Score the stock's 1-year total return, using prices already adjusted for dividends and splits."""
    rules = RESEARCH_SCORE_RULES["tsr"]
    change = _finite(return_percent)
    days = _whole_number(history_days)
    raw = {"return_percent": _round(change, 2), "history_days": days}
    if change is None or days is None:
        return _result(None, raw, "Yahoo did not return enough price history to measure a 1-year total return.")
    if days < rules["min_history_days"]:
        return _result(
            None,
            raw,
            f"Yahoo history covers {_plural(days, 'day')}; at least {rules['min_history_days']} are needed "
            "to score a 1-year total return.",
        )
    return _result(map_value_to_score(change, rules["limit_percent"]), raw, None)


def score_relative_performance(gap_points: Any, history_days: Any) -> dict[str, Any]:
    """Score the stock's return minus SPY's over the dates both have prices for, in percentage points."""
    rules = RESEARCH_SCORE_RULES["relative_performance"]
    gap = _finite(gap_points)
    days = _whole_number(history_days)
    raw = {"gap_points": _round(gap, 2), "history_days": days}
    if gap is None or days is None:
        return _result(
            None,
            raw,
            "Yahoo did not return enough overlapping price history for this symbol and SPY to compare their returns.",
        )
    if days < rules["min_history_days"]:
        return _result(
            None,
            raw,
            f"This symbol and SPY share {_plural(days, 'day')} of price history; at least "
            f"{rules['min_history_days']} are needed to score performance against SPY.",
        )
    return _result(map_value_to_score(gap, rules["limit_points"]), raw, None)


def score_revisions(periods: Any) -> dict[str, Any]:
    """Score the breadth of analyst EPS revisions: (up - down) / (up + down) over the last 30 days.

    A period counts only if both of its 30-day counts are valid, so a half-reported period never skews the total.
    """
    rules = RESEARCH_SCORE_RULES["revisions"]
    up = down = 0
    counted: list[str] = []
    if isinstance(periods, Mapping):
        for name in rules["periods"]:
            entry = periods.get(name)
            if not isinstance(entry, Mapping):
                continue
            raised = _whole_number(entry.get("up_last_30_days"))
            lowered = _whole_number(entry.get("down_last_30_days"))
            if raised is None or lowered is None:
                continue
            up += raised
            down += lowered
            counted.append(name)
    raw: dict[str, Any] = {"up": up, "down": down, "breadth": None, "periods_counted": counted}
    if not counted:
        return _result(None, raw, "Yahoo did not provide 30-day EPS revision counts for this symbol.")
    total = up + down
    if total < rules["min_revisions"]:
        return _result(
            None,
            raw,
            f"Yahoo shows {_plural(total, 'EPS revision')} in the last 30 days; at least "
            f"{rules['min_revisions']} are needed to score analyst revisions.",
        )
    breadth = (up - down) / total
    raw["breadth"] = _round(breadth, 4)
    return _result(map_value_to_score(breadth, 1.0), raw, None)


def _clean_points(points: Any) -> list[tuple[date, float]]:
    """Dated closes sorted oldest first, ignoring anything that is not a date with a positive, finite close."""
    try:
        items = iter(points)
    except TypeError:
        return []
    cleaned: list[tuple[date, float]] = []
    for item in items:
        try:
            day, close = item
        except (TypeError, ValueError):
            continue
        if isinstance(day, datetime):
            day = day.date()
        price = _finite(close)
        if isinstance(day, date) and price is not None and price > 0:
            cleaned.append((day, price))
    cleaned.sort(key=lambda point: point[0])
    return cleaned


def score_technical_health(points: Any) -> dict[str, Any]:
    """Score trend strength as the equal-weight average of three parts, each on the same 0-100 mapping.

    The parts are the last close against its 200-day and 50-day simple averages, and how far it sits below its
    52-week high. Averages are taken over the last 200 and 50 closes, and the high over the last 365 calendar days.
    """
    rules = RESEARCH_SCORE_RULES["technical_health"]
    long_rule, short_rule, high_rule = rules["long_average"], rules["short_average"], rules["high"]
    closes = _clean_points(points)
    if len(closes) < rules["min_closes"]:
        return _result(
            None,
            {"closes": len(closes)},
            f"Yahoo returned {_plural(len(closes), 'daily close')}; at least {rules['min_closes']} are needed "
            "to score technical health.",
        )

    last_day, last_close = closes[-1]
    long_window = [price for _, price in closes[-long_rule["days"]:]]
    short_window = [price for _, price in closes[-short_rule["days"]:]]
    high_start = last_day - timedelta(days=high_rule["window_days"])
    high = max(price for day, price in closes if day >= high_start)

    above_long = (last_close / (sum(long_window) / len(long_window)) - 1) * 100
    above_short = (last_close / (sum(short_window) / len(short_window)) - 1) * 100
    below_high = (1 - last_close / high) * 100
    parts = {
        "long_average": map_value_to_score(above_long, long_rule["limit_percent"]),
        "short_average": map_value_to_score(above_short, short_rule["limit_percent"]),
        "high": min(100.0, max(0.0, 100.0 * (1 - below_high / high_rule["limit_percent"]))),
    }
    raw = {
        "closes": len(closes),
        "long_average_days": long_rule["days"],
        "close_vs_long_average_percent": _round(above_long, 2),
        "short_average_days": short_rule["days"],
        "close_vs_short_average_percent": _round(above_short, 2),
        "high_window_days": high_rule["window_days"],
        "below_high_percent": _round(below_high, 2),
        "parts": {name: _round(value, 1) for name, value in parts.items()},
    }
    return _result(sum(parts.values()) / len(parts), raw, None)


def build_research_scores(
    *,
    return_percent: Any,
    history_days: Any,
    relative_gap_points: Any,
    relative_history_days: Any,
    revision_periods: Any,
    points: Any,
) -> dict[str, Any]:
    """All four research scores from one set of Yahoo facts, each judged on its own inputs."""
    return {
        "version": RESEARCH_SCORES_VERSION,
        "tsr": score_tsr(return_percent, history_days),
        "relative_performance": score_relative_performance(relative_gap_points, relative_history_days),
        "revisions": score_revisions(revision_periods),
        "technical_health": score_technical_health(points),
    }

from __future__ import annotations

from typing import Dict, Iterable, List


def normalize_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp a value into a 0..100 style score range."""

    if maximum == minimum:
        return 0.0
    return max(minimum, min(maximum, value))


def score_weighted_average(items: Iterable[tuple[float, float]]) -> float:
    """Return a weighted average where each item is (weight, value)."""

    total_weight = 0.0
    total_value = 0.0
    for weight, value in items:
        total_weight += weight
        total_value += weight * value
    if total_weight == 0:
        return 0.0
    return total_value / total_weight


def calculate_cps(
    tsr: float,
    relative_performance: float,
    dividend_growth: float,
    earnings_growth: float,
    analyst_revisions: float,
) -> float:
    """Capital Productivity Score (CPS) formula.

    Formula:
      40% TSR
      20% Relative Performance vs SPY
      15% Dividend Growth
      15% Earnings Growth
      10% Analyst Revisions
    """

    return score_weighted_average(
        [
            (0.40, normalize_score(tsr)),
            (0.20, normalize_score(relative_performance)),
            (0.15, normalize_score(dividend_growth)),
            (0.15, normalize_score(earnings_growth)),
            (0.10, normalize_score(analyst_revisions)),
        ]
    )


def calculate_sell_score(
    tsr: float,
    relative_performance: float,
    revisions: float,
    dividend_quality: float,
    technical_health: float,
    earnings_growth: float,
    opportunity_cost: float,
) -> float:
    """Sell Confidence Score formula.

    Formula:
      20% TSR
      20% Relative Performance
      20% Revisions
      15% Dividend Quality
      15% Technical Health
      10% Earnings Growth
      15% Opportunity Cost
    """

    return score_weighted_average(
        [
            (0.20, normalize_score(tsr)),
            (0.20, normalize_score(relative_performance)),
            (0.20, normalize_score(revisions)),
            (0.15, normalize_score(dividend_quality)),
            (0.15, normalize_score(technical_health)),
            (0.10, normalize_score(earnings_growth)),
            (0.15, normalize_score(opportunity_cost)),
        ]
    )


def build_score_breakdown(data: Dict[str, float]) -> Dict[str, float]:
    """Return the canonical score components used by the PIP engine."""

    return {
        "tsr": float(data.get("tsr", 0.0)),
        "relative_performance": float(data.get("relative_performance", 0.0)),
        "dividend_growth": float(data.get("dividend_growth", 0.0)),
        "earnings_growth": float(data.get("earnings_growth", 0.0)),
        "analyst_revisions": float(data.get("analyst_revisions", 0.0)),
        "dividend_quality": float(data.get("dividend_quality", 0.0)),
        "technical_health": float(data.get("technical_health", 0.0)),
        "opportunity_cost": float(data.get("opportunity_cost", 0.0)),
        "revisions": float(data.get("revisions", 0.0)),
    }

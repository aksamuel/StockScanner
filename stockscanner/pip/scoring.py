from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


CPS_WEIGHTS = {
    "tsr": 40.0,
    "relative_performance": 20.0,
    "dividend_growth": 15.0,
    "earnings_growth": 15.0,
    "analyst_revisions": 10.0,
}

SELL_SCORE_WEIGHTS = {
    "tsr": 20.0,
    "relative_performance": 20.0,
    "revisions": 20.0,
    "dividend_quality": 15.0,
    "technical_health": 15.0,
    "earnings_growth": 10.0,
    "opportunity_cost": 15.0,
}


@dataclass(frozen=True)
class ScoringResult:
    score: float | None
    confidence: float
    reasons: tuple[str, ...]
    component_scores: Mapping[str, float]


def normalize_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp a finite component score into the 0..100 range."""
    if maximum <= minimum:
        raise ValueError("maximum must be greater than minimum")
    if not isfinite(float(value)):
        raise ValueError("score must be finite")
    return max(minimum, min(maximum, float(value)))


def calculate_weighted_score(
    components: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> ScoringResult:
    """Normalize available 0..100 component scores and report missing-data confidence."""
    if not weights or any(not isfinite(float(weight)) or float(weight) <= 0 for weight in weights.values()):
        raise ValueError("weights must be finite positive values")

    total_weight = sum(float(weight) for weight in weights.values())
    available: dict[str, float] = {}
    reasons: list[str] = []
    available_weight = 0.0

    for name, weight in weights.items():
        value = components.get(name)
        if value is None:
            reasons.append(f"{name.replace('_', ' ').title()} data is missing.")
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            reasons.append(f"{name.replace('_', ' ').title()} data is invalid.")
            continue
        if not isfinite(numeric_value):
            reasons.append(f"{name.replace('_', ' ').title()} data is invalid.")
            continue
        available[name] = normalize_score(numeric_value)
        available_weight += float(weight)

    if not available:
        return ScoringResult(None, 0.0, tuple(reasons or ("No score inputs are available.",)), {})

    weighted_total = sum(float(weights[name]) * score for name, score in available.items())
    return ScoringResult(
        score=weighted_total / available_weight,
        confidence=available_weight / total_weight,
        reasons=tuple(reasons),
        component_scores=available,
    )


def score_weighted_average(items) -> float:
    """Return a normalized weighted average from (weight, score) pairs."""
    pairs = [(float(weight), normalize_score(value)) for weight, value in items]
    if not pairs:
        return 0.0
    if any(not isfinite(weight) or weight <= 0 for weight, _ in pairs):
        raise ValueError("weights must be finite positive values")
    total_weight = sum(weight for weight, _ in pairs)
    return sum(weight * value for weight, value in pairs) / total_weight


def calculate_cps_result(
    components: Mapping[str, float | None],
    weights: Mapping[str, float] | None = None,
) -> ScoringResult:
    return calculate_weighted_score(components, CPS_WEIGHTS if weights is None else weights)


def calculate_sell_score_result(
    components: Mapping[str, float | None],
    weights: Mapping[str, float] | None = None,
) -> ScoringResult:
    return calculate_weighted_score(components, SELL_SCORE_WEIGHTS if weights is None else weights)


def calculate_cps(
    tsr: float | None,
    relative_performance: float | None,
    dividend_growth: float | None,
    earnings_growth: float | None,
    analyst_revisions: float | None,
    weights: Mapping[str, float] | None = None,
) -> float | None:
    result = calculate_cps_result(
        {
            "tsr": tsr,
            "relative_performance": relative_performance,
            "dividend_growth": dividend_growth,
            "earnings_growth": earnings_growth,
            "analyst_revisions": analyst_revisions,
        },
        weights,
    )
    return result.score


def calculate_sell_score(
    tsr: float | None,
    relative_performance: float | None,
    revisions: float | None,
    dividend_quality: float | None,
    technical_health: float | None,
    earnings_growth: float | None,
    opportunity_cost: float | None,
    weights: Mapping[str, float] | None = None,
) -> float | None:
    result = calculate_sell_score_result(
        {
            "tsr": tsr,
            "relative_performance": relative_performance,
            "revisions": revisions,
            "dividend_quality": dividend_quality,
            "technical_health": technical_health,
            "earnings_growth": earnings_growth,
            "opportunity_cost": opportunity_cost,
        },
        weights,
    )
    return result.score


def build_score_breakdown(data: Mapping[str, float | None]) -> dict[str, float | None]:
    """Return canonical components without disguising absent data as a zero score."""
    keys = (
        "tsr",
        "relative_performance",
        "dividend_growth",
        "earnings_growth",
        "analyst_revisions",
        "dividend_quality",
        "technical_health",
        "opportunity_cost",
        "revisions",
    )
    return {key: data.get(key) for key in keys}

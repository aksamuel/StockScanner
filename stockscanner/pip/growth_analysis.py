from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class GrowthAssessment:
    score: float | None
    confidence: float
    reasons: tuple[str, ...]
    # Which growth rates the score was built from: earnings_and_revenue, earnings_only, revenue_only or none.
    basis: str = "none"


class GrowthAnalysisEngine:
    """Convert fundamental growth rates into a transparent 0..100 score."""

    def __init__(self, saturation_percent: float = 20.0):
        if saturation_percent <= 0:
            raise ValueError("saturation_percent must be positive")
        self.saturation_percent = saturation_percent

    def analyze(
        self,
        earnings_growth_percent: float | None = None,
        revenue_growth_percent: float | None = None,
    ) -> GrowthAssessment:
        rates: dict[str, float] = {}
        for name, value in (("earnings", earnings_growth_percent), ("revenue", revenue_growth_percent)):
            try:
                numeric_value = float(value) if value is not None else None
            except (TypeError, ValueError):
                numeric_value = None
            if numeric_value is not None and isfinite(numeric_value):
                rates[name] = numeric_value
        if not rates:
            return GrowthAssessment(None, 0.0, ("Earnings and revenue growth data are missing.",), "none")

        scores = [
            max(0.0, min(100.0, 50.0 + 50.0 * value / self.saturation_percent))
            for value in rates.values()
        ]
        score = sum(scores) / len(scores)
        if len(rates) == 2:
            return GrowthAssessment(score, 1.0, (), "earnings_and_revenue")
        if "earnings" in rates:
            reason = "Revenue growth data is missing; the score uses earnings growth only and confidence is reduced."
            return GrowthAssessment(score, 0.5, (reason,), "earnings_only")
        reason = "Earnings growth data is missing; the score uses revenue growth only and confidence is reduced."
        return GrowthAssessment(score, 0.5, (reason,), "revenue_only")

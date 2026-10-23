from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class GrowthAssessment:
    score: float | None
    confidence: float
    reasons: tuple[str, ...]


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
        values: list[float] = []
        for value in (earnings_growth_percent, revenue_growth_percent):
            try:
                numeric_value = float(value) if value is not None else None
            except (TypeError, ValueError):
                numeric_value = None
            if numeric_value is not None and isfinite(numeric_value):
                values.append(numeric_value)
        if not values:
            return GrowthAssessment(None, 0.0, ("Earnings and revenue growth data are missing.",))

        scores = [
            max(0.0, min(100.0, 50.0 + 50.0 * float(value) / self.saturation_percent))
            for value in values
        ]
        missing = len(values) < 2
        reasons = ("Revenue or earnings growth data is missing; confidence is reduced.",) if missing else ()
        return GrowthAssessment(sum(scores) / len(scores), len(values) / 2, reasons)

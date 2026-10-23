from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .scoring import calculate_weighted_score


@dataclass(frozen=True)
class ForwardLookingAssessment:
    score: float | None
    confidence: float
    reasons: tuple[str, ...]


class ForwardLookingAnalyzer:
    """Summarize available analyst and target-price outlook without forecasting."""

    weights = {"target_upside": 60.0, "analyst_revisions": 40.0}

    def analyze(
        self,
        target_upside_percent: float | None = None,
        analyst_revisions_score: float | None = None,
    ) -> ForwardLookingAssessment:
        upside_score = None
        try:
            upside = float(target_upside_percent) if target_upside_percent is not None else None
        except (TypeError, ValueError):
            upside = None
        if upside is not None and isfinite(upside):
            upside_score = max(0.0, min(100.0, 50.0 + upside))
        try:
            revisions = float(analyst_revisions_score) if analyst_revisions_score is not None else None
        except (TypeError, ValueError):
            revisions = None
        result = calculate_weighted_score(
            {"target_upside": upside_score, "analyst_revisions": revisions},
            self.weights,
        )
        reasons = list(result.reasons)
        reasons.append("Forward-looking inputs are indicators, not guaranteed outcomes.")
        return ForwardLookingAssessment(result.score, result.confidence, tuple(reasons))

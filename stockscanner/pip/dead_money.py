from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class DeadMoneyAssessment:
    symbol: str
    is_dead_money: bool | None
    confidence: float
    reasons: tuple[str, ...]


class DeadMoneyDetector:
    """Flag persistently weak capital productivity for a human review."""

    def __init__(self, cps_threshold: float = 40.0, return_threshold: float = 0.0):
        self.cps_threshold = cps_threshold
        self.return_threshold = return_threshold

    def assess(
        self,
        symbol: str,
        cps: float | None,
        total_return_percent: float | None = None,
        opportunity_cost_score: float | None = None,
    ) -> DeadMoneyAssessment:
        values: list[float | None] = []
        for value in (cps, total_return_percent, opportunity_cost_score):
            try:
                numeric_value = float(value) if value is not None else None
            except (TypeError, ValueError):
                numeric_value = None
            values.append(numeric_value if numeric_value is not None and isfinite(numeric_value) else None)
        cps, total_return_percent, opportunity_cost_score = values
        available = [value for value in values if value is not None]
        confidence = len(available) / 3
        if not available:
            return DeadMoneyAssessment(symbol, None, 0.0, ("No lifecycle or productivity data is available.",))

        reasons: list[str] = []
        weak_cps = cps is not None and cps < self.cps_threshold
        negative_return = total_return_percent is not None and total_return_percent <= self.return_threshold
        high_opportunity_cost = opportunity_cost_score is not None and opportunity_cost_score >= 60
        if weak_cps:
            reasons.append(f"CPS is below the {self.cps_threshold:.0f}-point productivity threshold.")
        if negative_return:
            reasons.append("Total return is not positive over the analyzed holding period.")
        if high_opportunity_cost:
            reasons.append("Opportunity cost is elevated versus available alternatives.")
        detected = weak_cps and (negative_return or high_opportunity_cost)
        if not reasons:
            reasons.append("Available indicators do not show persistent capital productivity drag.")
        if len(available) < 3:
            reasons.append("Some inputs are missing; confidence is reduced.")
        return DeadMoneyAssessment(symbol, detected, confidence, tuple(reasons))

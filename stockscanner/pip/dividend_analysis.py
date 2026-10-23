from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class DividendRecord:
    """Normalized dividend record from IBKR or another vendor source."""

    symbol: str
    amount: float
    ex_date: Optional[str] = None
    pay_date: Optional[str] = None
    account_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    currency: str = "USD"
    metadata: Dict[str, Any] | None = None


class DividendAnalysisEngine:
    """Compute dividend signal quality based on income, growth, and sustainability."""

    def annualized_income(self, dividend_records: Iterable[DividendRecord]) -> float | None:
        amounts = [float(record.amount) for record in dividend_records if record.amount is not None]
        return sum(amounts) if amounts else None

    def current_yield(self, annualized_income: float | None, current_price: float | None) -> float | None:
        if annualized_income is None or current_price is None or current_price <= 0:
            return None
        return (annualized_income / current_price) * 100.0

    def growth_score(self, growth_rate: float | None) -> float | None:
        """Map a dividend growth rate to a 0..100 score."""

        if growth_rate is None or not isfinite(float(growth_rate)):
            return None
        return max(0.0, min(100.0, growth_rate * 100.0))

    def quality_score(
        self,
        annualized_income: float | None,
        current_price: float | None,
        payout_ratio: float | None,
        dividend_growth_rate: float | None,
        consistency_score: float | None,
    ) -> float | None:
        """Returns a single dividend-quality metric between 0 and 100.

        This is deliberately supportive, not a guarantee. It is used as a factor in
        more complete portfolio decision scoring rather than an independent buy/sell verdict.
        """

        yield_pct = self.current_yield(annualized_income, current_price)
        yield_score = min(100.0, yield_pct * 10.0) if yield_pct is not None else None
        growth_component = self.growth_score(dividend_growth_rate)
        consistency_component = (
            max(0.0, min(100.0, consistency_score * 100.0))
            if consistency_score is not None and isfinite(float(consistency_score)) else None
        )
        payout_component = (
            max(0.0, min(100.0, 100.0 - max(0.0, (payout_ratio - 1.0) * 100.0)))
            if payout_ratio is not None and isfinite(float(payout_ratio)) else None
        )
        components = (
            (0.30, yield_score),
            (0.30, growth_component),
            (0.25, consistency_component),
            (0.15, payout_component),
        )
        available = [(weight, value) for weight, value in components if value is not None]
        if not available:
            return None
        return sum(weight * value for weight, value in available) / sum(weight for weight, _ in available)

    def analyze(
        self,
        dividend_records: Iterable[DividendRecord],
        current_price: float | None,
        payout_ratio: float | None,
        dividend_growth_rate: float | None,
        consistency_score: float | None,
    ) -> Dict[str, Any]:
        dividend_records = list(dividend_records)
        annualized_income = self.annualized_income(dividend_records)
        yield_pct = self.current_yield(annualized_income, current_price)
        inputs = (yield_pct, dividend_growth_rate, consistency_score, payout_ratio)
        weights = (0.30, 0.30, 0.25, 0.15)
        available_weight = sum(
            weight for value, weight in zip(inputs, weights)
            if value is not None and isfinite(float(value))
        )
        missing = tuple(
            f"{name} data is missing or invalid."
            for name, value in zip(
                ("dividend yield", "dividend growth", "dividend consistency", "payout ratio"),
                inputs,
            )
            if value is None or not isfinite(float(value))
        )
        quality = self.quality_score(
            annualized_income=annualized_income,
            current_price=current_price,
            payout_ratio=payout_ratio,
            dividend_growth_rate=dividend_growth_rate,
            consistency_score=consistency_score,
        )
        return {
            "annualized_income": annualized_income,
            "current_yield_pct": yield_pct,
            "dividend_quality_score": quality,
            "growth_score": self.growth_score(dividend_growth_rate),
            "confidence": available_weight,
            "reasons": missing,
        }

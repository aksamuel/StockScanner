from __future__ import annotations

from dataclasses import dataclass
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

    def annualized_income(self, dividend_records: Iterable[DividendRecord]) -> float:
        return sum(float(record.amount) for record in dividend_records)

    def current_yield(self, annualized_income: float, current_price: float) -> float:
        if current_price <= 0:
            return 0.0
        return (annualized_income / current_price) * 100.0

    def growth_score(self, growth_rate: float) -> float:
        """Map a dividend growth rate to a 0..100 score."""

        return max(0.0, min(100.0, growth_rate * 100.0))

    def quality_score(
        self,
        annualized_income: float,
        current_price: float,
        payout_ratio: float,
        dividend_growth_rate: float,
        consistency_score: float,
    ) -> float:
        """Returns a single dividend-quality metric between 0 and 100.

        This is deliberately supportive, not a guarantee. It is used as a factor in
        more complete portfolio decision scoring rather than an independent buy/sell verdict.
        """

        yield_score = self.current_yield(annualized_income, current_price)
        growth_component = self.growth_score(dividend_growth_rate)
        payout_penalty = max(0.0, (payout_ratio - 1.0) * 100.0)
        consistency_component = max(0.0, min(100.0, consistency_score * 100.0))

        score = (
            0.30 * min(100.0, yield_score * 10.0)
            + 0.30 * growth_component
            + 0.25 * consistency_component
            + 0.15 * max(0.0, 100.0 - payout_penalty)
        )
        return max(0.0, min(100.0, score))

    def analyze(self, dividend_records: Iterable[DividendRecord], current_price: float, payout_ratio: float, dividend_growth_rate: float, consistency_score: float) -> Dict[str, float]:
        annualized_income = self.annualized_income(dividend_records)
        yield_pct = self.current_yield(annualized_income, current_price)
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
        }

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .models import ReplacementCandidate, SellRecommendation


@dataclass
class SellAdvisor:
    """Translate score data into a plain-language recommendation."""

    minimum_sell_confidence: float = 65.0
    minimum_sell_status_score: float = 45.0

    def build_recommendation(
        self,
        portfolio_id: str,
        symbol: str,
        sell_score: float,
        cps: float,
        opportunity_cost: float,
        technical_health: float,
        relative_performance: float,
        replacement_candidates: Optional[List[ReplacementCandidate]] = None,
    ) -> SellRecommendation:
        reasons: List[str] = []

        if sell_score >= self.minimum_sell_confidence:
            recommendation = "sell"
            reasons.append("Sell score is strong enough to justify exit or replacement review.")
        elif cps < self.minimum_sell_status_score:
            recommendation = "watch"
            reasons.append("Capital productivity score is weak enough to warrant a close review.")
        else:
            recommendation = "hold"
            reasons.append("Score profile does not justify a forced exit based on current evidence.")

        if opportunity_cost > 60:
            reasons.append("Opportunity cost is high, suggesting capital is better deployed elsewhere.")
        if technical_health < 40:
            reasons.append("Technical health is weak and may be dragging overall performance.")
        if relative_performance < 40:
            reasons.append("Relative performance versus the broader market is weak.")

        if replacement_candidates:
            top = "; ".join(
                f"{candidate.symbol} (+{candidate.expected_benefit:.1f} pts)"
                for candidate in replacement_candidates[:3]
            )
            reasons.append(f"Stronger replacement candidates are available: {top}.")

        if not reasons:
            reasons.append("No material risk triggers were detected from the current score set.")

        return SellRecommendation(
            portfolio_id=portfolio_id,
            symbol=symbol,
            score=float(sell_score),
            recommendation=recommendation,
            rationale=reasons,
            confidence=max(0.0, min(1.0, sell_score / 100.0)),
            created_at=datetime.utcnow(),
            status="draft",
            replacement_candidates=replacement_candidates or [],
        )

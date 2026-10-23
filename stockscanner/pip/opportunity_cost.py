from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class OpportunityCostItem:
    symbol: str
    current_value: float
    expected_benefit: float
    alternative_symbol: str | None = None
    rationale: str = ""
    confidence: float = 0.0


class OpportunityCostEngine:
    """Estimate the cost of holding a lower-quality position versus better alternatives.

    This is a portfolio-intelligence layer used for decision support, not a trade exec engine.
    """

    def compare(
        self,
        symbol: str,
        current_value: float,
        current_score: float,
        alternatives: Iterable[tuple[str, float, float]],
    ) -> List[OpportunityCostItem]:
        items: List[OpportunityCostItem] = []
        for alternative_symbol, alt_score, alt_value in alternatives:
            if alternative_symbol == symbol:
                continue
            benefit = max(0.0, (alt_score - current_score) * 0.5)
            expected_benefit = max(0.0, benefit * (alt_value / max(current_value, 1.0)))
            items.append(
                OpportunityCostItem(
                    symbol=symbol,
                    current_value=current_value,
                    expected_benefit=expected_benefit,
                    alternative_symbol=alternative_symbol,
                    rationale=f"{alternative_symbol} is stronger than {symbol} by {alt_score - current_score:.2f} score points.",
                    confidence=min(1.0, max(0.0, (alt_score / 100.0))),
                )
            )
        items.sort(key=lambda item: item.expected_benefit, reverse=True)
        return items

    def summary(self, items: Iterable[OpportunityCostItem]) -> Dict[str, float]:
        items = list(items)
        if not items:
            return {"total_expected_benefit": 0.0, "average_confidence": 0.0}
        total = sum(item.expected_benefit for item in items)
        avg_conf = sum(item.confidence for item in items) / len(items)
        return {"total_expected_benefit": total, "average_confidence": avg_conf}

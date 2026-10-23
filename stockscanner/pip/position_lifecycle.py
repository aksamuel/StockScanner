from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class PortfolioHealthSnapshot:
    symbol: str
    tsl: float = 0.0
    relative_performance: float = 0.0
    dividend_growth: float = 0.0
    earnings_growth: float = 0.0
    analyst_revisions: float = 0.0
    dividend_quality: float = 0.0
    technical_health: float = 0.0
    opportunity_cost: float = 0.0
    revisions: float = 0.0
    snapshot_time: Optional[datetime] = None
    metadata: Dict[str, Any] | None = None


class PositionLifecycleAnalyzer:
    """Create simple position lifecycle summaries from normalized holding data."""

    def __init__(self):
        self.snapshot_time = datetime.utcnow()

    def summarize_position(self, symbol: str, **fields: Any) -> PortfolioHealthSnapshot:
        snapshot = PortfolioHealthSnapshot(
            symbol=symbol,
            tsl=float(fields.get("tsl", 0.0)),
            relative_performance=float(fields.get("relative_performance", 0.0)),
            dividend_growth=float(fields.get("dividend_growth", 0.0)),
            earnings_growth=float(fields.get("earnings_growth", 0.0)),
            analyst_revisions=float(fields.get("analyst_revisions", 0.0)),
            dividend_quality=float(fields.get("dividend_quality", 0.0)),
            technical_health=float(fields.get("technical_health", 0.0)),
            opportunity_cost=float(fields.get("opportunity_cost", 0.0)),
            revisions=float(fields.get("revisions", 0.0)),
            snapshot_time=self.snapshot_time,
            metadata=dict(fields),
        )
        return snapshot

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class PortfolioHealthSnapshot:
    symbol: str
    tsl: float | None = None
    relative_performance: float | None = None
    dividend_growth: float | None = None
    earnings_growth: float | None = None
    analyst_revisions: float | None = None
    dividend_quality: float | None = None
    technical_health: float | None = None
    opportunity_cost: float | None = None
    revisions: float | None = None
    snapshot_time: Optional[datetime] = None
    metadata: Dict[str, Any] | None = None
    days_held: int | None = None
    total_return_percent: float | None = None
    price_return_percent: float | None = None


class PositionLifecycleAnalyzer:
    """Create simple position lifecycle summaries from normalized holding data."""

    def __init__(self):
        self.snapshot_time = datetime.now(timezone.utc)

    def days_since(self, entry_date: Any) -> int | None:
        if not entry_date:
            return None
        if isinstance(entry_date, datetime):
            entered = entry_date.date()
        elif isinstance(entry_date, date):
            entered = entry_date
        else:
            try:
                entered = date.fromisoformat(str(entry_date)[:10])
            except ValueError:
                return None
        return max(0, (self.snapshot_time.date() - entered).days)

    def summarize_position(self, symbol: str, **fields: Any) -> PortfolioHealthSnapshot:
        days_held = self.days_since(fields.get("entry_date"))

        invested = fields.get("cost_basis")
        market_value = fields.get("market_value")
        dividends = fields.get("dividends")
        total_return = None
        price_return = None
        if invested is not None and market_value is not None and float(invested) != 0:
            price_return = (float(market_value) / float(invested) - 1) * 100
            if dividends is not None:
                total_return = ((float(market_value) + float(dividends or 0.0)) / float(invested) - 1) * 100
        snapshot = PortfolioHealthSnapshot(
            symbol=symbol,
            tsl=fields.get("tsl", fields.get("total_return_percent")),
            relative_performance=fields.get("relative_performance"),
            dividend_growth=fields.get("dividend_growth"),
            earnings_growth=fields.get("earnings_growth"),
            analyst_revisions=fields.get("analyst_revisions"),
            dividend_quality=fields.get("dividend_quality"),
            technical_health=fields.get("technical_health"),
            opportunity_cost=fields.get("opportunity_cost"),
            revisions=fields.get("revisions"),
            snapshot_time=self.snapshot_time,
            metadata=dict(fields),
            days_held=days_held,
            total_return_percent=total_return,
            price_return_percent=price_return,
        )
        return snapshot

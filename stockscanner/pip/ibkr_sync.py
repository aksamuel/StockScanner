from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import PositionRecord


class IBKRPortfolioSyncService:
    """Sync raw IBKR portfolio data into normalized StockScanner records.

    This service deliberately does not alter existing StockScanner scanner logic.
    It normalizes IBKR files or API payloads into a single internal object model
    for downstream analytics.
    """

    def __init__(self, repository: Optional[Any] = None):
        self.repository = repository

    def normalize_position(self, raw_position: Dict[str, Any]) -> PositionRecord:
        symbol = str(raw_position.get("symbol") or raw_position.get("ticker") or "UNKNOWN")
        quantity = float(raw_position.get("quantity", 0.0) or 0.0)
        average_cost = float(raw_position.get("average_cost", 0.0) or 0.0)
        market_price = float(raw_position.get("market_price", 0.0) or 0.0)
        market_value = float(raw_position.get("market_value", 0.0) or 0.0)
        cost_basis = quantity * average_cost if quantity else 0.0

        return PositionRecord(
            symbol=symbol,
            account_id=str(raw_position.get("account_id") or ""),
            portfolio_id=str(raw_position.get("portfolio_id") or ""),
            quantity=quantity,
            average_cost=average_cost,
            market_price=market_price,
            market_value=market_value,
            currency=str(raw_position.get("currency", "USD") or "USD"),
            cost_basis=cost_basis,
            entry_date=raw_position.get("entry_date"),
            last_updated=datetime.utcnow(),
            notes={
                "source": raw_position.get("source", "ibkr"),
                "raw": raw_position,
            },
        )

    def sync_portfolio(self, raw_positions: List[Dict[str, Any]]) -> List[PositionRecord]:
        records: List[PositionRecord] = []
        for raw_position in raw_positions:
            records.append(self.normalize_position(raw_position))
        return records

    def persist_positions(self, portfolio_id: str, positions: List[PositionRecord]) -> List[PositionRecord]:
        """Hook point for repository integration.

        The default implementation is intentionally simple. In production, this
        method would insert or upsert into the `positions` table using the
        configured Supabase client.
        """

        if self.repository is None:
            return positions

        for position in positions:
            position.portfolio_id = portfolio_id
        return positions

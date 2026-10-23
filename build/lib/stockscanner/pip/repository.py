from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from .models import PositionRecord, SellRecommendation


class PortfolioRepository:
    """Repository interface for the portfolio intelligence layer."""

    def upsert_positions(self, portfolio_id: str, positions: Iterable[PositionRecord]) -> List[PositionRecord]:
        raise NotImplementedError

    def upsert_score(self, portfolio_id: str, symbol: str, score_record: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def create_recommendation(self, recommendation: SellRecommendation) -> SellRecommendation:
        raise NotImplementedError


class InMemoryPortfolioRepository(PortfolioRepository):
    """Simple in-memory implementation suitable for tests and local prototypes."""

    def __init__(self):
        self.positions: Dict[str, List[PositionRecord]] = {}
        self.scores: Dict[str, Dict[str, Any]] = {}
        self.recommendations: List[SellRecommendation] = []

    def upsert_positions(self, portfolio_id: str, positions: Iterable[PositionRecord]) -> List[PositionRecord]:
        batch = list(positions)
        self.positions.setdefault(portfolio_id, [])
        existing = {p.symbol: p for p in self.positions[portfolio_id]}
        for position in batch:
            existing[position.symbol] = position
        self.positions[portfolio_id] = list(existing.values())
        return list(existing.values())

    def upsert_score(self, portfolio_id: str, symbol: str, score_record: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{portfolio_id}:{symbol}"
        self.scores[key] = score_record
        return score_record

    def create_recommendation(self, recommendation: SellRecommendation) -> SellRecommendation:
        self.recommendations.append(recommendation)
        return recommendation


@dataclass(frozen=True)
class SupabaseAuditLogSink:
    """Insert redacted workflow events into the owner-scoped append-only table."""

    client: Any
    portfolio_id: str
    user_id: str

    def __call__(self, event: Dict[str, Any]) -> None:
        recommendation_id = event.get("entity_id")
        if recommendation_id is not None:
            UUID(str(recommendation_id))
        payload = {
            "portfolio_id": str(UUID(self.portfolio_id)),
            "user_id": str(UUID(self.user_id)),
            "entity_type": event["entity_type"],
            "entity_id": str(recommendation_id) if recommendation_id is not None else None,
            "event_type": event["event_type"],
            "event_details": {
                key: value for key, value in event.items()
                if key not in {"entity_type", "entity_id", "event_type", "created_at"}
            },
            "created_at": event["created_at"],
        }
        result = self.client.table("audit_logs").insert(payload).execute()
        if getattr(result, "error", None):
            raise RuntimeError("Unable to persist PIP audit event")
        update = {"status": event["to_status"]}
        if event["to_status"] == "approved":
            update["approved_by"] = event.get("actor")
        state_result = self.client.table("sell_recommendations").update(update).eq("id", str(recommendation_id)).execute()
        if getattr(state_result, "error", None):
            raise RuntimeError("Unable to persist PIP approval state")


class SupabasePortfolioRepository(PortfolioRepository):
    """Duck-typed Supabase adapter; tests can provide a client fixture."""

    def __init__(self, client: Any):
        self.client = client
        self.account_ids: dict[str, str] = {}

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if is_dataclass(value):
            return SupabasePortfolioRepository._json_safe(asdict(value))
        if isinstance(value, dict):
            return {key: SupabasePortfolioRepository._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [SupabasePortfolioRepository._json_safe(item) for item in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> list[dict[str, Any]]:
        if not rows:
            return []
        response = self.client.table(table).upsert(rows, on_conflict=on_conflict).execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Unable to persist PIP {table} records")
        return list(getattr(response, "data", None) or [])

    def upsert_accounts(self, portfolio_id: str, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [
            {**account, "portfolio_id": portfolio_id}
            for account in accounts
            if account.get("masked_account_id")
        ]
        if not rows:
            return []
        response = (
            self.client.table("ibkr_accounts")
            .upsert(rows, on_conflict="portfolio_id,masked_account_id")
            .select("id,masked_account_id")
            .execute()
        )
        if getattr(response, "error", None):
            raise RuntimeError("Unable to persist PIP ibkr_accounts records")
        saved = list(getattr(response, "data", None) or [])
        for account in saved:
            masked_id = account.get("masked_account_id")
            account_id = account.get("id")
            if masked_id and account_id:
                self.account_ids[str(masked_id)] = str(account_id)
        return saved

    def upsert_positions(self, portfolio_id: str, positions: Iterable[PositionRecord]) -> list[dict[str, Any]]:
        rows = []
        for position in positions:
            account_key = position.account_id or "unassigned"
            rows.append({
                "portfolio_id": portfolio_id,
                "account_id": self.account_ids.get(account_key),
                "symbol": position.symbol,
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "market_price": position.market_price,
                "market_value": position.market_value,
                "cost_basis": position.cost_basis,
                "currency": position.currency,
                "entry_date": position.entry_date.isoformat() if position.entry_date else None,
                "last_updated": position.last_updated.isoformat() if position.last_updated else None,
                "source_key": f"{account_key}:{position.symbol}",
                "metadata": position.notes,
            })
        return self._upsert("positions", rows, "portfolio_id,source_key")

    @staticmethod
    def _source_key(row: dict[str, Any]) -> str:
        content = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def upsert_transactions(self, portfolio_id: str, transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [{**transaction, "portfolio_id": portfolio_id} for transaction in transactions]
        for row in rows:
            row["source_key"] = self._source_key(row)
        return self._upsert("transactions", rows, "portfolio_id,source_key")

    def upsert_dividends(self, portfolio_id: str, dividends: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for dividend in dividends:
            row = {
                "portfolio_id": portfolio_id,
                "symbol": dividend["symbol"],
                "dividend_amount": dividend["amount"],
                "ex_date": dividend["ex_date"].isoformat() if dividend["ex_date"] else None,
                "pay_date": dividend["pay_date"].isoformat() if dividend["pay_date"] else None,
                "metadata": {"currency": dividend["currency"]},
            }
            row["source_key"] = self._source_key(row)
            rows.append(row)
        return self._upsert("dividends", rows, "portfolio_id,source_key")

    def upsert_score(self, portfolio_id: str, symbol: str, score_record: Dict[str, Any]) -> Dict[str, Any]:
        columns = {
            "cps", "sell_score", "tsr", "relative_performance", "dividend_growth",
            "earnings_growth", "analyst_revisions", "dividend_quality",
            "technical_health", "opportunity_cost", "revisions", "calculated_at",
        }
        row = {
            key: value for key, value in score_record.items()
            if key in columns
        }
        row.update({"portfolio_id": portfolio_id, "symbol": symbol})
        row["metadata"] = {
            key: self._json_safe(value) for key, value in score_record.items()
            if key not in columns | {"portfolio_id", "symbol"}
        }
        row = self._json_safe(row)
        response = self._upsert("stock_scores", [row], "portfolio_id,symbol")
        return response[0] if response else row

    def create_recommendation(self, recommendation: SellRecommendation) -> SellRecommendation:
        if recommendation.id is None:
            recommendation.id = str(uuid4())
        row = {
            "id": recommendation.id,
            "portfolio_id": recommendation.portfolio_id,
            "symbol": recommendation.symbol,
            "score": recommendation.score,
            "recommendation": recommendation.recommendation,
            "rationale": recommendation.rationale,
            "confidence": recommendation.confidence,
            "status": recommendation.status,
            "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
            "approved_by": recommendation.approved_by,
            "metadata": {
                "replacement_candidates": [
                    {
                        "symbol": candidate.symbol,
                        "score": candidate.score,
                        "expected_benefit": candidate.expected_benefit,
                        "confidence": candidate.confidence,
                        "rationale": candidate.rationale,
                    }
                    for candidate in recommendation.replacement_candidates
                ],
            },
        }
        row = self._json_safe(row)
        response = self.client.table("sell_recommendations").insert(row).execute()
        if getattr(response, "error", None):
            raise RuntimeError("Unable to persist PIP sell recommendation")
        if recommendation.replacement_candidates and recommendation.portfolio_id:
            replacements = [
                {
                    "portfolio_id": recommendation.portfolio_id,
                    "current_symbol": recommendation.symbol,
                    "candidate_symbol": candidate.symbol,
                    "score": candidate.score,
                    "expected_benefit": candidate.expected_benefit,
                    "confidence": candidate.confidence,
                    "rationale": candidate.rationale,
                }
                for candidate in recommendation.replacement_candidates
            ]
            self._upsert(
                "replacement_candidates",
                replacements,
                "portfolio_id,current_symbol,candidate_symbol",
            )
        return recommendation


__all__ = [
    "PortfolioRepository",
    "InMemoryPortfolioRepository",
    "SupabaseAuditLogSink",
    "SupabasePortfolioRepository",
]

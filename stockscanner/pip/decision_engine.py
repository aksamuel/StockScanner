from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .models import PositionRecord, ReplacementCandidate, SellRecommendation
from .replacement_engine import ReplacementCandidateEngine
from .scoring import calculate_cps, calculate_sell_score


@dataclass
class PortfolioAnalysisResult:
    symbol: str
    cps: float
    sell_score: float
    recommendation: str
    rationale: List[str]
    metadata: Dict[str, Any]


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


class DecisionEngine:
    """Glue layer that computes portfolio decisions from normalized holding data."""

    def __init__(self, repository: Optional[PortfolioRepository] = None):
        self.repository = repository or InMemoryPortfolioRepository()

    def analyze_position(
        self,
        portfolio_id: str,
        symbol: str,
        tsr: float,
        relative_performance: float,
        dividend_growth: float,
        earnings_growth: float,
        analyst_revisions: float,
        dividend_quality: float,
        technical_health: float,
        opportunity_cost: float,
        revisions: float,
        recommendation_threshold: float = 65.0,
        peer_scores: Optional[Iterable[tuple[str, float]]] = None,
        replacement_limit: int = 5,
    ) -> PortfolioAnalysisResult:
        cps = calculate_cps(
            tsr=tsr,
            relative_performance=relative_performance,
            dividend_growth=dividend_growth,
            earnings_growth=earnings_growth,
            analyst_revisions=analyst_revisions,
        )

        sell_score = calculate_sell_score(
            tsr=tsr,
            relative_performance=relative_performance,
            revisions=revisions,
            dividend_quality=dividend_quality,
            technical_health=technical_health,
            earnings_growth=earnings_growth,
            opportunity_cost=opportunity_cost,
        )

        replacement_candidates: List[ReplacementCandidate] = []
        if peer_scores is not None:
            replacement_candidates = ReplacementCandidateEngine().generate_candidates(
                symbol=symbol,
                current_score=sell_score,
                peer_scores=peer_scores,
                max_candidates=replacement_limit,
            )

        if sell_score >= recommendation_threshold:
            recommendation = "sell"
            rationale = [
                "Sell score is above the review threshold.",
                "Weak relative performance and weak opportunity usage justify a review.",
            ]
        elif cps < 45:
            recommendation = "watch"
            rationale = [
                "CPS is below the minimum quality bar.",
                "The position may be dragging portfolio productivity.",
            ]
        else:
            recommendation = "hold"
            rationale = [
                "The current evidence does not justify exit action.",
                "Continue monitoring with a normal review cadence.",
            ]

        score_record = {
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "cps": cps,
            "sell_score": sell_score,
            "tsr": tsr,
            "relative_performance": relative_performance,
            "dividend_growth": dividend_growth,
            "earnings_growth": earnings_growth,
            "analyst_revisions": analyst_revisions,
            "dividend_quality": dividend_quality,
            "technical_health": technical_health,
            "opportunity_cost": opportunity_cost,
            "revisions": revisions,
            "replacement_candidates": replacement_candidates,
        }

        self.repository.upsert_score(portfolio_id, symbol, score_record)

        recommendation_record = SellRecommendation(
            portfolio_id=portfolio_id,
            symbol=symbol,
            score=sell_score,
            recommendation=recommendation,
            rationale=rationale,
            confidence=max(0.0, min(1.0, sell_score / 100.0)),
            status="draft",
            replacement_candidates=replacement_candidates,
        )
        self.repository.create_recommendation(recommendation_record)

        return PortfolioAnalysisResult(
            symbol=symbol,
            cps=cps,
            sell_score=sell_score,
            recommendation=recommendation,
            rationale=rationale,
            metadata=score_record,
        )

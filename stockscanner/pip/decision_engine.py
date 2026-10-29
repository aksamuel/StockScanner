from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4

from .models import PositionRecord, ReplacementCandidate, SellRecommendation
from .replacement_engine import ReplacementCandidateEngine
from .scoring import calculate_cps_result, calculate_sell_score_result
from .sell_advisor import SellAdvisor


@dataclass
class PortfolioAnalysisResult:
    symbol: str
    cps: float | None
    sell_score: float | None
    recommendation: str
    rationale: List[str]
    metadata: Dict[str, Any]
    confidence: float = 0.0


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
        self.last_recommendation: SellRecommendation | None = None

    def analyze_position(
        self,
        portfolio_id: str,
        symbol: str,
        tsr: float | None,
        relative_performance: float | None,
        dividend_growth: float | None,
        earnings_growth: float | None,
        analyst_revisions: float | None,
        dividend_quality: float | None,
        technical_health: float | None,
        opportunity_cost: float | None,
        revisions: float | None,
        recommendation_threshold: float = 65.0,
        peer_scores: Optional[Iterable[tuple[str, float]]] = None,
        replacement_limit: int = 5,
        candidate_cps: Optional[Dict[str, float]] = None,
        held_symbols: Optional[Iterable[str]] = None,
        concentrations: Optional[Dict[str, float]] = None,
        max_concentration_percent: float = 100.0,
        additional_metadata: Optional[Mapping[str, Any]] = None,
    ) -> PortfolioAnalysisResult:
        cps_result = calculate_cps_result(
            {
                "tsr": tsr,
                "relative_performance": relative_performance,
                "dividend_growth": dividend_growth,
                "earnings_growth": earnings_growth,
                "analyst_revisions": analyst_revisions,
            }
        )
        sell_result = calculate_sell_score_result(
            {
                "tsr": tsr,
                "relative_performance": relative_performance,
                "revisions": revisions,
                "dividend_quality": dividend_quality,
                "technical_health": technical_health,
                "earnings_growth": earnings_growth,
                "opportunity_cost": opportunity_cost,
            }
        )
        cps = cps_result.score
        sell_score = sell_result.score

        replacement_candidates: List[ReplacementCandidate] = []
        if peer_scores is not None and cps is not None:
            replacement_candidates = ReplacementCandidateEngine().generate_candidates(
                symbol=symbol,
                current_score=cps,
                peer_scores=peer_scores,
                max_candidates=replacement_limit,
                candidate_cps=candidate_cps,
                held_symbols=held_symbols or (),
                concentrations=concentrations,
                max_concentration_percent=max_concentration_percent,
            )

        confidence = min(cps_result.confidence, sell_result.confidence)
        missing_data_reasons = list(dict.fromkeys(cps_result.reasons + sell_result.reasons))
        advice = SellAdvisor(minimum_sell_confidence=recommendation_threshold).build_recommendation(
            portfolio_id=portfolio_id,
            symbol=symbol,
            sell_score=sell_score,
            cps=cps,
            opportunity_cost=opportunity_cost,
            technical_health=technical_health,
            relative_performance=relative_performance,
            replacement_candidates=replacement_candidates,
            confidence=confidence,
            missing_data_reasons=missing_data_reasons,
        )
        recommendation = advice.recommendation
        rationale = advice.rationale

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
            "cps_confidence": cps_result.confidence,
            "sell_score_confidence": sell_result.confidence,
            "missing_data_reasons": missing_data_reasons,
            **(additional_metadata or {}),
        }

        self.repository.upsert_score(portfolio_id, symbol, score_record)

        recommendation_record = SellRecommendation(
            id=str(uuid4()),
            portfolio_id=portfolio_id,
            symbol=symbol,
            score=sell_score,
            recommendation=recommendation,
            rationale=rationale,
            confidence=confidence,
            status="draft",
            replacement_candidates=replacement_candidates,
        )
        self.last_recommendation = self.repository.create_recommendation(recommendation_record)

        return PortfolioAnalysisResult(
            symbol=symbol,
            cps=cps,
            sell_score=sell_score,
            recommendation=recommendation,
            rationale=rationale,
            metadata=score_record,
            confidence=confidence,
        )

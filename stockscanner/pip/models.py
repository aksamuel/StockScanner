from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class PositionRecord:
    """Normalized portfolio holding record.

    This object represents the canonical shape used by the PIP services rather
    than whichever broker or CSV format was used to import the data.
    """

    symbol: str
    account_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    quantity: float = 0.0
    average_cost: Optional[float] = None
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    currency: str = "USD"
    cost_basis: Optional[float] = None
    entry_date: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreBreakdown:
    """Named score components used for all model calculations."""

    tsr: float = 0.0
    relative_performance: float = 0.0
    dividend_growth: float = 0.0
    earnings_growth: float = 0.0
    analyst_revisions: float = 0.0
    dividend_quality: float = 0.0
    technical_health: float = 0.0
    opportunity_cost: float = 0.0
    revisions: float = 0.0


@dataclass
class ReplacementCandidate:
    """Replacement candidate with a score and rationale."""

    symbol: str
    score: Optional[float]
    rationale: List[str] = field(default_factory=list)
    expected_benefit: float = 0.0
    confidence: float = 0.0


@dataclass
class SellRecommendation:
    """Recommendation object created by the sell advisor."""

    portfolio_id: Optional[str]
    symbol: str
    score: float
    recommendation: str
    rationale: List[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    status: str = "draft"
    replacement_candidates: List[ReplacementCandidate] = field(default_factory=list)
    id: Optional[str] = None


@dataclass
class ApprovalRecord:
    """Decision record for a sell recommendation or approval workflow step."""

    recommendation_id: Optional[str]
    status: str
    actor: Optional[str]
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

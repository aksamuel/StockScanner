"""Portfolio intelligence package for StockScanner.

This package is intentionally additive and keeps the existing StockScanner scanner
and report workflows intact. The goal is to support portfolio analytics, score
calculation, replacement analysis and approval tracking around the existing stock
scanner system.
"""

from .approval_workflow import ApprovalDecision, ApprovalStatus, ApprovalWorkflow
from .ibkr_sync import IBKRPortfolioSyncService
from .models import (
    ApprovalRecord,
    PositionRecord,
    ReplacementCandidate,
    ScoreBreakdown,
    SellRecommendation,
)
from .replacement_engine import ReplacementCandidateEngine
from .scoring import (
    calculate_cps,
    calculate_sell_score,
    normalize_score,
    score_weighted_average,
)
from .sell_advisor import SellAdvisor

__all__ = [
    "ApprovalDecision",
    "ApprovalRecord",
    "ApprovalStatus",
    "ApprovalWorkflow",
    "IBKRPortfolioSyncService",
    "PositionRecord",
    "ReplacementCandidate",
    "ReplacementCandidateEngine",
    "ScoreBreakdown",
    "SellAdvisor",
    "SellRecommendation",
    "calculate_cps",
    "calculate_sell_score",
    "normalize_score",
    "score_weighted_average",
]

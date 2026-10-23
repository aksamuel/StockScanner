from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from .models import ReplacementCandidate


@dataclass
class ReplacementCandidateEngine:
    """Generate ranked candidate replacements for weak or suboptimal current holdings."""

    universe: Sequence[str] = field(default_factory=list)
    minimum_score_gap: float = 0.0
    max_candidates: int = 5

    def generate_candidates(
        self,
        symbol: str,
        current_score: float,
        peer_scores: Iterable[tuple[str, float]],
        max_candidates: int | None = None,
        minimum_gap: float | None = None,
    ) -> List[ReplacementCandidate]:
        limit = max_candidates if max_candidates is not None else self.max_candidates
        threshold = minimum_gap if minimum_gap is not None else self.minimum_score_gap

        candidates: List[ReplacementCandidate] = []
        for candidate_symbol, candidate_score in peer_scores:
            if not candidate_symbol or candidate_symbol == symbol:
                continue

            score_gap = float(candidate_score) - float(current_score)
            if score_gap <= threshold:
                continue

            rationale = [
                f"{candidate_symbol} outperforms {symbol} by {score_gap:.1f} points.",
                "The replacement candidate has a stronger relative score and may improve capital productivity.",
            ]
            candidates.append(
                ReplacementCandidate(
                    symbol=candidate_symbol,
                    score=float(candidate_score),
                    rationale=rationale,
                    expected_benefit=max(0.0, score_gap),
                    confidence=min(1.0, max(0.0, float(candidate_score) / 100.0)),
                )
            )

        candidates.sort(key=lambda item: (item.expected_benefit, item.score), reverse=True)
        return candidates[:limit]

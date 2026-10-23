from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from .models import ReplacementCandidate


@dataclass
class ReplacementCandidateEngine:
    """Generate candidate replacements for weak or suboptimal current holdings."""

    universe: Sequence[str] = field(default_factory=list)

    def generate_candidates(
        self,
        symbol: str,
        current_score: float,
        peer_scores: Iterable[tuple[str, float]],
        max_candidates: int = 5,
    ) -> List[ReplacementCandidate]:
        candidates: List[ReplacementCandidate] = []

        for candidate_symbol, candidate_score in peer_scores:
            if candidate_symbol == symbol:
                continue
            if not candidate_symbol:
                continue

            expected_benefit = max(0.0, candidate_score - current_score)
            rationale = [
                f"{candidate_symbol} scores higher than {symbol}",
                "Candidate has stronger relative score quality and may improve capital productivity",
            ]
            candidates.append(
                ReplacementCandidate(
                    symbol=candidate_symbol,
                    score=float(candidate_score),
                    rationale=rationale,
                    expected_benefit=expected_benefit,
                    confidence=min(1.0, max(0.0, candidate_score / 100.0)),
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:max_candidates]

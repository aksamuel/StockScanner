from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable, List, Mapping, Sequence

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
        candidate_cps: Mapping[str, float] | None = None,
        held_symbols: Iterable[str] = (),
        concentrations: Mapping[str, float] | None = None,
        max_concentration_percent: float = 100.0,
    ) -> List[ReplacementCandidate]:
        limit = max_candidates if max_candidates is not None else self.max_candidates
        threshold = minimum_gap if minimum_gap is not None else self.minimum_score_gap
        if limit < 0 or not 0 <= max_concentration_percent <= 100:
            raise ValueError("candidate limit or concentration limit is invalid")
        held = {held_symbol.strip().upper() for held_symbol in held_symbols}
        held.add(symbol.strip().upper())

        candidates: List[ReplacementCandidate] = []
        for candidate_symbol, candidate_score in peer_scores:
            normalized_symbol = str(candidate_symbol or "").strip().upper()
            if not normalized_symbol or normalized_symbol in held:
                continue
            try:
                scanner_score = float(candidate_score)
            except (TypeError, ValueError):
                continue
            if not isfinite(scanner_score):
                continue
            try:
                current_concentration = float((concentrations or {}).get(normalized_symbol, 0.0))
            except (TypeError, ValueError):
                continue
            if not isfinite(current_concentration) or current_concentration >= max_concentration_percent:
                continue
            candidate_fundamental_score = (candidate_cps or {}).get(normalized_symbol)
            if candidate_fundamental_score is None:
                rank_score = scanner_score
            else:
                try:
                    fundamental_score = float(candidate_fundamental_score)
                except (TypeError, ValueError):
                    continue
                if not isfinite(fundamental_score):
                    continue
                rank_score = (scanner_score + max(0.0, min(100.0, fundamental_score))) / 2
            score_gap = rank_score - float(current_score)
            if score_gap <= threshold:
                continue

            rationale = [
                f"{candidate_symbol} outperforms {symbol} by {score_gap:.1f} points.",
                "The replacement candidate has a stronger relative score and may improve capital productivity.",
            ]
            if candidate_fundamental_score is not None:
                rationale.append("Ranking combines existing scanner output with the candidate's CPS.")
            if current_concentration:
                rationale.append(f"Current candidate concentration is {float(current_concentration):.1f}%.")
            candidates.append(
                ReplacementCandidate(
                    symbol=normalized_symbol,
                    score=rank_score,
                    rationale=rationale,
                    expected_benefit=max(0.0, score_gap),
                    confidence=min(1.0, max(0.0, rank_score / 100.0)),
                )
            )

        candidates.sort(key=lambda item: (item.expected_benefit, item.score), reverse=True)
        return candidates[:limit]

from __future__ import annotations

from stockscanner.pip.replacement_engine import ReplacementCandidateEngine


def test_replacement_engine_candidates_are_ranked_by_improvement():
    engine = ReplacementCandidateEngine()
    candidates = engine.generate_candidates(
        symbol="AAPL",
        current_score=55.0,
        peer_scores=[
            ("MSFT", 82.0),
            ("NVDA", 92.0),
            ("AAPL", 55.0),
            ("META", 58.0),
        ],
        max_candidates=3,
    )

    assert len(candidates) == 3
    assert candidates[0].symbol == "NVDA"
    assert candidates[0].expected_benefit >= candidates[1].expected_benefit
    assert candidates[0].expected_benefit > 0
    assert candidates[0].confidence <= 1.0

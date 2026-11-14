from __future__ import annotations

import pytest

from stockscanner.pip.growth_analysis import GrowthAnalysisEngine


def test_a_score_from_both_inputs_names_both_and_needs_no_caveat():
    result = GrowthAnalysisEngine().analyze(earnings_growth_percent=20, revenue_growth_percent=10)

    assert result.basis == "earnings_and_revenue"
    assert result.score == pytest.approx(87.5)
    assert result.confidence == 1.0
    assert result.reasons == ()


def test_a_score_from_earnings_alone_says_revenue_is_missing():
    result = GrowthAnalysisEngine().analyze(earnings_growth_percent=10)

    assert result.basis == "earnings_only"
    assert result.score == pytest.approx(75.0)
    assert result.confidence == 0.5
    assert result.reasons == (
        "Revenue growth data is missing; the score uses earnings growth only and confidence is reduced.",
    )


def test_a_score_from_revenue_alone_is_not_passed_off_as_earnings_growth():
    result = GrowthAnalysisEngine().analyze(revenue_growth_percent=10)

    assert result.basis == "revenue_only"
    assert result.score == pytest.approx(75.0)
    assert result.confidence == 0.5
    assert result.reasons == (
        "Earnings growth data is missing; the score uses revenue growth only and confidence is reduced.",
    )


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"earnings_growth_percent": float("nan")},
        {"earnings_growth_percent": float("inf"), "revenue_growth_percent": "n/a"},
        {"revenue_growth_percent": float("-inf")},
    ],
)
def test_no_usable_input_gives_no_score_and_no_basis(inputs):
    result = GrowthAnalysisEngine().analyze(**inputs)

    assert (result.score, result.confidence, result.basis) == (None, 0.0, "none")
    assert result.reasons == ("Earnings and revenue growth data are missing.",)


def test_an_unusable_input_counts_as_missing_not_as_zero_growth():
    result = GrowthAnalysisEngine().analyze(earnings_growth_percent=float("nan"), revenue_growth_percent=10)

    assert result.basis == "revenue_only"
    assert result.score == pytest.approx(75.0)


def test_growth_rates_saturate_at_the_ends_of_the_scale():
    engine = GrowthAnalysisEngine()

    assert engine.analyze(earnings_growth_percent=500).score == 100.0
    assert engine.analyze(revenue_growth_percent=-500).score == 0.0


@pytest.mark.parametrize("saturation_percent", [0, -5])
def test_the_saturation_point_must_be_positive_so_scoring_never_divides_by_zero(saturation_percent):
    with pytest.raises(ValueError, match="saturation_percent must be positive"):
        GrowthAnalysisEngine(saturation_percent)

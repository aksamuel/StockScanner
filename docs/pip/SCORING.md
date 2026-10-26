# PIP Scoring

All component values are finite scores normalized to the 0–100 interval. The
weighted average divides by the sum of weights, so it does not depend on whether
the configurable weights are expressed as percentages or fractions.

## Capital Productivity Score

`CPS_WEIGHTS` in `stockscanner/pip/scoring.py` is the single source for:

| Component | Weight |
| --- | ---: |
| TSR | 40 |
| Relative performance vs. SPY | 20 |
| Dividend growth | 15 |
| Earnings growth | 15 |
| Analyst revisions | 10 |

## Sell Confidence Score

`SELL_SCORE_WEIGHTS` in the same module is the single source for:

| Component | Weight |
| --- | ---: |
| TSR | 20 |
| Relative performance | 20 |
| Revisions | 20 |
| Dividend quality | 15 |
| Technical health | 15 |
| Earnings growth | 10 |
| Opportunity cost | 15 |
| **Total** | **115** |

> **Open question for maintainer:** The supplied Sell Score weights add to 115%,
> not 100%. They are preserved exactly as specified and the weighted result is
> divided by 115 (or, generally, by the sum of configured weights). Confirm whether
> the weights should be revised in a later release. Change the one
> `SELL_SCORE_WEIGHTS` mapping if the approved weights change.

## Missing data and determinism

Use `calculate_cps_result` or `calculate_sell_score_result` when confidence and
missing-input reasons are needed. Missing or invalid components are excluded from
the numerator and denominator; confidence is the available weight divided by
total configured weight. If all inputs are missing, the score is `None`, confidence
is zero, and the result contains a reason. The `calculate_cps` and
`calculate_sell_score` helpers return the score for existing callers.

Input scores outside 0–100 are clamped; non-finite and non-numeric inputs are
treated as missing. Scores use no current-time, network, or random inputs.
Confidence is input coverage only and is not reduced because the resulting score
is low. Replacement candidates are compared against the current holding's CPS,
not its separately weighted Sell Score.

Dividend income is named `trailing_twelve_month_income` and includes only dated
events in the trailing 365-day window. If the events have no usable dates, income
and yield are unavailable rather than treating an arbitrary multi-period sum as
annualized.

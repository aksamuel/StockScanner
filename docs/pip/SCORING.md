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

## Return hurdle and dead money

The return hurdle compares what a holding has earned since entry with an annual
return you require. It defaults to 7% per year and can be set from 0% to 100% in
each analysis request (`hurdle.required_annual_return_percent`); it is not stored
per portfolio. The API reports `"hurdle_analysis": 1` on `/healthz`, and the
workbench refuses to analyze against an API that does not.

| Topic | Rule |
| --- | --- |
| Hurdle path | Each lot's cost compounds at the required return from that lot's own entry date (365-day year). Stored positions are measured lot by lot; a cost basis or entry date entered in the analysis form is treated as a single lot. |
| Return basis | Market value plus dividends received. Dividends come only from the **Dividends received** input (enter 0 if none); stored dividend history is not summed. If it is missing or invalid, the basis is `price_only` and the status stays `unavailable` unless the price return already meets the path. |
| Verdict | `meets` when the current value is at or above the path. `below` only after at least 365 cost-weighted days with dividends known. Otherwise `unavailable`. Periods under one year are not annualized. |
| Shortfall | Path value minus current value; negative when the holding is ahead of the path. |
| Catch-up requirement | The annual return needed over the next 1, 3 and 5 years to reach the path (`required_return_by_horizon`). It is a requirement, not a prediction. |
| Outlook | Only an analyst target upside (entered or stored) gives an outlook: `below` when it is under the hurdle, otherwise `meets`. Without it the outlook is `unavailable`. |
| What-if scenarios | `years_to_catch_up` and `replacement_months_to_hurdle_gain` (12 × ln(1 + hurdle) ÷ ln(1 + assumed return)) are computed only from assumed annual returns you enter (greater than −100% up to 1,000%). They are arithmetic, not forecasts, dates or guarantees. PIP never estimates a future return. |

Dead money uses the hurdle as additional evidence. A holding is flagged when a
CPS below 40 coincides with a non-positive total return, a return below the
hurdle, or high opportunity cost, or when it is below the hurdle and its analyst
target upside is also below the hurdle. Below the hurdle with neither a CPS nor
an outlook is reported as insufficient data rather than flagged. Unavailable
hurdle or outlook evidence lowers the assessment's input confidence. A request
without hurdle evidence behaves as before.

The hurdle result is saved in `stock_scores.metadata.modules.hurdle`, so no schema
change is needed. A flag is a prompt for human review; PIP never submits or
approves an order, and replacement candidates are ranked only from the symbols
and scores you supply.

## Portfolio review

The portfolio review ranks a portfolio's open holdings by how far they trail the
return hurdle and attaches dead-money and replacement advice to the few furthest
behind. It only reads saved positions, scores and analyst signals: it writes
nothing, changes no recommendation, and never places, approves or transmits an
order. It runs only when you press **Review portfolio**
(`POST /api/pip/portfolios/{id}/review`); importing or syncing a portfolio does not
run it. The API reports `"portfolio_review": 1` on `/healthz`, and the workbench
refuses to review against an API that does not.

| Topic | Rule |
| --- | --- |
| Request | `required_annual_return_percent` (default 7, 0–100), `top_n` (default 5, 1–20), `replacement_limit` (default 5, 1–10) and optional `peer_scores` (up to 500 symbol/score pairs, scores 0–100, each symbol once). Unknown fields are rejected. |
| Ranked holdings | Lots are grouped by symbol. A holding is ranked only when its cost-weighted holding period is at least 365 days and its value is below the hurdle path. Holdings held under a year, or on or ahead of the path, are counted in the summary but not ranked. |
| Order | Percentage points behind the hurdle path, furthest first; ties by symbol. Advice is attached to the first `top_n` holdings only, and the summary still counts every holding behind the path. |
| Return basis | Always `price_only`. The review does not know dividends received, so dividend payers can look further behind than they are. |
| Skipped holdings | Grouped by reason, with at most 20 symbols each: positions in more than one currency or with no currency recorded (PIP does not convert currencies), short positions, a missing or non-positive cost basis, a missing entry date, a missing market value, or a path that cannot be computed. |
| Dead money | The saved CPS and opportunity-cost scores and the latest saved analyst target feed the dead-money rules above; the review supplies no total return. Because dividends are unknown, a "not dead money" result is returned as `null` (verdict withheld) instead of an all-clear. Analyze the holding and enter dividends received to confirm. |
| Replacements | Only symbols you supply in `peer_scores` are considered. Candidates must score above the holding's saved CPS (not its Sell Score); the holding itself and any symbol you already hold are excluded. Without candidate scores or a saved CPS the holding is reported as "not compared". A candidate's `confidence` is its score ÷ 100, not input coverage, so the workbench does not show it. |
| Timing | The review never estimates when a holding will recover or a replacement will reach the hurdle. Use the single-holding analysis with assumed returns for catch-up arithmetic. |
| Limits | Reads at most 10,000 positions (10 pages of 1,000). If that limit is reached the result is flagged `truncated` and the ranking may be incomplete. It also reads at most 1,000 saved scores and the 1,000 most recent analyst signals per portfolio. |

A review result is a prompt for human review, not advice to sell. Approval of a
recommendation remains a separate, explicit human step that records a decision
only.

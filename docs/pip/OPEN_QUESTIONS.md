# PIP Open Questions

- **Sell Score weights:** supplied components total 115%. Current code preserves
  each weight and normalizes by the total. See `SCORING.md` for the maintainer
  decision.
- **Revenue growth as earnings growth:** when no earnings growth score is supplied
  or saved, the capital productivity and sell scores use the growth analysis score,
  which averages earnings and revenue growth and falls back to revenue growth
  alone. Results now say which data they used (`earnings_growth_input`), but the
  substitution itself is unchanged. Decide whether revenue-only growth should fill
  the earnings growth component at all or leave it missing. See `SCORING.md`.
- **Dividends in the hurdle and portfolio review:** both use only the **Dividends
  received** input, never stored dividend history, because stored history can be
  incomplete (a positions-only sync imports none, and a Flex statement covers a
  limited period that PIP does not record). A dividends-aware version would add
  stored dividends only where the imported statement period is known to cover the
  whole holding period (entry date to today), and would otherwise stay price-only
  and say why. It also needs the Flex Query's Cash Transactions section. Not
  implemented; confirm that rule, and how partial history should be shown, before
  building it.
- **Research scores:** the `research-1` rules (limits and minimum history in
  `SCORING.md`) are fixed and were approved as a starting point; revisit them after
  real use. Not built: dividend growth and opportunity cost scores (they need
  five-year dividends and peers) and filling the workbench from the `scores` block.
  The lookup sends the ticker symbol only, so a symbol listed on several exchanges can
  return another market's currency and the pages do not convert it; decide whether
  to pass the exchange or currency.
- **Portfolio policy:** confirm default review thresholds, replacement minimum
  score gap, and concentration cap before making recommendations user-facing.
- **Data cadence:** confirm how often CSV/Flex imports and historical snapshots
  should be refreshed; no automatic or live sync is enabled.
- **Approval retention:** confirm audit retention and who may review an account's
  approval history. The current schema scopes access to the approved portfolio
  owner and leaves the audit log append-only for that user.
- **External order execution:** not implemented. Any future integration must be
  disabled by default, require explicit human approval, and never execute in CI
  or tests.
- **Financial-data quality:** choose trusted sources and freshness requirements
  for dividend sustainability, earnings growth, analyst revisions, and target
  prices before relying on the scores.

## Resolved

- **Sell Score direction:** the sell score now counts its six healthier-is-higher
  inputs as 100 minus their score, so a higher sell score is a stronger case to sell
  and the advisor's `sell` at 65 or more follows from it. Rows saved before the
  change carry no `sell_score_direction` tag and used the earlier direction; review
  or reject any recommendation that is still open from before it. See `SCORING.md`.

# StockScanner v2.22.0

Stable release · 23/Oct/2026

This release introduces an additive Portfolio Intelligence Platform (PIP)
Python layer for offline portfolio analysis and human-reviewed screening.

- Adds fixture-backed and local IBKR CSV/Flex-export normalization for accounts,
  positions, transactions, and dividends. It does not connect live to IBKR.
- Adds lifecycle, dead-money, opportunity-cost, dividend, growth, and
  forward-looking analysis helpers, plus configurable CPS and Sell Confidence
  scores with explicit missing-data reasons and reduced confidence.
- Preserves the specified Sell Score weights, which total 115%, and normalizes
  by their total. This remains an open question for the maintainer.
- Adds replacement-candidate ranking that excludes held symbols and supports
  portfolio concentration limits.
- Adds validated recommendation approval states and append-only audit records.
  There is no order-transmission implementation; recommendations are screening
  prompts and require explicit human review.
- Adds a separate Supabase PIP schema with owner/approved-user RLS, masked
  account identifiers, and append-only audit logs. Reuses `auth.users` and
  `public.user_access`; leaves existing scanner, portfolio imports, pages, RPCs,
  and Edge Functions unchanged.
- Documents PIP capabilities, rollout, security, and limitations in
  `docs/pip/`.

PIP is a library layer, not an enabled website feature. The GitHub Pages workflow
does not apply database migrations or establish a live IBKR integration. Review
`docs/pip/MIGRATION_PLAN.md` before applying the additive schema. No order
placement is available.

The deployment workflow tests the commit, publishes GitHub Pages, then creates
the matching stable GitHub Release from this file.

## Previous stable release: v2.21.0

Stable release · 23/Oct/2026

This release adds annualized return tracking and a recovery graph that compares
the portfolio objective with a stock's trailing one-year daily-return trend.

- The portfolio's default 7% objective is annualized and compounded across
  weekdays using 252 market days per year. Below-target holdings receive an
  evidence-aware review prompt; this is not an automatic order.
- Recovery scenarios show the percentage-point gap to the compounded target
  and estimate additional market days from the arithmetic mean of trailing
  one-year daily adjusted-close returns. Insufficient history or a trend that
  does not outpace the moving target is reported as unavailable.
- The recovery graph overlays the stock's one-year average-return path and the
  moving annual target while retaining stock-history and Equal-weight Top 20
  breakeven scenarios.
- Positions at or above cost remain in the portfolio but leave the recovery
  scenario display. Manual targets still take priority for target-hit reviews.
- Displayed clocks use 24-hour time; displayed dates use dd/mmm/yyyy.
- No database schema change is required.

The deployment workflow tests the commit, publishes GitHub Pages, then creates
the matching stable GitHub Release from this file.

## Previous stable release: v2.20.0

Stable release · 23/Oct/2026

This release makes the portfolio profit-review objective user-adjustable and
refreshes analysis from the latest data already available to the application.

- The portfolio target field defaults to 7% and accepts values from 0% to
  100%. Valid edits recalculate automatic targets and action reviews as typed.
- CSV rows with missing currency require an explicit three-letter currency;
  the import no longer silently assumes USD.
- Portfolio analysis and CSV-format explanations start collapsed behind info
  buttons and can be closed back to their headings.
- Manual targets remain higher priority than the return objective, scanner
  targets, resistance, or analyst target proxy.
- **Review again** reloads the portfolio and currently stored scanner and price
  data. It does not trigger a live quote request or start a new scan.
- Help, FAQ, release, and setup documentation describe these controls and their
  data-freshness limitations.
- No database schema change is required.

The deployment workflow tests the commit, publishes GitHub Pages, then creates
the matching stable GitHub Release from this file.

## Previous stable release: v2.19.0

Stable release · 02/Oct/2026

This release combines private portfolio Technical strength with resilient price
refreshes and administrator-visible recovery history for unsuccessful scans.

- The daily run analyses current portfolio symbols without adding portfolio-only
  stocks to discovery rankings, Top 20, Technical Analysis, or Analysts Rating.
- Successful scores and targets are stored in a backend-only Supabase table and
  returned only for holdings owned by the authenticated approved user.
- A failed symbol retains its last successful Technical strength and targets,
  marks them stale, and shows the earlier market date in amber.
- Portfolio enrichment and private signal-storage failures do not prevent the
  public NYSE report from completing.
- Price collection queries Yahoo Finance first, then Alpaca Basic/IEX and up to
  eight remaining Twelve Data gaps. One provider exception cannot stop the run.
- Failed daily histories and hourly quotes are recorded separately and retried
  on the next market date. The administrator can inspect their dated history.
- Last-available prices remain usable and appear in amber when older than
  75 minutes or retained after a failed refresh.
- Daily scans run at 07:30 New York time with a 09:00 fallback. Price collection
  retains the established logical hourly and close slots with frequent retries.
- Recovery timelines, searchable dropdowns, purchase-price comparisons, New
  York clocks, and dd/mmm/yyyy dates remain available.

The deployment workflow runs Python and JavaScript tests before publishing and
creates the matching stable GitHub Release from the successful `main` commit.

## Previous stable release: v2.17.0

Stable release · 05/Sep/2026

This release adds purchase-price comparisons to the scanner pages and searchable
dropdowns throughout the table filters.

- Technical Analysis and Analysts Rating show **Bought @ $price** for owned
  stocks in Top 20 and All Results. Multiple portfolio lots use the
  quantity-weighted average buy price. Portfolio holdings take precedence over
  a duplicate My Bought List entry; all purchase reads remain scoped to the
  approved user and include pagination.
- Technical Targets 1, 2 and 3, and analyst Support Low/High and Resistance
  Low/High, display percentage returns from the purchase price beneath each
  price level. Profit is green, loss red, and breakeven or unavailable grey.
  The existing arrows continue to compare levels with the market price.
  Labels remain present after sorting and price refreshes.
- Table filters contain populated, searchable dropdowns with unique sorted
  symbols and **All stocks**. Typing narrows the choices, with prefix matches
  first. Click a choice or use the arrow keys and Enter; clear the field to reset
  or use Escape to cancel an unfinished search. User management offers the same
  interaction for email addresses.
- Choices follow the active scanner table, dashboard category or portfolio
  scope. Selecting a stock on Hourly and Daily Stock Prices also opens its chart.
  Shared report code provides the same filters in newly generated reports and
  archived report displays.
- README, setup documentation and Help & FAQ describe the new controls and
  price comparisons. The previous portfolio layout, recovery estimates,
  no-guarantee disclaimer and New York date/time formatting remain available.

## Validation and deployment

The deployment workflow runs the Python suite and all JavaScript test files
before publishing. Local browser fixtures cover purchase-price weighting and
account filters, pagination, loss/profit labels, sorting, price refreshes,
searchable options, keyboard and mouse selection, clearing, unavailable matches,
scope changes and mobile layout. Fixture checks do not constitute a test of
every user's live portfolio.

GitHub Pages publishes the release, including formatting of archived report
displays. A successful push deployment creates the matching stable GitHub
Release from that source commit. Existing release tags are preserved.
No database migration is required for this release. Reverting the release
changes on main and redeploying restores the preceding application behavior.

## Price and recovery assumptions

Purchase-price comparisons exclude fees, taxes, dividends and currency
conversion. Missing prices, mixed currencies and short positions do not produce
a misleading average. Non-USD purchase prices retain their currency labels;
returns against USD report levels are unavailable.

Recovery means returning from the latest available quote to the recorded buy
price. The stock-history and Equal-weight Top 20 scenarios assume their
historical compound rates continue. They exclude fees, taxes, dividends and
currency conversion and do not change action-review decisions. Recovery may
happen earlier, later, or not at all. The graph displays up to five future years;
later calculated dates remain listed separately.

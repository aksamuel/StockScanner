# StockScanner v2.16.0

Stable release · 05/Sep/2026

This release brings the portfolio review changes together with consistent date
and time displays and a dedicated Help & FAQ page.

- Portfolio columns begin with Symbol, Action review, Recovery scenario / days
  held, and Profit / Loss %. Broker selection controls the analysis scope.
- Technical strength appears once inside Action review, with a score out of 100:
  Weak below 40 in red, Moderate from 40 through 70 in orange, and Strong above
  70 in green. Missing scores remain unavailable. Existing action rules are
  unchanged; a weak score alone is not an instruction to sell.
- Recovery timelines start at a grey Today dot, followed in date order by blue
  stock-history and orange Equal-weight Top 20 estimated recovery milestones.
  Both dates and calendar-day counts remain visible when calculable. Graphs
  retain the stock history, both growth scenarios and the buy-price target.
- Recovery dates carry an explicit no-guarantee disclaimer. Unavailable,
  non-positive-growth and beyond-graph-horizon scenarios remain explained.
- Displayed clocks use New York time, 24-hour HH:mm, without seconds and with
  EST/EDT. Dates use dd/mmm/yyyy. Report generation, existing deployed report
  displays, charts and new Excel exports use the shared formatting rules.
  Stored timestamp precision, machine-readable dates and unique paths remain
  intact.
- The README, setup guide, inline portfolio help and new in-app Help & FAQ
  explain the final layout and assumptions. The shared menu and generated
  report help links open the new help page. Broker CSV uploads, including native
  IBKR exports, remain supported after removal of direct IBKR downloading.

## Validation and deployment

The deployment workflow runs the Python suite and JavaScript date, recovery
model and history-handler checks before publishing. Local browser fixtures
cover portfolio layout, strength boundaries, recovery graphs and timelines,
missing history, mobile layout and New York clocks in multiple browser zones.
These fixture checks do not constitute a test of every user's live portfolio.

GitHub Pages publishes the release, including formatting of archived report
displays. A successful push deployment creates the matching stable GitHub
Release from that source commit. Existing release tags are preserved.
No database migration is required for this release. Reverting the release
changes on main and redeploying restores the preceding application behavior.

## Recovery assumptions

Recovery means returning from the latest available quote to the recorded buy
price. The stock-history and Equal-weight Top 20 scenarios assume their
historical compound rates continue. They exclude fees, taxes, dividends and
currency conversion and do not change action-review decisions. Recovery may
happen earlier, later, or not at all. The graph displays up to five future years;
later calculated dates remain listed separately.

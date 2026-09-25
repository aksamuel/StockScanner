# StockScanner v2.17.0

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

# Portfolio Intelligence Platform FAQ

## Is PIP part of the existing scanner workflow?

PIP is an additive Python package under `stockscanner/pip/`. It does not change
scanner discovery, rankings, reports, or the existing portfolio pages. The
deployed website does not currently provide a PIP dashboard or automatically run
PIP analysis.

## What is included?

The package provides fixture/CSV portfolio normalization, lifecycle and
productivity analysis, dividend/growth/forward-looking helpers, CPS and Sell
Confidence scores, replacement ranking, recommendation helpers, and explicit
approval-state tracking. It can also load Yahoo historical prices and available
analyst consensus through the existing scanner helpers, and read the shared
Yahoo/Alpaca/Twelve Data price snapshot. The Supabase migration and adapters
provide an optional owner-scoped persistence layer.

## Which research data is currently available?

For an imported holding, PIP can show the latest shared price snapshot, Yahoo
historical price return, relative performance to SPY, analyst consensus/target
data when Yahoo provides it, and dividend events per share. It does not treat
raw returns as 0–100 component scores or per-share dividend events as portfolio
cash income. The shared snapshot can report Yahoo, Alpaca, or Twelve Data as the
latest-quote source; Alpaca may also supply a previous close. PIP reads this
shared snapshot instead of calling Alpaca or Twelve Data directly. Those current
adapters provide price data, not analyst consensus, earnings/revenue growth, or
historical estimate revisions, so unavailable factors remain missing and reduce
score confidence. The research request sends only the ticker symbol to Yahoo;
portfolio details and Supabase tokens stay out of provider requests.

## Does sync connect to my IBKR account?

No. The current sync is read-only and accepts local CSV/Flex export files or
recorded fixtures. There is no live IBKR connection and no network call in the
sync tests. Account identifiers are masked before they enter normalized PIP
records. Never place a broker token or unmasked account identifier in a fixture,
log, audit event, or source-controlled file.

## Will PIP place a trade or transmit an order?

No. Recommendations are screening prompts, not financial advice. Approval
transitions record a human decision; `mark_submitted()` only records that an
action happened outside PIP. There is no IBKR order transmitter.

## Can any signed-in user read PIP data?

No. The additive schema enables RLS on every PIP table. Policies require the
authenticated portfolio owner to have approved status in the existing
`public.user_access` model. Audit rows are append-only for authenticated users.
The migration is not automatically applied by the GitHub Pages deployment.

## How do the scores handle missing data?

Each available component is clamped to 0–100, and missing/invalid components are
excluded from the weighted mean. The result reports missing-input reasons and
confidence based on the available weight. An entirely missing score is `None`
with zero confidence rather than a misleading zero.

## Why do Sell Score weights total 115?

That total is in the supplied specification. PIP preserves the specified
component weights and divides by their total, so the output remains on the
0–100 scale. See [Scoring](SCORING.md) for the explicitly marked maintainer
question and the single place to change the weights.

## How can I try the code?

Install the repository's declared dependencies, then run the fixture-backed PIP
tests:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/pip tests/test_pip_integration.py
```

The complete Python and browser-independent JavaScript test commands are listed
in [setup and operations](../../README_SETUP.md#run-tests). Do not point fixture
tests at a live brokerage or a production database.

## What must happen before production use?

Review the open maintainer questions, decide the score and concentration policy,
apply and verify the PIP migration in the intended Supabase project, and add a
reviewed server-side integration for any real-data persistence. Live IBKR
retrieval and order execution are out of scope. GitHub Pages deployment alone
does not apply database migrations or enable PIP.

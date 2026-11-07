# Portfolio Intelligence Platform FAQ

## Is PIP part of the existing scanner workflow?

PIP is an additive Python package under `stockscanner/pip/` with a FastAPI service
and a Portfolio Intelligence workbench page. It does not change scanner discovery,
rankings, reports, or the existing portfolio pages. Nothing runs automatically:
analysis and portfolio review run only when you press their buttons, and the
workbench works only while it is connected to a deployed PIP API.

## What is included?

The package provides fixture/CSV portfolio normalization, lifecycle and
productivity analysis, a required-annual-return hurdle (7% by default), a
read-only portfolio review that ranks holdings against it,
dividend/growth/forward-looking helpers, CPS and Sell
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
adapters provide price data only. Yahoo Finance can also provide earnings and
revenue growth percentages and raw EPS revision counts for some symbols; PIP
displays the revision counts without converting them into a score. Missing
provider fields remain unavailable and reduce score confidence. The research
request sends only the ticker symbol to Yahoo; portfolio details and Supabase
tokens stay out of provider requests.

## Does sync connect to my IBKR account?

The API supports optional read-only IBKR Flex Web Service sync. It is available
only after applying the PIP migrations, deploying the `pip-ibkr-flex` Supabase
Edge Function, and configuring the same server-only internal key in the API and
the function. Each approved user can save multiple named Flex connections for
their own portfolios; credentials are kept in Supabase Vault and are never
returned to the browser. Configure the Flex Query to return XML. Local CSV
imports remain available. Each sync requires confirmation that the query
includes all stock positions for each included account without symbol filters;
it replaces only those accounts' earlier Flex positions. CSV/manual holdings
and transaction/dividend history are retained. Avoid importing the same holdings
from both CSV and Flex because both copies are counted. Account identifiers are masked before persistence;
never place broker tokens or unmasked account identifiers in fixtures, logs,
audit events, or source-controlled files.

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

## Will PIP flag a holding that is not earning my required return, such as 7% per year?

Yes, as a prompt for human review. Each analysis compares the holding with the
annual return you require (7% by default, 0%–100%) measured from its own entry
date. A holding is judged below the hurdle only after a year of holding and once
dividends received are known (enter 0 if none); until then the status reads
"cannot be judged yet". Dead money combines the hurdle with a weak CPS, a
non-positive return, high opportunity cost, or an analyst target upside below the
hurdle, and reports insufficient data instead of guessing. See
[Scoring](SCORING.md#return-hurdle-and-dead-money) for the exact rules.

## Can PIP say when the holding or a replacement will reach 7%?

Not as a forecast. PIP shows the annual return a holding would need over 1, 3 and
5 years to catch up with the hurdle path. If you enter an assumed annual return
for the holding or a replacement, it also shows the arithmetic result: years for
the holding to catch up, or months for the replacement to earn the hurdle gain.
Those figures are scenarios from your assumptions, not predictions or guarantees.
PIP ranks the replacement symbols and scores you supply; it does not search the
market for candidates.

## Will downloading or syncing my portfolio automatically analyze every stock and suggest replacements?

No. Importing a CSV or syncing Flex only saves positions. Nothing is analyzed until
you press a button in the workbench. **Review portfolio** ranks the open holdings
you have kept for at least a year that trail your required return (7% by default),
furthest behind first, then attaches dead-money and replacement advice to the five
furthest behind (you can choose 1–20). The review is read-only: it saves nothing,
changes no recommendation, and places no order. Holdings kept under a year, holdings
already on or ahead of the hurdle, holdings in more than one currency, and holdings
missing a cost basis or entry date are counted or listed but not ranked.

## Why does the review withhold a verdict or say replacements were not compared?

The review does not know your dividends, so its returns are price-only and it will
not call a holding "not dead money" on that basis. It compares replacements only
with candidate scores you type in, written as `AAA:82, BBB:90`, and only against the
holding's saved CPS. A candidate with a blank score such as `AAA:` is rejected
rather than read as 0. To save a CPS and get a confirmed verdict, analyze that
holding and enter dividends received. See [Scoring](SCORING.md#portfolio-review)
for the exact rules.

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

Apply and verify the PIP migrations, configure approved-user access, deploy the
API and `pip-ibkr-flex` function, set their matching internal key, and verify a
read-only sync using a test Flex Query. GitHub Pages deployment alone does not
apply database migrations or configure server secrets. Order execution remains
out of scope; approval records a human decision only.

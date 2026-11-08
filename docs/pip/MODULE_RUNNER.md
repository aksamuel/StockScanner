# PIP Module Runner

`pip-modules.html` is a signed-in page that shows the holdings saved by a CSV
import or a Flex sync and runs one analysis module for one holding each time you
press a button. It uses the same PIP API as the
[workbench](../portfolio-intelligence-pip.md), and nothing it does changes saved
data.

## What it never does

- **Place, approve or transmit an order.** It has no broker connection.
- **Save anything.** A module run answers with `"saved": false`, so no score,
  recommendation, snapshot or audit event is written. To save a score and propose a
  recommendation, analyze the holding in the workbench.
- **Fetch live prices.** Values are as of the last import or sync.
- **Convert currencies.** Totals are per currency and are never added together.
- **Fall back to demo data.** If the API cannot be reached or is out of date, the
  page says so and shows nothing.

## Use it

1. Open **Menu → Portfolio intelligence → PIP module runner** and sign in with an
   approved account.
2. Check the API address (it defaults to `https://stockscanner-pip-api.onrender.com`)
   and press **Connect**. The first request after the service has been idle can take
   about a minute on Render's free plan, and the page waits up to 90 seconds.
3. Unless you chose a portfolio earlier, the page shows the newest portfolio that has
   holdings. If newer portfolios are empty it says how many it skipped. Choose
   another portfolio from the list; the choice is remembered in this browser.
4. Read the holdings table (one row per symbol, with a per-currency total and any
   flags) and filter it by symbol if the list is long.
5. Press **Run modules** on a holding, fill in any inputs you have, then press a
   module button. Each press runs that module once for that holding and shows the
   result below the buttons.

Only the API address and the chosen portfolio are stored in the browser. The
sign-in token is read when a request is sent and is never stored by this page.

## Connecting to another API address

An alternative deployment must verify the same Supabase project's sign-in tokens
and list this page's origin in `PIP_CORS_ORIGINS`; otherwise the browser blocks the
request and the page names the origin to allow.

The page sends your sign-in token to the address you enter, so connect only to a
service you run or trust. For any address other than the default or `localhost`
it shows a warning and asks you to press **Connect** a second time. Plain `http` is
accepted only for `localhost` and `127.0.0.1`.

Before it sends the token, the page calls the public `/healthz` route and refuses a
service that does not report `"service": "pip"`, `"positions_list": 1` and
`"module_runner": 1`. An API deployed before this feature is therefore reported as
out of date instead of failing part-way.

## Routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Public health check and feature markers; no user data |
| GET | `/api/pip/portfolios` | The caller's portfolios, newest first |
| GET | `/api/pip/portfolios/{id}/positions` | Per-symbol overview of saved positions; read-only |
| POST | `/api/pip/portfolios/{id}/modules/{module}` | Run one module for one holding; read-only |

These are the only requests the page makes. Both new routes require the caller's
sign-in token and approved access, read through the caller's row-level security
and the same owner check as every other PIP route, and write nothing.

The positions response holds `as_of`, `lots`, `holdings`, `totals`, `flags`,
`truncated` and `notes`. A holding carries its symbol, currency, quantity, lot
count, cost basis, market value, price return (percent), entry date and days held.
Any value the import did not provide is `null` and is shown as "not available"
rather than guessed. Holdings are flagged when they mix currencies (or have none
recorded), are short, or miss a cost basis, entry date or market value. Returns
are price-only because imported positions do not include dividends. At most 10,000
positions are read; beyond that the response is marked `truncated` and the page
says some holdings are not shown.

The module request body is the single-holding analysis input (`symbol` plus the
optional `position`, `scores`, `hurdle`, `growth`, `forward`, `dividends` and
`peer_scores` sections) without a portfolio id. Unknown fields are rejected. The
page sends only the fields you fill in, plus the required annual return, which is
prefilled with 7. The response is `module`, `symbol`, `currency`, `saved` and
`result`.

## Modules

| Module | Page label | What it needs |
| --- | --- | --- |
| `lifecycle` | Position lifecycle | The saved lots; share price, cost basis, entry date and dividends received fill gaps |
| `hurdle` | Return hurdle | The saved lots and the required annual return; dividends received give a total return |
| `dead_money` | Dead money | Position values plus score or outlook inputs |
| `dividends` | Dividend analysis | Saved dividend history; share price, payout ratio, growth rate and consistency add detail |
| `growth` | Growth analysis | Earnings growth or revenue growth |
| `forward_looking` | Forward-looking analysis | Target upside or a forward revisions score |
| `opportunity_cost` | Opportunity cost | Replacement candidates and at least one capital productivity input |
| `cps` | Capital productivity score | Whichever of its five score inputs are available |
| `sell_score` | Sell confidence score | Whichever of its seven score inputs are available |
| `replacements` | Replacement candidates | Replacement candidates and at least one capital productivity input |
| `sell_advisor` | Sell advisor | The sell score, capital productivity score and replacement candidates |

Replacement candidates are written `AAA:82, BBB:90` and use the same 0–100 scale as
the holding's capital productivity score. A candidate is listed only when it scores
above that holding's score and is not already held in the portfolio.

## Reading a result

- **Input confidence** is how much of the needed data was available, from 0 to 1.
  It does not measure how strong the signal is, so a low score can have high
  confidence.
- **To get a fuller answer** lists the inputs that would complete a partial result.
- **Opportunity cost** shows a score-based estimate (half the score gap, in score
  points). It is not a return forecast or an amount of money.
- **Dividend income** covers the trailing 365 days only.
- **Forward-looking analysis** is an indicator built from the inputs you supplied,
  not a forecast.
- **Sell advisor** returns `watch`, `sell`, `partial-sell` or `hold`, checked in
  this order: input confidence below 0.5 or no sell score gives `watch`; a sell
  score of 65 or more gives `sell`; a score of 50 or more with an opportunity-cost
  score of 60 or more gives `partial-sell`; a capital productivity score under 45
  gives `watch`; anything else gives `hold`. It is advice for a person to review,
  and the approval workflow is a separate, explicit step.

## Why a verdict can be withheld

- **No dividends received entered.** The return stays price-only, so the hurdle
  result stays `unavailable` unless the price return already meets the path, and
  dead money cannot be called "not dead money".
- **No market value.** The import did not provide a market value for at least one
  lot, so the value and return are withheld and the holding is flagged.
- **No capital productivity inputs.** Replacements, opportunity cost and the sell
  advisor compare against the holding's capital productivity score, which needs at
  least one score input. Type one in, or analyze the holding in the workbench to
  save scores.

## Open question: sell-score direction

Most sell-score inputs rise as a holding gets healthier (total return, relative
performance, revisions, dividend quality, technical health, earnings growth); only
opportunity cost rises with a stronger case to sell. The Sell advisor nevertheless
reads a sell score of 65 or more as `sell`. That behaviour predates the module
runner and is unchanged, and it is pinned by existing tests, so the page shows a
caveat under the sell-score and sell-advisor results. See
[Open questions](OPEN_QUESTIONS.md) and [Scoring](SCORING.md).

## Tests

```sh
python -m pytest -q tests/pip/test_holdings.py tests/pip/test_holdings_modules_api.py tests/pip/test_module_page_contract.py
node --test tests/pip-shared.test.mjs tests/pip-modules-core.test.mjs tests/pip-modules.test.mjs
```

The contract test reads the page's module and field tables and checks them against
the API models, so changing a module name, a field or a limit on one side without the
other fails the build. The page tests run against a fake DOM and fake `fetch`, and
use placeholder symbols only.

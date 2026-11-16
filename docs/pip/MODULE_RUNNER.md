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
- **Fetch prices or market data on its own.** The holdings table shows values as of
  the last import or sync. The one market lookup is the **Load research** button,
  which runs only when you press it and asks about one ticker (see
  [Loading research](#loading-research)).
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
5. Press **Run modules** on a holding. Optionally press **Load research** to fill
   the inputs that Yahoo data can supply, fill in any others you have, then press a
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
| POST | `/api/pip/portfolios/{id}/research` | Look up Yahoo research for one saved holding's ticker; stores nothing |

These are the only requests the page makes. The routes under `/api/pip` require the
caller's sign-in token and approved access, use the same owner check as every other
PIP route, read saved data through the caller's row-level security, and write
nothing.

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

## Loading research

**Load research**, under the module buttons, fills the inputs that Yahoo data can
supply so you do not have to look them up. It does not run a module and saves
nothing.

The page asks the API to look up the holding's ticker symbol at Yahoo. Only the
symbol goes to data providers; quantities, cost, account details and your sign-in
token do not. The API returns raw facts and four 0–100 scores calculated by the fixed
rules in [Scoring](SCORING.md#research-scores-from-yahoo-data), and the page puts the
usable values in the boxes. It can fill up to eight:

| Input | Comes from |
| --- | --- |
| Current share price | The latest shared price snapshot |
| Total shareholder return score | The one-year adjusted-close return |
| Relative performance score | That return minus SPY's, over the dates both have |
| Technical health score | The last close against its 200-close and 50-close averages and its 365-day high |
| Forward revisions score | The 30-day EPS estimate revisions |
| Earnings growth, Revenue growth | Yahoo's growth percentages |
| Target upside | The analyst target price |

Opportunity cost, the dividend inputs and replacement candidates are never filled;
they depend on your portfolio and your peers.

- **Nothing is guessed.** A box is filled only when Yahoo gave a usable number that
  fits the field. When it did not, for example with under 330 days of history, the
  box stays empty and the notes under the button say why. If the API predates the
  scores, the notes say so and the four score boxes stay empty.
- **Every value is explained.** The status line says how many of the eight inputs
  were filled and the date of the data. The notes give the figures behind each value,
  such as the return and the days it covers, or the revision counts.
- **It overwrites.** A box research can fill is replaced, whatever it held; a box it
  cannot fill keeps what you typed. Loading again first empties the boxes that still
  hold the previous load's text, so a value Yahoo no longer gives does not linger.
  Every loaded value can be edited, and choosing another holding clears them.
- **Results say where inputs came from.** After a module runs, the result shows
  **Inputs from Yahoo research** with the data date, the score rules version and the
  loaded values still in the boxes. Values you edited are your own and are not
  listed, and a module uses only the inputs it needs.
- **Errors are shown, not hidden.** If Yahoo has nothing usable for the symbol, or the
  API cannot be reached, the page shows the error and fills nothing. The API also
  checks that the symbol is saved in the selected portfolio.
- **Check the listing.** The lookup uses the ticker symbol only. When one ticker
  trades on several exchanges, Yahoo's listing may be a different market or currency
  from your holding, and the page does not convert currencies. Check the price and
  the notes before relying on a result.

## Reading a result

- **Input confidence** is how much of the needed data was available, from 0 to 1.
  It does not measure how strong the signal is, so a low score can have high
  confidence.
- **To get a fuller answer** lists the inputs that would complete a partial result.
- **Opportunity cost** shows a score-based estimate (half the score gap, in score
  points). It is not a return forecast or an amount of money.
- **Dividend income** covers the trailing 365 days only.
- **Earnings growth input.** When no earnings growth score is supplied or saved,
  the capital productivity and sell scores use the growth analysis score. If that
  score came from revenue growth (alone or blended with earnings growth), the
  result carries a note saying so. The growth result itself lists which growth
  data it used.
- **Forward-looking analysis** is an indicator built from the inputs you supplied,
  not a forecast.
- **Sell confidence score** runs from 0 to 100, and a higher score is a stronger
  case to sell. Six of its inputs rise as a holding gets healthier, so each counts as
  100 minus its score: the values listed under the result are those flipped values,
  not the ones you typed. Opportunity cost counts as entered. The result names the
  inputs that were flipped.
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
  lot, so the value and return are withheld and the holding is flagged. The sync or
  import that saved the positions shows a count-only warning for this, so the cause
  is visible before you open a module (see the Flex runbook for the fields to add).
- **No capital productivity inputs.** Replacements, opportunity cost and the sell
  advisor compare against the holding's capital productivity score, which needs at
  least one score input. Type one in, or analyze the holding in the workbench to
  save scores.

## Sell-score direction

The sell score counts total return, relative performance, revisions, dividend
quality, technical health and earnings growth as 100 minus their score, so a higher
sell score always means a stronger case to sell, and the advisor's `sell` (65 or
more) follows from it. See [Scoring](SCORING.md#direction-a-higher-sell-score-is-a-stronger-case-to-sell).

The API tags sell-score and sell-advisor results with `sell_score_direction`. When a
result lacks the tag, for example because the API has not been updated since the
change, the page says it may use the earlier direction and should be treated as
unverified. Recommendations saved before the change carry no tag either; review or
reject any that are still open.

## Tests

```sh
python -m pytest -q tests/pip/test_holdings.py tests/pip/test_holdings_modules_api.py tests/pip/test_module_page_contract.py tests/pip/test_research.py tests/pip/test_research_scores.py
node --test tests/pip-shared.test.mjs tests/pip-modules-core.test.mjs tests/pip-modules.test.mjs
```

The contract test reads the page's module and field tables and checks them against
the API models, so changing a module name, a field or a limit on one side without the
other fails the build. It also resolves every path in the page's research table
against a real research answer built by the API code, so the page cannot read a value
the API no longer returns. The page tests run against a fake DOM and fake `fetch`, and
use placeholder symbols only.

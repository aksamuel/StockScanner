# Portfolio Intelligence Platform (PIP)

This document describes the implemented PIP analytics package, authenticated API,
Supabase persistence, and human review workflow.

## Objective
Add a modular portfolio intelligence layer to StockScanner without disturbing the current stock scanner discovery, reporting, and dashboard workflows.

## Scope
The PIP modules are additive and focused on:
- IBKR portfolio synchronization
- position lifecycle analysis
- score calculation and ranking
- dead money detection
- opportunity cost evaluation
- dividend and growth analysis
- replacement candidate generation
- sell recommendation advice
- approval workflow and audit trail

## Architectural direction
The existing StockScanner repository already has the correct core ingredients:
- data persistence via Supabase
- user and portfolio concepts
- market data ingestion
- report generation and dashboard conventions
- AI-assisted analysis and evaluation patterns

The PIP layer is an adjacent service rather than a rewrite of the core scanner.

## Recommended package layout
- `stockscanner/pip/__init__.py`
- `stockscanner/pip/models.py`
- `stockscanner/pip/scoring.py`
- `stockscanner/pip/ibkr_sync.py`
- `stockscanner/pip/replacement_engine.py`
- `stockscanner/pip/sell_advisor.py`
- `stockscanner/pip/approval_workflow.py`

## Planned module responsibilities
### 1. IBKR Portfolio Sync
Load IBKR positions, transactions, and account metadata into normalized forms suitable for scoring and analysis.

### 2. Position Lifecycle Analysis
Track entry dates, holding duration, cost basis, market value and age-related performance drift.

### 3. Dead Money Detector
Identify holdings with weak score quality, low expected upside, or persistent drag on portfolio productivity.

### 4. Opportunity Cost Engine
Compare current positions to alternative candidates and quantify the cost of keeping weak holdings.

### 5. Dividend Analysis
Evaluate dividend consistency, payout quality and dividend growth for the holding.

### 6. Growth Analysis
Measure earnings growth and growth quality relative to expectations and forward-looking fundamentals.

### 7. Forward Looking Analysis
Use expected future catalysts to inform confidence bands and risk-adjusted decision support.

### 8. Capital Productivity Score (CPS)
Formula:
- 40% TSR
- 20% Relative Performance vs SPY
- 15% Dividend Growth
- 15% Earnings Growth
- 10% Analyst Revisions

### 9. Sell Confidence Score
Formula:
- 20% TSR
- 20% Relative Performance
- 20% Revisions
- 15% Dividend Quality
- 15% Technical Health
- 10% Earnings Growth
- 15% Opportunity Cost

### 10. Replacement Candidate Engine
Generate replacement options that may produce stronger score quality and better capital efficiency.

### 11. Sell Advisor
Convert score outputs into clear recommendations such as `sell`, `watch`, or `hold` with supporting rationale.

### 12. Order Approval Workflow
Require review and auditability before a recommendation becomes an actionable decision.

## Supabase tables
The migration in `supabase/migrations/20261023_pip_core_schema.sql` creates:
- users
- portfolios
- ibkr_accounts
- positions
- transactions
- dividends
- daily_snapshots
- analyst_signals
- stock_scores
- sell_recommendations
- replacement_candidates
- audit_logs

`auth.users` is the identity table; `pip_profiles` contains only optional profile
metadata. The API uses each request's verified Supabase access token for all
PostgREST operations. It does not use or accept a service-role key.

## Deploying the API

Install the project dependencies, apply `20261023_pip_core_schema.sql` followed by
`20261024_pip_approval_rpc.sql`, then configure the API host with:

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `PIP_CORS_ORIGINS`, a comma-separated exact allowlist of browser origins
- Optional `PIP_API_HOST` and `PIP_API_PORT` (defaults `127.0.0.1:8000`)

Start the service with `stockscanner-pip-api` (or
`python -m uvicorn stockscanner.pip.api:app`). Put it behind HTTPS before
connecting a browser. Do not configure a service-role key. The API verifies the
Supabase token, requires `user_access.status = 'approved'`, and relies on owner
RLS for portfolio reads and writes. The approval RPC is narrowly scoped to one
authenticated owner's state transition and appends its audit entry atomically.

### Render test deployment

The root `render.yaml` defines a Render Blueprint for the API only. It pins the
native runtime to Python 3.11, installs the package, starts Uvicorn on Render's
assigned port, and checks `/healthz`. It uses Render's Free plan for testing;
free services can sleep after inactivity and are not suitable for production.
Portfolio data remains in Supabase, not on Render's ephemeral filesystem.

To create the service, push this branch, sign in to Render, and create a
Blueprint from `aksamuel/StockScanner` on the branch containing `render.yaml`.
When prompted, enter `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` as Render
environment values. Use the Supabase project URL and publishable key only;
never use a service-role or secret key. The Blueprint restricts browser access
to the configured GitHub Pages origin and the local workbench on port 8001.
Adjust `PIP_CORS_ORIGINS` in Render if the workbench is hosted at another exact
origin.

After the service is live, open its `https://<service>.onrender.com/healthz`
URL and confirm it returns `{"status":"ok","service":"pip"}`. Copy the service's
base HTTPS URL into the Portfolio Intelligence page's API URL field and
connect. The Blueprint does not publish the static workbench; use the local
workbench or publish the updated page separately. A free service's first
request after sleeping can take about a minute to wake it.

The static Portfolio Intelligence page connects to a configured API URL, keeps
that URL in local browser storage, and never stores the Supabase access token.
The user explicitly imports a CSV/Flex export and explicitly submits analysis.
Imports are limited to 1 MB and 1,000 CSV rows. The page can list portfolios,
create a portfolio, import normalized positions/transactions/dividends, run
analysis for an imported holding, and persist human approval transitions. Its
optional analysis inputs cover position overrides, dividend and growth metrics,
analyst targets/revisions, and candidate symbols with 0–100 scores; blank
position values reuse imported records where possible.

The authenticated `POST /api/pip/portfolios/{id}/research` route uses the
existing Yahoo historical-price and analyst-consensus helpers and reads the
latest shared `price_snapshots` row. That snapshot is produced by the existing
Yahoo-first price collection with Alpaca and Twelve Data fallbacks. The request
sends only the imported holding's symbol to Yahoo; account identifiers,
quantities, cost basis, user IDs, and Supabase tokens are not sent to market
data providers. The browser displays raw historical price return, SPY-relative
performance, available analyst consensus/target information, and Yahoo
per-share dividend history. It fills the available current-price and target
inputs, but does not convert raw returns into component scores or treat
per-share dividend events as portfolio cash income.

The current provider adapters do not expose earnings/revenue growth or analyst
estimate revision history to PIP. Those fields remain missing, lowering score
confidence. Raw returns are evidence only until a documented 0–100 mapping is
approved. Provider/API keys remain in the existing server-side price workflow;
the PIP browser never receives them.

API routes:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Service health (no user data) |
| GET, POST | `/api/pip/portfolios` | List or create caller-owned portfolios |
| POST | `/api/pip/portfolios/{id}/sync/csv` | Import a CSV/Flex export |
| POST | `/api/pip/portfolios/{id}/research` | Load available research for an imported holding |
| POST | `/api/pip/analysis` | Run modules, persist scores and propose a recommendation |
| GET | `/api/pip/portfolios/{id}/recommendations` | List portfolio recommendations |
| GET | `/api/pip/recommendations/{id}/events` | Read the append-only audit history |
| POST | `/api/pip/recommendations/{id}/transitions` | Record a human workflow transition |

Analysis reuses imported position/dividend rows and saved analyst/score inputs
where available; other components remain explicitly missing until supplied.
Broker sync is CSV/Flex only, and no route submits an order.

## Decision quality guidance
The PIP layer helps by giving better evidence, not by guaranteeing a right decision. It is most useful when it answers:
- Why is this holding weak?
- What is the opportunity cost?
- What is the better alternative?
- How confident is the recommendation?
- Who reviewed and approved it?

## Recommended implementation sequence
1. Schema and normalization
2. IBKR sync and data ingestion
3. Position lifecycle
4. Analytics and score components
5. Candidate generation and recommendations
6. Approval workflow and audits
7. Tests and documentation

## Guardrails
- Do not modify the existing scanner logic in place.
- Treat an automated recommendation as advisory evidence, not certainty.
- Keep every recommendation tied to source data and audit records.
- Score calculations should be deterministic and versioned.
- Confidence measures available input coverage, not whether a score is strong.
- Replacement quality scores are compared to the current holding's CPS, not its
  distinct Sell Score.
- Dividend yield uses dated cash events from the trailing 365-day period; an
  undated sum is reported as unavailable rather than mislabeled as annual income.

# Catalyst Lab — Beta 1

Open `catalysts-beta.html` from the StockScanner navigation. Sign in with an approved account.

1. Enter a NYSE ticker and select **Check SEC filings**.
2. Select **Inspect**, then open the official filing and exhibits.
3. Choose your assessment category, enter a reason, confirm you read the source, and save.
4. Compare the private beta score with the existing technical indicators and trade-plan values.
5. Check earnings dates, quotes and portfolio exposure inside IBKR. No order submission is implemented.

## Scope and safeguards

- This is **on-demand research**, not an automated full-NYSE catalyst scan.
- SEC metadata categories never count as positive/negative evidence automatically.
- SEC foreign-issuer 6-K/20-F forms are included where the SEC maps the NYSE ticker.
- Up to 60 recent filings from 90 days, deduplicated by accession; older events are hidden.
- One cache row per symbol; cache TTL one hour. Failed source checks never replace valid cache.
- Positive/negative scores reflect the user's manual interpretation. They are not probabilities or validated trading signals.
- Points count once per category, capped −25/+25; filing and review must be within 30 days.
- Beta score uses 75% of the existing technical score plus the catalyst adjustment, clamped 0–100.
- Missing/stale evidence (>24h) or technical report (>4 calendar days) suppresses combined scores.
- Technical timestamps indicate report generation, not an exact exchange quote timestamp.
- Existing targets are fixed-percentage scanner objectives, not independently estimated fair values.
- Search is checked against the current NYSE database and SEC mapping. No arbitrary upstream URLs.
- Approved-user authentication is checked server-side on every request. The edge function performs custom JWT validation with `auth.getUser()`; gateway `verify_jwt=false` is intentional for publishable-key compatibility.
- Cache writes and global/user refresh throttles are backend-only; reviews require owner + approved-user RLS.
- All external text uses DOM text nodes, and SEC links are host/path validated.
- Reuters, company IR, TradingView, IBKR and FactSet are links only. No subscription entitlement or redistribution rights are assumed.
- No production scoring, existing price retention, scan schedules, or trading logic is changed.
- No new recurring job is enabled in Beta 1. Scheduled collection and outcome testing are later work.

## Deployment

Apply `sql/catalyst_beta.sql` once (remote migration `add_catalyst_research_beta`). Deploy `supabase/functions/catalyst-beta/` with custom auth enabled in the handler. The function uses the runtime's existing server keys; no key belongs in frontend code. Optional `SEC_USER_AGENT` can override the default application/contact identification.

Static files: `catalysts-beta.html`, `catalysts-beta.css`, `catalysts-beta.js`, `catalyst-model.mjs`; `auth.js` adds one menu entry. Existing Pages workflow publishes them.

## Verification

`node --test tests/*.test.mjs`

Local browser QA: serve root on localhost:8000 and run `node tools/test_catalyst_ui.cjs` with Playwright available. It uses explicitly mocked auth/evidence, but parses the real local technical report. Screenshots are test-only files under `/tmp`.

Live acceptance: approved login → CRH → source link → save personal review → reload. Pending/blocked user must receive 403. User A must not read or update User B's reviews. Source outages must remain errors, not empty successful scans.

## Rollback

Remove the beta navigation entry and static assets, then undeploy only `catalyst-beta`. Leave additive beta tables intact until review data has been exported and deletion approved. Production scanner has no dependency on the beta tables.

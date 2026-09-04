# StockScanner security policy

## Supported versions

| Version | Security support |
|---|---|
| `2.15.x` | Supported |
| `< 2.15` | Unsupported; upgrade to the current stable release |

The production baseline is maintained on `main` and pinned on the
`stable/v2.15.0` branch.

## Reporting a vulnerability

Do not publish credentials, personal information, exploit details, or an active
vulnerability in a public issue. Use GitHub's private vulnerability-reporting
form:

<https://github.com/aksamuel/StockScanner/security/advisories/new>

Include the affected page or component, steps to reproduce, expected behavior,
actual behavior, and impact. Never include a Supabase secret key, service-role
JWT, password, session token, or recovery link.

## Authentication and authorization

- Supabase Auth stores password hashes. StockScanner does not store passwords.
- New accounts require prior administrator permission through the Before User
  Created hook and `public.signup_allowlist`.
- Application access also requires an approved `public.user_access` row.
- The sole production administrator is `aaksamuel@zohomail.com`.
- Admin and user-management pages verify that exact email before loading data.
- Authorization data must use protected `app_metadata` or database records,
  never user-editable `user_metadata`.
- A blocked or deleted user's active sessions should be revoked when strict
  immediate termination is required; deleting a user alone does not instantly
  invalidate every already-issued access token.

## Database access

- RLS is enabled on exposed application tables.
- Personal exception, bought-selection, and imported-portfolio policies require
  `auth.uid() = user_id` and approved application access.
- Deleting an Auth user cascades deletion to their personal lists and imports.
- `public.nyse_tickers` is backend-only. `anon` and `authenticated` have no
  table privileges; `service_role` has the minimum required write access.
- The ticker replacement RPC uses `SECURITY INVOKER`, an empty `search_path`,
  and an explicit service-role-only `EXECUTE` grant.
- `public.price_snapshots` exposes read-only current prices to authenticated
  users and accepts writes only from backend automation.
- `database.html` relies on those grants and RLS policies: approved users see
  shared market status and only their own portfolio/list counts. The activity
  log is queried only for the named administrator.

Data API grants and RLS are separate controls: grants determine whether a role
can reach an object, while RLS determines which rows that role can access.

## API keys and secrets

- Browser code may contain only the Supabase publishable/anonymous key.
- IBKR Flex tokens and query IDs are Edge Function secrets and must never be
  exposed in HTML, JavaScript, CSV templates, logs, or repository files.
- `GITHUB_ACTIONS_TOKEN` is an Edge Function secret used only by the
  admin-verified `trigger-scanner` function. Restrict it to the StockScanner
  repository with Actions read/write permission; never expose it to browser
  code or GitHub Pages.
- `SUPABASE_SECRET_KEY` belongs only in the protected GitHub `github-pages`
  environment or an intentionally secured backend session.
- New `sb_secret_...` keys are sent through the `apikey` header. Legacy
  service-role JWTs may additionally require `Authorization: Bearer`.
- Never put secret keys in HTML, JavaScript bundles, screenshots, logs,
  documentation examples, commits, issues, or chat messages.
- Supabase platform logs require dashboard organization/project access. Never
  place a Supabase management token in the static GitHub Pages application.
- Rotate a key immediately if exposure is suspected, then update the GitHub
  environment secret and verify the affected workflow.

## Production hardening checklist

- Enable leaked-password protection in Supabase Auth.
- Configure a production SMTP provider for reliable invitations and recovery
  emails.
- Keep the Before User Created hook enabled.
- Keep Auth redirect URLs restricted to approved StockScanner URLs.
- Review Supabase Security and Performance Advisors after database changes.
- Keep GitHub environment deployment-branch restrictions enabled.
- Review dependency and code-scanning alerts before each stable release.
- Never treat a static GitHub Pages Auth guard as protection for confidential
  data; sensitive records must remain in Supabase behind grants and RLS.

## Relevant references

- [Supabase password security](https://supabase.com/docs/guides/auth/password-security)
- [Supabase Data API security](https://supabase.com/docs/guides/api/securing-your-api)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)

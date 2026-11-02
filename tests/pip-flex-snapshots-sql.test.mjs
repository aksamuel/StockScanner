import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import test from "node:test";

const pglitePrefix = process.env.PIP_PGLITE_PREFIX;

test("Flex snapshot migration preserves account isolation, history, atomicity, and ordering", {
  skip: pglitePrefix ? false : "Set PIP_PGLITE_PREFIX to an installation of @electric-sql/pglite.",
}, async () => {
  const require = createRequire(resolve(pglitePrefix, "package.json"));
  const { PGlite } = require("@electric-sql/pglite");
  const db = new PGlite();
  const user = "11111111-1111-4111-8111-111111111111";
  const otherUser = "22222222-2222-4222-8222-222222222222";
  const pendingUser = "33333333-3333-4333-8333-333333333333";
  const portfolio = "44444444-4444-4444-8444-444444444444";
  const otherPortfolio = "55555555-5555-4555-8555-555555555555";
  const pendingPortfolio = "66666666-6666-4666-8666-666666666666";
  const accountA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const accountB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const otherAccount = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const fingerprintA = "a".repeat(64);
  const fingerprintB = "b".repeat(64);
  const fingerprintOther = "c".repeat(64);
  const now = Date.now();
  const timestamp = (offset) => new Date(now + offset).toISOString();
  const day = (offset) => new Date(now + offset * 86_400_000).toISOString().slice(0, 10);
  const firstDate = day(-2);
  const newestDate = day(-1);
  const accountInput = (fingerprint, statementDate) => ({
    account_fingerprint: fingerprint,
    statement_date: statementDate,
  });
  const position = (account, fingerprint, sourceKey, quantity) => ({
    portfolio_id: portfolio,
    account_id: account,
    symbol: "AAPL",
    quantity,
    average_cost: 100,
    market_price: 120,
    market_value: 120 * Number(quantity),
    cost_basis: 100 * Number(quantity),
    currency: "USD",
    source_key: sourceKey,
    last_updated: timestamp(-90_000),
    metadata: { source: "ibkr_flex", account_fingerprint: fingerprint },
  });

  async function actAs(userId, role = "authenticated") {
    await db.exec("RESET ROLE");
    await db.query("SELECT set_config('request.jwt.claim.sub', $1, false)", [userId]);
    await db.exec(`SET ROLE ${role}`);
  }

  async function replace(portfolioId, accounts, positions, startedAt) {
    return db.query(
      "SELECT public.pip_replace_flex_positions($1::uuid, $2::jsonb, $3::jsonb, $4::timestamptz) AS saved",
      [portfolioId, JSON.stringify(accounts), JSON.stringify(positions), startedAt],
    );
  }

  async function rows() {
    return (await db.query(
      "SELECT id, source_key, quantity::text FROM public.positions ORDER BY source_key",
    )).rows;
  }

  try {
    await db.exec(`
      CREATE ROLE anon NOLOGIN;
      CREATE ROLE authenticated NOLOGIN;
      CREATE ROLE service_role NOLOGIN;
      ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
      ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role;
      CREATE SCHEMA auth;
      CREATE TABLE auth.users (id UUID PRIMARY KEY);
      CREATE FUNCTION auth.uid() RETURNS UUID LANGUAGE SQL STABLE
        AS $$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::UUID $$;
      CREATE TABLE public.user_access (user_id UUID NOT NULL, status TEXT NOT NULL);
      GRANT USAGE ON SCHEMA auth, public TO anon, authenticated;
      GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated;
      GRANT SELECT ON public.user_access TO authenticated;
    `);
    for (const migration of [
      "../supabase/migrations/20261023_pip_core_schema.sql",
      "../supabase/migrations/20261026000000_pip_account_fingerprints.sql",
      "../supabase/migrations/20261102000000_pip_flex_position_snapshots.sql",
    ]) {
      await db.exec(await readFile(new URL(migration, import.meta.url), "utf8"));
    }
    const privileges = (await db.query(`
      SELECT
        has_function_privilege('authenticated', 'public.pip_replace_flex_positions(uuid,jsonb,jsonb,timestamptz)', 'EXECUTE') AS authenticated,
        has_function_privilege('anon', 'public.pip_replace_flex_positions(uuid,jsonb,jsonb,timestamptz)', 'EXECUTE') AS anon,
        has_function_privilege('service_role', 'public.pip_replace_flex_positions(uuid,jsonb,jsonb,timestamptz)', 'EXECUTE') AS service_role
    `)).rows[0];
    assert.deepEqual(privileges, { authenticated: true, anon: false, service_role: false });
    const tablePrivileges = (await db.query(`
      SELECT
        has_table_privilege('authenticated', 'public.pip_flex_position_snapshots', 'SELECT') AS authenticated,
        has_table_privilege('anon', 'public.pip_flex_position_snapshots', 'SELECT') AS anon,
        has_table_privilege('service_role', 'public.pip_flex_position_snapshots', 'SELECT') AS service_role
    `)).rows[0];
    assert.deepEqual(tablePrivileges, { authenticated: true, anon: false, service_role: false });

    await db.query("INSERT INTO auth.users (id) VALUES ($1), ($2), ($3)", [user, otherUser, pendingUser]);
    await db.query(
      "INSERT INTO public.user_access (user_id, status) VALUES ($1, 'approved'), ($2, 'approved'), ($3, 'pending')",
      [user, otherUser, pendingUser],
    );
    await db.query(
      "INSERT INTO public.portfolios (id, user_id, name) VALUES ($1, $2, 'one'), ($3, $4, 'two'), ($5, $6, 'pending')",
      [portfolio, user, otherPortfolio, otherUser, pendingPortfolio, pendingUser],
    );
    await db.query(
      `INSERT INTO public.ibkr_accounts (id, portfolio_id, account_name, masked_account_id, account_fingerprint)
       VALUES ($1, $2, 'one', '***4567', $3), ($4, $2, 'two', '***4567', $5),
              ($6, $7, 'other', '***9999', $8)`,
      [accountA, portfolio, fingerprintA, accountB, fingerprintB, otherAccount, otherPortfolio, fingerprintOther],
    );
    async function seedPosition(portfolioId, account, key, symbol, quantity, metadata) {
      await db.query(
        `INSERT INTO public.positions (portfolio_id, account_id, source_key, symbol, quantity, metadata)
         VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
        [portfolioId, account, key, symbol, quantity, JSON.stringify(metadata)],
      );
    }
    await seedPosition(portfolio, accountA, "old-a", "AAPL", 5, {
      source: "ibkr_flex", account_fingerprint: fingerprintA,
    });
    await seedPosition(portfolio, null, "legacy-a", "MSFT", 2, {
      source: "ibkr_flex", account_fingerprint: fingerprintA,
    });
    await seedPosition(portfolio, accountA, "legacy-without-fingerprint", "MSFT", 1, {
      source: "ibkr_flex",
    });
    await seedPosition(portfolio, accountA, "csv-preserve", "AAPL", 3, { source: "ibkr" });
    await seedPosition(portfolio, accountB, "other-account", "AAPL", 4, {
      source: "ibkr_flex", account_fingerprint: fingerprintB,
    });
    await seedPosition(portfolio, accountA, "other-fingerprint", "MSFT", 1, {
      source: "ibkr_flex", account_fingerprint: fingerprintB,
    });
    await seedPosition(otherPortfolio, otherAccount, "other-user", "AAPL", 9, {
      source: "ibkr_flex", account_fingerprint: fingerprintOther,
    });
    await db.query(
      `INSERT INTO public.transactions (portfolio_id, symbol, transaction_type, trade_date, source_key)
       VALUES ($1, 'AAPL', 'buy', now(), 'history')`,
      [portfolio],
    );
    await db.query(
      "INSERT INTO public.dividends (portfolio_id, symbol, dividend_amount, source_key) VALUES ($1, 'AAPL', 1, 'history')",
      [portfolio],
    );

    await actAs(user);
    const accounts = [accountInput(fingerprintA, firstDate)];
    let result = await replace(portfolio, accounts, [position(accountA, fingerprintA, "new-a", 6)], timestamp(-90_000));
    assert.equal(result.rows[0].saved, 1);
    let saved = await rows();
    assert.deepEqual(saved.map((row) => row.source_key), [
      "csv-preserve", "new-a", "other-account", "other-fingerprint",
    ]);
    assert.equal(saved.find((row) => row.source_key === "new-a").quantity, "6");
    const originalId = saved.find((row) => row.source_key === "new-a").id;

    await assert.rejects(
      () => replace(portfolio, accounts, [position(accountA, fingerprintA, "csv-preserve", 6)], timestamp(-60_000)),
      (error) => error.code === "22023",
    );
    const invalidPosition = position(accountA, fingerprintA, "invalid", "not-a-number");
    invalidPosition.market_value = null;
    invalidPosition.cost_basis = null;
    await assert.rejects(
      () => replace(portfolio, accounts, [invalidPosition], timestamp(-60_000)),
      (error) => error.code === "22P02",
    );
    assert.deepEqual((await rows()).map((row) => row.source_key), [
      "csv-preserve", "new-a", "other-account", "other-fingerprint",
    ]);

    await replace(portfolio, accounts, [position(accountA, fingerprintA, "new-a", 7)], timestamp(-60_000));
    saved = await rows();
    assert.equal(saved.find((row) => row.source_key === "new-a").id, originalId);
    assert.equal(saved.find((row) => row.source_key === "new-a").quantity, "7");
    await assert.rejects(
      () => replace(portfolio, accounts, [position(accountA, fingerprintA, "new-a", 5)], timestamp(-90_000)),
      (error) => error.code === "PPS01",
    );
    await assert.rejects(
      () => replace(portfolio, [accountInput(fingerprintA, day(-3))], [], timestamp(-30_000)),
      (error) => error.code === "PPS01",
    );
    await replace(portfolio, [accountInput(fingerprintA, newestDate)], [], timestamp(-30_000));
    assert.deepEqual((await rows()).map((row) => row.source_key), [
      "csv-preserve", "other-account", "other-fingerprint",
    ]);
    await assert.rejects(
      () => replace(portfolio, accounts, [position(accountA, fingerprintA, "new-a", 5)], timestamp(-10_000)),
      (error) => error.code === "PPS01",
    );
    assert.equal((await db.query("SELECT count(*)::int AS n FROM public.transactions")).rows[0].n, 1);
    assert.equal((await db.query("SELECT count(*)::int AS n FROM public.dividends")).rows[0].n, 1);

    await actAs(otherUser);
    assert.deepEqual((await rows()).map((row) => row.source_key), ["other-user"]);
    await assert.rejects(
      () => replace(portfolio, accounts, [], timestamp(-10_000)),
      (error) => error.code === "42501",
    );
    await assert.rejects(
      () => replace(otherPortfolio, accounts, [], timestamp(-10_000)),
      (error) => error.code === "22023",
    );
    await assert.rejects(
      () => db.query(
        `INSERT INTO public.pip_flex_position_snapshots (portfolio_id, account_id, statement_date, sync_started_at)
         VALUES ($1, $2, $3, $4)`,
        [otherPortfolio, accountA, newestDate, timestamp(-10_000)],
      ),
      (error) => error.code === "42501",
    );
    await actAs(pendingUser);
    await assert.rejects(
      () => replace(pendingPortfolio, accounts, [], timestamp(-10_000)),
      (error) => error.code === "42501",
    );
    await actAs(user, "anon");
    await assert.rejects(
      () => replace(portfolio, accounts, [], timestamp(-10_000)),
      (error) => error.code === "42501",
    );
  } finally {
    await db.close();
  }
});

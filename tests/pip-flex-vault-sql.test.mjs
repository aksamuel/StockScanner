import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import test from "node:test";

const pglitePrefix = process.env.PIP_PGLITE_PREFIX;

test("Flex Vault RPC validates token limits and persists only approved owners", {
  skip: pglitePrefix ? false : "Set PIP_PGLITE_PREFIX to an installation of @electric-sql/pglite.",
}, async () => {
  const require = createRequire(resolve(pglitePrefix, "package.json"));
  const { PGlite } = require("@electric-sql/pglite");
  const db = new PGlite();
  const user = "11111111-1111-4111-8111-111111111111";
  const otherUser = "22222222-2222-4222-8222-222222222222";
  const pendingUser = "33333333-3333-4333-8333-333333333333";
  const portfolio = "44444444-4444-4444-8444-444444444444";
  const pendingPortfolio = "55555555-5555-4555-8555-555555555555";

  async function store(owner, portfolioId, token, queryId = "123456") {
    return (await db.query(
      "SELECT public.pip_flex_store_connection($1::uuid, $2::uuid, $3, $4, $5) AS connection",
      [owner, portfolioId, "Test connection", token, queryId],
    )).rows[0].connection;
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
      GRANT USAGE ON SCHEMA auth, public TO anon, authenticated, service_role;
      GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated, service_role;
      GRANT SELECT ON public.user_access TO authenticated;

      CREATE SCHEMA vault;
      CREATE TABLE vault.secrets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT,
        description TEXT,
        secret TEXT NOT NULL
      );
      CREATE VIEW vault.decrypted_secrets AS
        SELECT id, secret AS decrypted_secret FROM vault.secrets;
      CREATE FUNCTION vault.create_secret(
        p_secret TEXT, p_name TEXT DEFAULT NULL,
        p_description TEXT DEFAULT NULL, p_key_id UUID DEFAULT NULL
      ) RETURNS UUID LANGUAGE plpgsql AS $$
      DECLARE secret_id UUID;
      BEGIN
        INSERT INTO vault.secrets (secret, name, description)
        VALUES (p_secret, p_name, p_description) RETURNING id INTO secret_id;
        RETURN secret_id;
      END;
      $$;
      CREATE FUNCTION vault.update_secret(
        p_secret_id UUID, p_secret TEXT, p_name TEXT DEFAULT NULL,
        p_description TEXT DEFAULT NULL, p_key_id UUID DEFAULT NULL
      ) RETURNS VOID LANGUAGE plpgsql AS $$
      BEGIN
        UPDATE vault.secrets SET secret = p_secret WHERE id = p_secret_id;
      END;
      $$;
    `);
    for (const migration of [
      "../supabase/migrations/20261023_pip_core_schema.sql",
      "../supabase/migrations/20261026000000_pip_account_fingerprints.sql",
      "../supabase/migrations/20261027000000_pip_ibkr_flex_vault.sql",
      "../supabase/migrations/20261102000001_pip_flex_token_validation.sql",
    ]) {
      await db.exec(await readFile(new URL(migration, import.meta.url), "utf8"));
    }

    const privileges = (await db.query(`
      SELECT
        has_function_privilege('authenticated', 'public.pip_flex_store_connection(uuid,uuid,text,text,text)', 'EXECUTE') AS authenticated,
        has_function_privilege('anon', 'public.pip_flex_store_connection(uuid,uuid,text,text,text)', 'EXECUTE') AS anon,
        has_function_privilege('service_role', 'public.pip_flex_store_connection(uuid,uuid,text,text,text)', 'EXECUTE') AS service_role
    `)).rows[0];
    assert.deepEqual(privileges, { authenticated: false, anon: false, service_role: true });

    await db.query("INSERT INTO auth.users (id) VALUES ($1), ($2), ($3)", [user, otherUser, pendingUser]);
    await db.query(
      "INSERT INTO public.user_access (user_id, status) VALUES ($1, 'approved'), ($2, 'approved'), ($3, 'pending')",
      [user, otherUser, pendingUser],
    );
    await db.query(
      "INSERT INTO public.portfolios (id, user_id, name) VALUES ($1, $2, 'one'), ($3, $4, 'pending')",
      [portfolio, user, pendingPortfolio, pendingUser],
    );

    await db.exec("SET ROLE service_role");
    const initial = await store(user, portfolio, "a");
    assert.ok(initial.id);
    assert.equal(initial.connection_name, "Test connection");
    assert.equal("token" in initial, false);
    assert.equal("query_id" in initial, false);
    assert.equal("vault_secret_id" in initial, false);

    const longestToken = "x".repeat(256);
    const updated = await store(user, portfolio, longestToken);
    assert.equal(updated.id, initial.id);
    const credentials = (await db.query(
      "SELECT public.pip_flex_get_connection($1::uuid, $2::uuid) AS credentials",
      [user, initial.id],
    )).rows[0].credentials;
    assert.equal(credentials.token, longestToken);
    assert.equal(credentials.query_id, "123456");

    for (const invalid of ["", "x".repeat(257), "invalid token", "invalid!token", null]) {
      await assert.rejects(() => store(user, portfolio, invalid), (error) => error.code === "22023");
    }
    await assert.rejects(() => store(user, portfolio, "valid", "not-numeric"), (error) => error.code === "22023");
    await assert.rejects(() => store(otherUser, portfolio, "valid"), (error) => error.code === "42501");
    await assert.rejects(() => store(pendingUser, pendingPortfolio, "valid"), (error) => error.code === "42501");

    const removed = (await db.query(
      "SELECT public.pip_flex_delete_connection($1::uuid, $2::uuid) AS removed",
      [user, initial.id],
    )).rows[0].removed;
    assert.equal(removed, true);
    await db.exec("RESET ROLE");
    assert.equal((await db.query("SELECT count(*)::int AS count FROM vault.secrets")).rows[0].count, 0);
    assert.equal((await db.query("SELECT count(*)::int AS count FROM public.pip_ibkr_connections")).rows[0].count, 0);
  } finally {
    await db.close();
  }
});

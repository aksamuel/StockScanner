import assert from "node:assert/strict";
import test from "node:test";
import { createFlexHandler } from "../supabase/functions/pip-ibkr-flex/handler.mjs";

const USER_ID = "33333333-3333-4333-8333-333333333333";
const PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222";
const CONNECTION_ID = "55555555-5555-4555-8555-555555555555";
const INTERNAL_KEY = "test-internal-key-with-at-least-thirty-two-characters";
const FLEX_TOKEN = "ibkr-flex-token-test-only";
const QUERY_ID = "123456789";
const STATEMENT_XML = `<FlexQueryResponse>
  <FlexStatements><FlexStatement accountId="U1234567" currency="USD">
    <OpenPositions><OpenPosition assetCategory="STK" accountId="U1234567"
      currency="USD" symbol="AAPL" position="5" /></OpenPositions>
  </FlexStatement></FlexStatements>
</FlexQueryResponse>`;

function harness({
  approved = true,
  portfolioOwned = true,
  connectionOwned = true,
  rateLimited = false,
  fetcher,
  userId = USER_ID,
} = {}) {
  const calls = { rpc: [], fetch: [], createdClients: [] };
  const envValues = {
    PIP_FLEX_INTERNAL_KEY: INTERNAL_KEY,
    SUPABASE_URL: "https://project.supabase.co",
    SUPABASE_PUBLISHABLE_KEYS: JSON.stringify({ default: "publishable-test-key" }),
    SUPABASE_SECRET_KEYS: JSON.stringify({ default: "service-role-test-key" }),
  };
  const userClient = {
    auth: {
      getUser: async () => ({ data: { user: { id: userId } }, error: null }),
    },
    from(table) {
      let filters = {};
      const query = {
        select() { return query; },
        eq(column, value) {
          filters[column] = value;
          return query;
        },
        async maybeSingle() {
          if (table === "user_access") {
            return { data: approved ? { status: "approved" } : { status: "pending" }, error: null };
          }
          if (table === "portfolios") {
            return {
              data: portfolioOwned && filters.id === PORTFOLIO_ID ? { id: PORTFOLIO_ID } : null,
              error: null,
            };
          }
          if (table === "pip_ibkr_connections") {
            return {
              data: connectionOwned
                && filters.id === CONNECTION_ID
                && filters.portfolio_id === PORTFOLIO_ID
                ? { id: CONNECTION_ID, portfolio_id: PORTFOLIO_ID, connection_name: "Main IBKR" }
                : null,
              error: null,
            };
          }
          return { data: null, error: null };
        },
      };
      return query;
    },
  };
  const adminClient = {
    async rpc(name, params) {
      calls.rpc.push([name, params]);
      if (name === "pip_flex_store_connection") {
        return {
          data: {
            id: CONNECTION_ID,
            portfolio_id: PORTFOLIO_ID,
            connection_name: params.p_connection_name,
            last_synced_at: null,
            created_at: "2026-01-01T00:00:00Z",
            vault_secret_id: "must-not-be-returned",
          },
          error: null,
        };
      }
      if (name === "pip_flex_get_connection") {
        return {
          data: { token: FLEX_TOKEN, query_id: QUERY_ID },
          error: null,
        };
      }
      if (name === "pip_flex_reserve_request" && rateLimited) {
        return { data: null, error: { code: "P4290" } };
      }
      return { data: true, error: null };
    },
  };
  const createClient = (url, key, options) => {
    calls.createdClients.push({ url, key, options });
    return key === "service-role-test-key" ? adminClient : userClient;
  };
  const handler = createFlexHandler({
    createClient,
    env: (name) => envValues[name],
    sleep: async () => {},
    fetcher: async (url, options) => {
      calls.fetch.push({ url: new URL(url), options });
      if (fetcher) return fetcher(url, options);
      if (new URL(url).pathname.endsWith("/SendRequest")) {
        return new Response(
          "<FlexStatementResponse><Status>Success</Status><ReferenceCode>87654321</ReferenceCode><Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url></FlexStatementResponse>",
          { status: 200 },
        );
      }
      return new Response(STATEMENT_XML, { status: 200 });
    },
  });
  return { handler, calls, envValues };
}

function request(payload, { internalKey = INTERNAL_KEY, authorization = "Bearer test-user-token" } = {}) {
  return new Request("https://project.supabase.co/functions/v1/pip-ibkr-flex", {
    method: "POST",
    headers: {
      ...(authorization ? { authorization } : {}),
      ...(internalKey ? { "x-pip-internal-key": internalKey } : {}),
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

test("Flex handler requires its server-only internal key before handling caller data", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({ action: "sync", portfolio_id: PORTFOLIO_ID }, { internalKey: "" }));

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { error: "Server authentication required." });
  assert.equal(calls.createdClients.length, 0);
  assert.equal(calls.fetch.length, 0);
});

test("Flex handler requires the authenticated user token after the internal key", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({
    action: "connect",
    portfolio_id: PORTFOLIO_ID,
  }, { authorization: "" }));

  assert.equal(response.status, 401);
  assert.equal(calls.createdClients.length, 0);
});

test("Flex handler rejects oversized request bodies while streaming them", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({
    action: "connect",
    portfolio_id: PORTFOLIO_ID,
    padding: "x".repeat(5_000),
  }));

  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: "Request is too large." });
  assert.equal(calls.rpc.length, 0);
  assert.equal(calls.fetch.length, 0);
});

test("Flex handler denies unapproved users and portfolios they do not own", async () => {
  const unapproved = harness({ approved: false });
  const deniedAccess = await unapproved.handler(request({
    action: "connect",
    portfolio_id: PORTFOLIO_ID,
  }));
  assert.equal(deniedAccess.status, 403);
  assert.equal(unapproved.calls.rpc.length, 0);

  const foreignPortfolio = harness({ portfolioOwned: false });
  const deniedPortfolio = await foreignPortfolio.handler(request({
    action: "connect",
    portfolio_id: PORTFOLIO_ID,
  }));
  assert.equal(deniedPortfolio.status, 404);
  assert.equal(foreignPortfolio.calls.rpc.length, 0);
});

test("saving a Flex connection sends credentials only to the Vault RPC", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({
    action: "connect",
    portfolio_id: PORTFOLIO_ID,
    connection_name: "Main IBKR",
    token: FLEX_TOKEN,
    query_id: QUERY_ID,
  }));
  const body = await response.text();

  assert.equal(response.status, 201);
  assert.equal(body.includes(FLEX_TOKEN), false);
  assert.equal(body.includes(QUERY_ID), false);
  assert.equal(body.includes("must-not-be-returned"), false);
  assert.deepEqual(calls.rpc[0], [
    "pip_flex_store_connection",
    {
      p_user_id: USER_ID,
      p_portfolio_id: PORTFOLIO_ID,
      p_connection_name: "Main IBKR",
      p_token: FLEX_TOKEN,
      p_query_id: QUERY_ID,
    },
  ]);
});

test("Flex sync uses the fixed IBKR endpoints, bounded rate-limit RPC, and returns the XML statement internally", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({
    action: "sync",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  }));
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.statement_xml, STATEMENT_XML);
  assert.equal(JSON.stringify(body).includes(FLEX_TOKEN), false);
  assert.equal(calls.fetch.length, 2);
  assert.equal(calls.fetch[0].url.hostname, "ndcdyn.interactivebrokers.com");
  assert.equal(calls.fetch[0].url.pathname.endsWith("/SendRequest"), true);
  assert.equal(calls.fetch[0].url.searchParams.get("t"), FLEX_TOKEN);
  assert.equal(calls.fetch[1].url.pathname.endsWith("/GetStatement"), true);
  assert.equal(calls.fetch[1].url.searchParams.get("q"), "87654321");
  assert.equal(calls.fetch[0].options.headers["User-Agent"], "StockScanner-PIP/1.0");
  assert.equal(calls.rpc.filter(([name]) => name === "pip_flex_reserve_request").length, 2);
});

test("Flex sync rejects an unsafe statement URL without following it", async () => {
  const { handler, calls } = harness({
    fetcher: async () => new Response(
      "<FlexStatementResponse><Status>Success</Status><ReferenceCode>87654321</ReferenceCode><Url>https://attacker.example/GetStatement</Url></FlexStatementResponse>",
      { status: 200 },
    ),
  });
  const response = await handler(request({
    action: "sync",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  }));

  assert.equal(response.status, 502);
  assert.equal(calls.fetch.length, 1);
  assert.equal((await response.text()).includes(FLEX_TOKEN), false);
});

test("Flex handler does not access credentials for a connection owned by another user", async () => {
  const { handler, calls } = harness({ connectionOwned: false });
  const response = await handler(request({
    action: "sync",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  }));

  assert.equal(response.status, 404);
  assert.equal(calls.rpc.length, 0);
  assert.equal(calls.fetch.length, 0);
});

test("Flex rate limit stops before contacting IBKR", async () => {
  const { handler, calls } = harness({ rateLimited: true });
  const response = await handler(request({
    action: "sync",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  }));

  assert.equal(response.status, 429);
  assert.equal(calls.fetch.length, 0);
});

test("Flex request fingerprints remain shared by token across application users", async () => {
  const firstUser = harness();
  const secondUser = harness({ userId: "44444444-4444-4444-8444-444444444444" });
  const payload = {
    action: "sync",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  };

  await firstUser.handler(request(payload));
  await secondUser.handler(request(payload));

  const firstFingerprint = firstUser.calls.rpc.find(([name]) => name === "pip_flex_reserve_request")[1]
    .p_token_fingerprint;
  const secondFingerprint = secondUser.calls.rpc.find(([name]) => name === "pip_flex_reserve_request")[1]
    .p_token_fingerprint;
  assert.equal(firstFingerprint, secondFingerprint);
});

test("disconnect deletes the owner-scoped Vault connection through its restricted RPC", async () => {
  const { handler, calls } = harness();
  const response = await handler(request({
    action: "disconnect",
    portfolio_id: PORTFOLIO_ID,
    connection_id: CONNECTION_ID,
  }));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { removed: true });
  assert.deepEqual(calls.rpc[0], [
    "pip_flex_delete_connection",
    { p_user_id: USER_ID, p_connection_id: CONNECTION_ID },
  ]);
});

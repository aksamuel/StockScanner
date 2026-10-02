import assert from 'node:assert/strict';
import { createPortfolioSignalsHandler } from '../supabase/functions/portfolio-signals/handler.mjs';

let user = { id: 'owner' }, approved = true, rpcError = null;
const rows = [{ symbol: 'ADBE', score: 35, status: 'available' }];
const calls = [];
const handler = createPortfolioSignalsHandler({
  env: name => ({ SUPABASE_URL: 'https://test.supabase.co', SUPABASE_PUBLISHABLE_KEYS: '{"default":"public-key"}' }[name]),
  createClient(url, key, options) {
    assert.equal(key, 'public-key');
    assert.equal(options.global.headers.Authorization, 'Bearer test-token');
    return {
      auth: { getUser: async () => ({ data: { user }, error: null }) },
      from(table) {
        const query = {
          select() { return query; }, eq() { return query; }, maybeSingle() { return query; },
          then(resolve) { resolve({ data: { status: approved ? 'approved' : 'pending' }, error: null }); },
        };
        calls.push(table);
        return query;
      },
      async rpc(name) {
        calls.push(name);
        return { data: rows, error: rpcError };
      },
    };
  },
});

const request = (auth = true) => new Request('https://test/functions/v1/portfolio-signals', {
  method: 'POST', headers: auth ? { authorization: 'Bearer test-token' } : {}, body: '{}',
});
assert.equal((await handler(request(false))).status, 401);
approved = false;
assert.equal((await handler(request())).status, 403);
approved = true;
const response = await handler(request());
assert.equal(response.status, 200);
assert.equal(response.headers.get('cache-control'), 'private, no-store');
assert.deepEqual(await response.json(), { signals: rows });
assert.ok(calls.includes('get_my_portfolio_technical_signals'));
rpcError = new Error('temporary');
assert.equal((await handler(request())).status, 502);
user = null;
assert.equal((await handler(request())).status, 401);
console.log('Private portfolio technical-signal access checks passed');

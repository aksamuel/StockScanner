import assert from 'node:assert/strict';
import { createHistoryHandler, parseHistory } from '../supabase/functions/portfolio-history/handler.mjs';

const now = new Date('2026-09-05T12:00:00Z');
const payload = { chart: { result: [{ meta: { exchangeTimezoneName: 'America/New_York' },
  timestamp: ['2026-09-03T13:30:00Z','2026-09-04T13:30:00Z','2026-09-05T13:30:00Z'].map(t=>Date.parse(t)/1000),
  indicators: { adjclose: [{ adjclose: [100, 80, 90] }] } }] } };
assert.deepEqual(parseHistory(payload, now).points, [['2026-09-03',100],['2026-09-04',80]]);
assert.deepEqual(parseHistory({}, now).points, []);
const invalid = structuredClone(payload);
invalid.chart.result[0].indicators.adjclose[0].adjclose = [null, -1, 90];
assert.deepEqual(parseHistory(invalid, now).points, []);

let user = { id: 'owner' }, approved = true, owns = true, authError = null, providerOk = true;
let calls = [], queries = [], providers = 0;
const handler = createHistoryHandler({
  clock: () => now, env: name => ({SUPABASE_URL:'https://test.supabase.co',SUPABASE_PUBLISHABLE_KEYS:'{"default":"public-key"}'}[name]),
  createClient(url, key, options) {
    assert.equal(key,'public-key');
    assert.equal(options.global.headers.Authorization,'Bearer test-token');
    return { auth: { getUser: async()=>({data:{user},error:authError}) }, from(table) {
      const filters=[];
      const q = { select(){return q}, eq(k,v){filters.push([k,v]);return q}, limit(){return q},maybeSingle(){return q},
        then(resolve){queries.push({table,filters}); resolve({data:table==='user_access'?{status:approved?'approved':'pending'}:owns?[{id:1}]:[],error:null})} };
      return q;
    } };
  },
  fetcher: async(url, options)=>{
    providers++; calls.push({url,options});
    return new Response(JSON.stringify(payload),{status:providerOk?200:429});
  },
});
const req = (symbol='AAPL', auth=true) => new Request('https://test/functions/v1/portfolio-history', {
  method:'POST',headers:{'content-type':'application/json',...(auth?{authorization:'Bearer test-token'}:{})},
  body:JSON.stringify({symbol,quantity:999,purchase_price:1000,user_id:'spoofed'}),
});
assert.equal((await handler(req('AAPL',false))).status,401);
user=null;assert.equal((await handler(req())).status,401);user={id:'owner'};
approved=false;assert.equal((await handler(req())).status,403);approved=true;
owns=false;assert.equal((await handler(req())).status,403);owns=true;
assert.equal((await handler(req('../invalid'))).status,400);
assert.equal(providers,0);
const good=await handler(req());
assert.equal(good.status,200);
assert.equal(good.headers.get('cache-control'),'private, no-store');
assert.equal((await good.json()).points.length,2);
assert.equal(providers,1);
assert.equal(calls[0].url,'https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1y&interval=1d');
assert.deepEqual(calls[0].options.headers,{'User-Agent':'StockScanner/1.0'});
assert.equal(calls[0].options.body,undefined);
assert.ok(queries.filter(q=>q.table==='user_portfolio_holdings').every(q=>q.filters.some(([k,v])=>k==='user_id'&&v==='owner')));
assert.equal((await handler(req())).status,200);assert.equal(providers,1);
// Another caller cannot obtain a cached symbol without passing ownership again.
user={id:'another-user'};owns=false;
assert.equal((await handler(req())).status,403);assert.equal(providers,1);
owns=true;providerOk=false;
assert.equal((await handler(req('MSFT'))).status,502);
const options = await handler(new Request('https://test/',{method:'OPTIONS',headers:{origin:'https://aksamuel.github.io'}}));
assert.equal(options.status,200);
assert.equal(options.headers.get('access-control-allow-origin'),'https://aksamuel.github.io');
assert.equal((await handler(new Request('https://test/'))).status,405);
console.log('History access, ownership, cache, provider privacy/failure, and candle parsing checks passed');

import test from 'node:test';
import assert from 'node:assert/strict';
import {createCatalystHandler} from '../supabase/functions/catalyst-beta/handler.mjs';
function fixture({user={id:'u'},approved=true,granted=true,issuer={symbol:'CRH',exchange:'NYQ'},cached=null,collectError=false}={}){
  let collected=0,backendUsed=false,saved=false;
  const handler=createCatalystHandler({clock:()=>new Date('2026-10-02T12:00:00Z'),env:n=>({SUPABASE_URL:'https://test',SUPABASE_ANON_KEY:'public',SUPABASE_SERVICE_ROLE_KEY:'secret'}[n]),
    createClient(url,key){if(key==='secret')backendUsed=true;return{auth:{getUser:async()=>({data:{user}})},from(table){let save=false;const q={select(){return q;},eq(){return q;},maybeSingle(){return q;},upsert(){save=true;saved=true;return q;},then(resolve){resolve({data:table==='user_access'?{status:approved?'approved':'pending'}:table==='nyse_tickers'?issuer:cached,error:null});}};return q;},rpc:async()=>({data:granted})};},
    collect:async()=>{collected++;if(collectError)throw new Error('SEC HTTP 403');return{symbol:'CRH',collected_at:'2026-10-02T12:00:00Z',events:[]};}});
  return {handler,stats:()=>({collected,backendUsed,saved})};
}
const req=(body={symbol:'CRH'},auth=true,origin='https://aksamuel.github.io')=>new Request('https://test',{method:'POST',headers:{...(auth?{authorization:'Bearer x'}:{}),origin},body:JSON.stringify(body)});
test('unauthenticated and unapproved never reach backend key',async()=>{for(const options of [{user:null},{approved:false}]){const f=fixture(options);assert.ok([401,403].includes((await f.handler(req())).status));assert.equal(f.stats().backendUsed,false);}const f=fixture();assert.equal((await f.handler(req({},false))).status,401);});
test('rejects invalid ticker, foreign origin and non-NYSE',async()=>{assert.equal((await fixture().handler(req({symbol:'../foo'}))).status,400);assert.equal((await fixture().handler(req({},true,'https://evil.example'))).status,403);assert.equal((await fixture({issuer:null}).handler(req())).status,400);});
test('rate-limit denies collection',async()=>{const f=fixture({granted:false});assert.equal((await f.handler(req())).status,429);assert.equal(f.stats().collected,0);});
test('fresh cache avoids upstream',async()=>{const f=fixture({cached:{collected_at:'2026-10-02T11:45:00Z',payload:{events:[]}}});assert.equal((await f.handler(req())).status,200);assert.equal(f.stats().collected,0);});
test('source failure preserves previous cache',async()=>{const f=fixture({collectError:true});assert.equal((await f.handler(req())).status,502);assert.equal(f.stats().saved,false);});
test('approved successful request saves evidence',async()=>{const f=fixture();assert.equal((await f.handler(req())).status,200);assert.equal(f.stats().saved,true);});

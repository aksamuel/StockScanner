// Local UI integration test with explicit fake auth/data; never used in deployment.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
 const page=await browser.newPage({viewport:{width:1440,height:950}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/auth.js',r=>r.fulfill({contentType:'application/javascript',body:"document.documentElement.classList.add('auth-ready');"}));
 await page.route('https://cdn.jsdelivr.net/**',r=>r.fulfill({contentType:'application/javascript',body:`
 const now=new Date().toISOString(); const event={id:'0000001234-26-000001',form:'8-K',category:'Earnings announcement',accepted_at:now,url:'https://www.sec.gov/Archives/edgar/data/1234/000000123426000001/0000001234-26-000001-index.html'};
 const payload={name:'CRH plc',cik:'0000001234',events:[event],collected_at:now,coverage:'TEST FIXTURE — not investment data'};
 export function createClient(){return {auth:{getUser:async()=>({data:{user:{id:'test-user'}}})},functions:{invoke:async()=>({data:payload})},from(table){const q={select(){return q},order(){return q},eq(){return q},limit(){return q},upsert(){return q},then(resolve){resolve({data:table==='catalyst_beta_cache'?[{symbol:'CRH',collected_at:now,payload}]:[],error:null})}};return q}}}
 `}));
 await page.goto('http://127.0.0.1:8000/catalysts-beta.html');
 await page.getByRole('button',{name:'Inspect',exact:true}).waitFor();
 assert.match(await page.locator('#report-date').innerText(),/2026/);
 assert.equal(await page.locator('#count').innerText(),'1');
 await page.getByRole('button',{name:'Inspect',exact:true}).click();
 await page.locator('textarea').fill('Reviewed guidance increase in official source.');
 await page.locator('input[type=checkbox]').check();
 await page.locator('.review-form select').selectOption('guidance_raise');
 await page.getByRole('button',{name:'Save my assessment'}).click();
 await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('Private assessment saved'));
 assert.equal(await page.locator('#reviewed').innerText(),'1');
 await page.screenshot({path:'/tmp/catalyst-beta-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'/tmp/catalyst-beta-mobile.png',fullPage:true});
 await page.locator('#filter').selectOption('Candidate');
 // Outcome varies with the current technical report; filtering must not crash.
 assert.deepEqual(errors,[]);
 await browser.close();console.log('Desktop/mobile UI, real report parsing, private review flow and overflow checks passed (mock auth/evidence).');
})().catch(e=>{console.error(e);process.exit(1)});

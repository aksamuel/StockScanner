import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/+esm';
import { assess, parseTechnicalDocument, WEIGHTS, isFresh } from './catalyst-model.mjs';
const client = createClient('https://cszzbkssxxgwgafwuonc.supabase.co', 'sb_publishable_VnhkG4H4acjm2Hp1k5tzyw_I9xtUrGI');
const $ = id => document.getElementById(id);
let rows = [], reviews = [], technical = new Map(), user, selected, sortKey = 'combined';
const money = n => typeof n === 'number' && Number.isFinite(n) ? `$${n.toFixed(2)}` : '—';
const date = x => Number.isFinite(Date.parse(x)) ? new Date(x).toLocaleString('en-GB', { timeZone: 'America/New_York' }) + ' NY' : 'Unavailable';
const element = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
function link(label, url) { const a = element('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
function officialLink(url) { try { const u = new URL(url); return u.protocol === 'https:' && u.hostname === 'www.sec.gov' && u.pathname.startsWith('/Archives/edgar/data/'); } catch { return false; } }
function activeEvents(payload) { return (payload.events || []).filter(e => isFresh(e.accepted_at, Date.now(), 90) && officialLink(e.url)); }
function model(row) { return assess(technical.get(row.symbol), activeEvents(row.payload), reviews.filter(r => r.symbol === row.symbol), row.collected_at); }

async function load() {
  $('reload').disabled = true;
  try {
    const [cache, notes, report] = await Promise.all([
      client.from('catalyst_beta_cache').select('*').order('collected_at', { ascending: false }).limit(500),
      client.from('catalyst_beta_reviews').select('*').eq('user_id', user.id).limit(1000),
      fetch('technical.html', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error('Technical report unavailable.'); return r.text(); }),
    ]);
    if (cache.error || notes.error) throw new Error('Cannot load beta storage. Check your access or retry.');
    rows = cache.data; reviews = notes.data;
    technical = parseTechnicalDocument(new DOMParser().parseFromString(report, 'text/html'));
    $('suggestions').textContent = `Tickers present in the technical report (not buy recommendations): ${[...technical.keys()].slice(0,8).join(', ')}. Other NYSE tickers may have no technical coverage.`;
    $('report-date').textContent = date([...technical.values()][0]?.as_of);
    $('message').textContent = rows.length ? 'Saved evidence loaded. Select Inspect to review filings. Latest 500 researched stocks shown.' : 'Start with a NYSE ticker such as CRH. No live data has been fabricated or pre-scored.';
    render(); if (selected) detail(selected);
  } catch (e) { $('message').textContent = e.message; }
  finally { $('reload').disabled = false; }
}
function render() {
  $('count').textContent = rows.length;
  $('reviewed').textContent = rows.reduce((sum, r) => sum + model(r).reviewed, 0);
  $('results').replaceChildren();
  const sorted = [...rows].sort((a,b) => sortKey === 'symbol' ? a.symbol.localeCompare(b.symbol) : (model(b).combined ?? -1) - (model(a).combined ?? -1));
  for (const row of sorted) {
    const m = model(row), t = technical.get(row.symbol);
    if ($('filter').value !== 'all' && !m.status.startsWith($('filter').value)) continue;
    const tr = element('tr');
    const values = [row.symbol, m.combined === null ? '—' : m.combined.toFixed(1), t?.score ?? '—', m.catalyst,
      m.status, money(t?.entry), money(t?.stop), [t?.target1,t?.target2,t?.target3].map(money).join(' / '),
      m.rr === null ? 'Invalid / unavailable' : `${m.rr.toFixed(2)} : 1`, date(row.collected_at)];
    values.forEach((v,i) => tr.append(element('td', String(v), i === 4 ? 'status' : '')));
    const td = element('td'), button = element('button', 'Inspect', 'secondary'); button.addEventListener('click', () => detail(row.symbol)); td.append(button);tr.append(td);$('results').append(tr);
  }
  if (!$('results').children.length) { const tr = element('tr'), td = element('td', 'No results in this view. Search a NYSE ticker above.');td.colSpan=11;tr.append(td);$('results').append(tr); }
}
function detail(symbol) {
  selected = symbol;
  const row = rows.find(r => r.symbol === symbol); if (!row) return;
  $('detail').hidden = false; $('detail-title').textContent = `${symbol} · ${row.payload.name}`;
  $('research-links').replaceChildren(
    link('SEC issuer', `https://www.sec.gov/edgar/browse/?CIK=${row.payload.cik}&owner=include`),
    link('Reuters search', `https://www.reuters.com/site-search/?query=${encodeURIComponent(row.payload.name)}`),
    link('Company IR search', `https://www.google.com/search?q=${encodeURIComponent(row.payload.name + ' investor relations')}`),
    link('TradingView', `https://www.tradingview.com/symbols/NYSE-${encodeURIComponent(symbol.replace('.', '-'))}/`),
    link('IBKR research login', 'https://www.interactivebrokers.com/sso/Login'),
    link('FactSet context', 'https://www.factset.com/earningsinsight'));
  $('detail-context').textContent = `${row.payload.coverage} Scores below reflect your assessment, not automated verification. Read exhibits as well as the filing. Earnings dates must be checked separately.`;
  $('events').replaceChildren();
  const events = activeEvents(row.payload);
  if (!events.length) $('events').append(element('p', 'No eligible recent filings returned. This is not evidence that the company has no catalysts.'));
  for (const e of events) {
    const review = reviews.find(r => r.symbol === symbol && r.event_id === e.id);
    const card = element('article', undefined, 'event'), header = element('header');
    header.append(element('h3', `${e.form} · ${e.category}`), link('Read official filing ↗', e.url));
    card.append(header, element('p', `${date(e.accepted_at)} · ${e.id} · Metadata only; direction unassessed${isFresh(e.accepted_at,Date.now(),30)?'':' · Older than 30 days: review can be saved, but earns no current score'}`));
    const form = element('form', undefined, 'review-form');
    const label = element('label', 'Your assessment'), select = element('select');
    for (const [value, weight] of Object.entries(WEIGHTS)) { const o = element('option', `${value.replaceAll('_',' ')} (${weight > 0 ? '+' : ''}${weight})`);o.value=value;select.append(o); }
    select.value = review?.category || 'neutral';label.append(select);
    const noteLabel = element('label', 'Reason and evidence (required; private to you)'), note = element('textarea'); note.maxLength=1000; note.required=true;note.value=review?.note||'';noteLabel.append(note);
    const actions = element('div', undefined, 'review-actions'), confirmLabel=element('label'), confirm=element('input');confirm.type='checkbox';confirm.required=true;confirm.checked=!!review?.confirmed;
    confirmLabel.append(confirm, document.createTextNode(' I read the source and checked the direction/materiality.'));
    const save=element('button','Save my assessment');save.type='submit';actions.append(confirmLabel,save);
    form.append(label,noteLabel,actions);card.append(form);$('events').append(card);
    form.addEventListener('submit', async event => {
      event.preventDefault();save.disabled=true;
      try {
        if (!note.value.trim()) throw new Error('Enter your evidence-based reason.');
        const record={user_id:user.id,symbol,event_id:e.id,category:select.value,note:note.value.trim(),confirmed:confirm.checked,updated_at:new Date().toISOString()};
        const {error}=await client.from('catalyst_beta_reviews').upsert(record,{onConflict:'user_id,symbol,event_id'});
        if(error) throw new Error('Assessment could not be saved. Retry after checking your session.');
        reviews=reviews.filter(r=>!(r.symbol===symbol&&r.event_id===e.id));reviews.push(record);render();$('message').textContent='Private assessment saved. Beta score updated; production recommendations unchanged.';
      } catch(error){$('message').textContent=error.message;}finally{save.disabled=false;}
    });
  }
}
$('lookup').addEventListener('submit', async event => {
  event.preventDefault(); const symbol=$('symbol').value.trim().toUpperCase();$('analyse').disabled=true;$('message').textContent=`Checking ${symbol} against NYSE and SEC sources…`;
  try {
    const {data,error}=await client.functions.invoke('catalyst-beta',{body:{symbol}});
    if(error){let message=data?.error;try{message=(await error.context.json()).error||message;}catch{/* generic below */}throw new Error(message||'Evidence service unavailable. Retry shortly.');}
    rows=rows.filter(r=>r.symbol!==symbol);rows.unshift({symbol,collected_at:data.collected_at,payload:data});render();detail(symbol);
    $('message').textContent=`${symbol}: ${data.events.length} filings found. ${data.cached?'Using a cache less than one hour old.':'Fresh SEC check complete.'} Assess source content before scoring.`;
  } catch(e){$('message').textContent=e.message;}finally{$('analyse').disabled=false;}
});
$('reload').addEventListener('click',load);$('filter').addEventListener('change',render);
document.querySelectorAll('[data-sort]').forEach(b=>b.addEventListener('click',()=>{sortKey=b.dataset.sort;render();}));
try {
  const {data,error}=await client.auth.getUser(); if(error||!data.user) throw new Error('Sign in to StockScanner to use this beta.');user=data.user;
  await load();
}catch(e){$('message').textContent=e.message;}

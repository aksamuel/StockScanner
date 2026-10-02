export const WEIGHTS = Object.freeze({ guidance_raise: 8, earnings_improvement: 7, contract_approval: 6,
  acquisition_disposal: 4, capital_return: 3, insider_purchase: 3, negative_guidance: -8,
  dilution: -7, accounting_regulatory: -8, neutral: 0 });
const DAY = 86400000;
export function validNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const n = Number(String(value).replace(/[$,]/g, '').match(/^-?\d+(?:\.\d+)?/)?.[0]);
  return Number.isFinite(n) ? n : null;
}
export function isFresh(iso, now = Date.now(), days = 4) {
  const t = Date.parse(iso || '');
  return Number.isFinite(t) && t <= now && now - t <= days * DAY;
}
export function assess(technical, events = [], reviews = [], collectedAt, now = Date.now()) {
  const reviewById = new Map(reviews.map(r => [r.event_id, r]));
  const scoresByCategory = new Map();
  const seen = new Set();
  let reviewed = 0;
  for (const e of events) {
    const review = reviewById.get(e.id);
    if (seen.has(e.id) || !review?.confirmed || !review?.note?.trim() || !Object.hasOwn(WEIGHTS, review.category)
      || !isFresh(e.accepted_at, now, 30) || !isFresh(review.updated_at, now, 30)) continue;
    seen.add(e.id); reviewed++;
    // Cap by category: five releases about one buyback do not produce five scores.
    scoresByCategory.set(review.category, WEIGHTS[review.category]);
  }
  const catalyst = Math.max(-25, Math.min(25, [...scoresByCategory.values()].reduce((a, b) => a + b, 0)));
  const score = validNumber(technical?.score);
  const technicalFresh = !!technical && isFresh(technical.as_of, now) && score !== null && score >= 0 && score <= 100;
  const evidenceFresh = isFresh(collectedAt, now, 1);
  const combined = technicalFresh && evidenceFresh ? Math.max(0, Math.min(100, score * .75 + catalyst)) : null;
  const entry = validNumber(technical?.entry), stop = validNumber(technical?.stop), target = validNumber(technical?.target2);
  const planValid = entry > 0 && stop > 0 && stop < entry && target > entry;
  const rr = planValid ? (target - entry) / (entry - stop) : null;
  const price = validNumber(technical?.price), ma50 = validNumber(technical?.ma50), ma200 = validNumber(technical?.ma200);
  const trend = price > 0 && ma50 > 0 && ma200 > 0 && price > ma50 && price > ma200;
  const nearEntry = price > 0 && entry > 0 && Math.abs(price / entry - 1) <= .03;
  let status = 'Review evidence';
  if (!technicalFresh || !evidenceFresh) status = 'Stale / incomplete';
  else if (catalyst < 0) status = 'Risk review';
  else if (reviewed && catalyst > 0 && combined >= 75 && trend && planValid && rr >= 2 && nearEntry) status = 'Candidate — verify in IBKR';
  else if (reviewed) status = 'Watch / wait';
  return { catalyst, combined, reviewed, technicalFresh, evidenceFresh, status, rr, trend, planValid };
}

export function parseReportDate(title) {
  const m = title.match(/(\d{2})\/([A-Za-z]{3})\/(\d{4}),\s*(\d{2}):(\d{2})\s*(EDT|EST)/);
  if (!m) return null;
  const month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].indexOf(m[2]) + 1;
  if (!month) return null;
  return `${m[3]}-${String(month).padStart(2, '0')}-${m[1]}T${m[4]}:${m[5]}:00${m[6] === 'EDT' ? '-04:00' : '-05:00'}`;
}

export function parseTechnicalDocument(doc) {
  const asOf = parseReportDate(doc.title);
  const records = new Map();
  for (const table of doc.querySelectorAll('table')) {
    const heads = [...table.querySelectorAll('thead th')].map(h => h.textContent.trim());
    if (!['Score', 'Entry', '50 MA', '200 MA'].every(h => heads.includes(h))) continue;
    for (const row of table.querySelectorAll('tbody tr[data-symbol]')) {
      const symbol = row.dataset.symbol;
      if (records.has(symbol)) continue;
      const cells = [...row.children];
      const value = name => validNumber(cells[heads.indexOf(name)]?.textContent);
      records.set(symbol, { symbol, as_of: asOf, price: validNumber(row.dataset.currentPrice),
        score: value('Score'), entry: value('Entry'), stop: value('Stop Loss'),
        target1: value('Target 1'), target2: value('Target 2'), target3: value('Target 3'),
        ma50: value('50 MA'), ma200: value('200 MA'), rsi: value('RSI') });
    }
  }
  return records;
}

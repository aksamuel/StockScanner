// Beta evidence classification. Filing metadata never implies a bullish thesis.
export const MODEL_VERSION = 'catalyst-beta-1';
export const SYMBOL = /^[A-Z0-9][A-Z0-9.-]{0,14}$/;
export function normalizeSymbol(value) {
  const symbol = String(value || '').trim().toUpperCase();
  if (!SYMBOL.test(symbol)) throw new Error('Invalid ticker.');
  return symbol;
}

export function companyMapping(payload, symbol) {
  const fields = payload?.fields || [];
  const ticker = fields.indexOf('ticker'), exchange = fields.indexOf('exchange');
  const cik = fields.indexOf('cik'), name = fields.indexOf('name');
  if ([ticker, exchange, cik, name].some(i => i < 0)) throw new Error('Invalid SEC company mapping.');
  const row = payload.data.find(r => String(r[ticker]).replaceAll('.', '-') === symbol.replaceAll('.', '-')
    && String(r[exchange]).toUpperCase() === 'NYSE');
  return row ? { cik: String(row[cik]).padStart(10, '0'), name: row[name], symbol } : null;
}

export function filingCategory(form, items = '') {
  if (form.startsWith('4')) return 'Insider transaction — purchase/sale not yet verified';
  if (form.startsWith('10-Q') || form.startsWith('10-K') || form.startsWith('20-F')) return 'Financial results';
  if (items.includes('4.02')) return 'Accounting reliability risk';
  if (items.includes('3.01')) return 'Listing compliance risk';
  if (items.includes('2.02')) return 'Earnings announcement';
  if (items.includes('1.01')) return 'Material agreement';
  if (items.includes('2.01')) return 'Acquisition / disposal';
  if (items.includes('5.02')) return 'Management / board change';
  return 'Corporate disclosure';
}

export function extractFilings(payload, company, now = new Date()) {
  const recent = payload?.filings?.recent;
  if (!Array.isArray(recent?.accessionNumber)) throw new Error('Invalid SEC submissions response.');
  const cutoff = now.getTime() - 90 * 86400000;
  const seen = new Set(), events = [];
  recent.accessionNumber.forEach((accession, i) => {
    const form = String(recent.form?.[i] || '');
    const date = String(recent.filingDate?.[i] || '');
    const accepted = recent.acceptanceDateTime?.[i] || `${date}T23:59:59Z`;
    const timestamp = Date.parse(accepted);
    if (!/^(8-K|10-Q|10-K|20-F|6-K|4)(\/A)?$/.test(form)
      || !/^\d{10}-\d{2}-\d{6}$/.test(accession) || !Number.isFinite(timestamp)
      || timestamp < cutoff || timestamp > now.getTime() || seen.has(accession)) return;
    seen.add(accession);
    const items = String(recent.items?.[i] || '');
    events.push({ id: accession, symbol: company.symbol, form, date, accepted_at: accepted,
      category: filingCategory(form, items), items,
      url: `https://www.sec.gov/Archives/edgar/data/${Number(company.cik)}/${accession.replaceAll('-', '')}/${accession}-index.html`,
      evidence: 'SEC filing metadata', direction: 'unassessed', score: 0,
      expires_at: new Date(timestamp + 90 * 86400000).toISOString() });
  });
  return events.sort((a, b) => b.accepted_at.localeCompare(a.accepted_at)).slice(0, 60);
}

export async function collectEvidence(symbol, { fetcher = fetch, now = new Date(), mapping,
  userAgent = 'StockScanner catalyst research aaksamuel@zohomail.com' } = {}) {
  const read = async url => {
    const r = await fetcher(url, { headers: { 'User-Agent': userAgent, Accept: 'application/json' },
      signal: AbortSignal.timeout(15000), redirect: 'error' });
    if (!r.ok) throw new Error(`SEC temporarily unavailable (HTTP ${r.status}). No new evidence collected.`);
    return r.json();
  };
  const companies = mapping || await read('https://www.sec.gov/files/company_tickers_exchange.json');
  const company = companyMapping(companies, normalizeSymbol(symbol));
  if (!company) throw new Error('No NYSE SEC issuer mapping found. Funds, some securities and unmapped symbols are not supported.');
  const submissions = await read(`https://data.sec.gov/submissions/CIK${company.cik}.json`);
  return { symbol: company.symbol, name: company.name, cik: company.cik,
    collected_at: now.toISOString(), model_version: MODEL_VERSION,
    events: extractFilings(submissions, company, now), status: 'available',
    coverage: 'Recent SEC filings, 90 days, maximum 60. No Reuters, Bloomberg or IBKR feed is ingested.' };
}

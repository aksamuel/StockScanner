import assert from 'node:assert/strict';
import {
  aggregateSellAdvisorHoldings,
  parseScannerReportTimestamp,
  parseSellAdvisorCsv,
  selectLatestScanQuote,
} from '../sell-advisor.js';

const csv = [
  'Symbol,Quantity,CostBasisPrice,OpenDateTime,Currency,ClientAccountID',
  'LONG,1.25,20,2026-01-03,USD,account-not-used',
  'LONG,0.75,24,2026-02-02,USD,account-not-used',
  'SHORT,-2.5,10,2026-02-10,USD,account-not-used',
  'NOCURRENCY,3,5,2026-02-11,,account-not-used',
  'LONG,1.25,20,2026-01-03,USD,account-not-used',
].join('\n');

const parsed = parseSellAdvisorCsv(csv);
assert.equal(parsed.duplicateCount, 1);
assert.deepEqual(parsed.rejected, []);
assert.equal(parsed.lots.length, 4);
assert.ok(parsed.lots.every((lot) => !Object.hasOwn(lot, 'account')));

const holdings = aggregateSellAdvisorHoldings(parsed.lots);
const long = holdings.find((holding) => holding.symbol === 'LONG');
const short = holdings.find((holding) => holding.symbol === 'SHORT');
const missingCurrency = holdings.find((holding) => holding.symbol === 'NOCURRENCY');
assert.equal(long.longQuantity, 2);
assert.equal(long.quantity, 2);
assert.equal(long.buyPrice, 21.5);
assert.equal(long.lots.length, 2);
assert.equal(short.shortQuantity, 2.5);
assert.equal(short.quantity, -2.5);
assert.equal(short.buyPrice, 10);
assert.equal(missingCurrency.currency, null);
assert.equal(missingCurrency.currencyStatus, 'missing');

const mixed = aggregateSellAdvisorHoldings([
  { symbol: 'MIX', quantity: 4, buyPrice: 10, boughtOn: '2026-01-01', currency: 'USD', currencySource: 'CSV' },
  { symbol: 'MIX', quantity: -1, buyPrice: 12, boughtOn: '2026-01-02', currency: 'USD', currencySource: 'CSV' },
])[0];
assert.equal(mixed.quantity, 3);
assert.equal(mixed.mixedDirection, true);
assert.equal(mixed.buyPrice, null);
assert.equal(mixed.longQuantity, 4);
assert.equal(mixed.shortQuantity, 1);

const selected = selectLatestScanQuote(
  { price: 100, at: '2026-10-22T14:00:00Z' },
  { price: 90, at: '2026-10-22T14:30:00Z' },
);
assert.equal(selected.source, 'Daily scan');
assert.equal(selected.price, 90);
assert.equal(selectLatestScanQuote(
  { price: 100, at: '2026-10-22T14:31:00Z' },
  { price: 90, at: '2026-10-22T14:30:00Z' },
).source, 'Hourly scan');
assert.equal(selectLatestScanQuote({ price: 100 }, { price: 90, at: '2026-10-22T14:30:00Z' }).source, 'Daily scan');
assert.equal(parseScannerReportTimestamp('StockScanner Dashboard - 22/Oct/2026, 07:44 EDT'), '2026-10-22T11:44:00.000Z');

const selectedCurrency = parseSellAdvisorCsv(
  'symbol,quantity,buy_price,buy_date\nABC,0.125,18.75,2026-01-01',
  'USD',
);
assert.equal(selectedCurrency.lots[0].currency, 'USD');
assert.equal(selectedCurrency.lots[0].currencySource, 'User selected');

assert.throws(
  () => parseSellAdvisorCsv('symbol,quantity,buy_price\nABC,1,10'),
  /Required CSV column is missing: buyDate/,
);
console.log('Sell Advisor import, holdings, duplicate, currency and quote-selection checks passed');

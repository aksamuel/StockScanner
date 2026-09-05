import assert from 'node:assert/strict';
import { purchaseBasisBySymbol, levelReturn } from '../bought-price.js';

const bases = purchaseBasisBySymbol([
  { symbol: 'DUP', quantity: 99, buy_price: 999 },
  { symbol: 'MANUAL', quantity: 2, buy_price: 80 },
], [
  { symbol: ' dup ', quantity: '0.5', buy_price: '100', currency: 'USD' },
  { symbol: 'DUP', quantity: '1.5', buy_price: '120', currency: 'USD' },
  { symbol: 'MISSING', quantity: 2, buy_price: 100 },
  { symbol: 'MISSING', quantity: 1, buy_price: null },
  { symbol: 'SHORT', quantity: -1, buy_price: 100 },
  { symbol: 'MIXED', quantity: 1, buy_price: 100, currency: 'USD' },
  { symbol: 'MIXED', quantity: 1, buy_price: 90, currency: 'EUR' },
  { symbol: 'EUR', quantity: 1, buy_price: 90, currency: 'EUR' },
]);
assert.equal(bases.get('DUP').price, 115, 'Use quantity weights and avoid counting the bought-list duplicate');
assert.equal(bases.get('DUP').lots, 2);
assert.equal(bases.get('MANUAL').price, 80);
assert.equal(bases.get('MISSING').price, null, 'Do not average only the lots with known prices');
assert.equal(bases.get('SHORT').price, null, 'Do not label a short as a long-position profit');
assert.equal(bases.get('MIXED').price, null, 'Do not combine different currencies');
assert.equal(bases.get('EUR').price, 90);
assert.equal(levelReturn(110, bases.get('EUR')), null, 'USD report levels require a USD cost basis');
const basis = { price: 100, currency: 'USD' };
assert.deepEqual(levelReturn(120, basis), { text: '+20.00%', tone: 'profit' });
assert.deepEqual(levelReturn(75, basis), { text: '-25.00%', tone: 'loss' });
assert.deepEqual(levelReturn(100, basis), { text: '0.00%', tone: 'neutral' });
assert.deepEqual(levelReturn(99.9999, basis), { text: '0.00%', tone: 'neutral' });
for (const level of [null, '', 0, -1, NaN, Infinity]) assert.equal(levelReturn(level, basis), null);
for (const price of [null, '', 0, -1, NaN, Infinity]) {
  assert.equal(purchaseBasisBySymbol([{ symbol: 'BAD', quantity: 1, buy_price: price }]).get('BAD').price, null);
}
assert.equal(levelReturn(100, bases.get('MISSING')), null);
assert.equal(purchaseBasisBySymbol([{ symbol: 'BAD', quantity: 0, buy_price: 100 }]).get('BAD').price, null);
assert.equal(bases.has('UNBOUGHT'), false);
console.log('Purchase weights, duplicate sources, missing prices, currencies, short positions and return labels passed');

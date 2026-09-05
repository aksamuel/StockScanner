import assert from 'node:assert/strict';
import { technicalStrength, recoveryScenario, historicalRecovery, stockGrowthMetrics, recoveryGraphModel } from '../portfolio-recovery.js';

for (const [score, label] of [[0,'Weak'],[39,'Weak'],[40,'Moderate'],[70,'Moderate'],[71,'Strong'],[100,'Strong'],[null,'Unavailable'],['','Unavailable'],[101,'Unavailable']]) {
  assert.equal(technicalStrength(score).label, label);
}
const holding = { quantity: 1, buy_price: 100, quote: { price: 80 } };
const now = new Date('2026-09-05T12:00:00Z');
const scenario = recoveryScenario(holding, { dailyReturn: 0.01 }, now);
assert.equal(scenario.requiredGain, 25);
assert.equal(scenario.days, 23);
assert.equal(scenario.date.toISOString().slice(0, 10), '2026-09-28');
assert.equal(recoveryScenario(holding, { dailyReturn: -0.01 }, now).date, null);
assert.equal(recoveryScenario({...holding, quantity: -1}, {}, now).label, 'Not estimated for short positions');
assert.equal(recoveryScenario({...holding, quote: {price: 105}}, {}, now).days, 0);
assert.equal(recoveryScenario({...holding, quote: {price: null}}, {}, now).label, 'Price data needed');
const points = Array.from({length: 60}, (_, i) => [new Date(Date.UTC(2026,6,7+i)).toISOString().slice(0,10), 100]);
points[10][1] = 75;
points[11][1] = 85;
points[30][1] = 70;
for (let i=31;i<60;i++) points[i][1]=80;
const history = historicalRecovery({points}, 0.2, now);
assert.equal(history.recovered, 1);
assert.equal(history.unresolved, 1);
assert.equal(history.medianDays, 2);
assert.equal(history.unresolvedDays, 29);
assert.ok(historicalRecovery({points: points.slice(0,10)}, 0.2, now).unavailable);
assert.ok(historicalRecovery({points}, 0.2, new Date('2027-01-01')).unavailable);
assert.equal(historicalRecovery({points}, 0.9, now).recovered, 0);
const rising = {points: points.map(([date], i) => [date, 50 * 1.01 ** i])};
const metrics = stockGrowthMetrics(rising, now);
assert.ok(Math.abs(metrics.dailyReturn - 0.01) < 1e-12);
assert.equal(metrics.startDate, '2026-07-07');
assert.equal(metrics.endDate, '2026-09-04');
const graph = recoveryGraphModel(holding, rising, {dailyReturn: 0.005}, now);
assert.equal(graph.stockScenario.days, 23);
assert.equal(graph.benchmarkScenario.days, 45);
assert.equal(graph.horizonDays, 365);
assert.equal(graph.history.length, 60);
for (const [projection, scenario] of [[graph.stockProjection,graph.stockScenario],[graph.benchmarkProjection,graph.benchmarkScenario]]) {
  assert.equal(projection[0].price, 80); // Both scenarios use the holding's quote.
  assert.equal(projection[0].date.getTime(), now.getTime());
  assert.equal(projection.at(-1).price, 100);
  assert.equal(projection.at(-1).date.getTime(), scenario.date.getTime());
  assert.ok(projection.every(p => p.price <= 100));
}
const falling = {points: points.map(([date], i) => [date, 100 * 0.99 ** i])};
const noRecovery = recoveryGraphModel(holding, falling, {dailyReturn: 0}, now);
assert.equal(noRecovery.stockScenario.date, null);
assert.equal(noRecovery.benchmarkScenario.date, null);
assert.ok(noRecovery.stockProjection.at(-1).price < 80);
assert.ok(noRecovery.benchmarkProjection.every(p => p.price === 80));
const slow = recoveryGraphModel(holding, undefined, {dailyReturn: 0.00001}, now);
assert.equal(slow.horizonDays, 1826);
assert.ok(slow.benchmarkScenario.days > slow.horizonDays);
assert.ok(slow.benchmarkScenario.date > slow.end); // Retain dates beyond the chart.
assert.ok(slow.benchmarkProjection.at(-1).price < slow.target);
assert.deepEqual(slow.history, []);
assert.deepEqual(slow.stockProjection, []);
assert.ok(slow.stock.unavailable);
for (const invalid of [undefined,{points: rising.points.slice(1,20)}, {points: [...rising.points].reverse()}, {points: rising.points.map(([d,p],i) => [d,i===30?NaN:p])}]) {
  assert.ok(stockGrowthMetrics(invalid, now).unavailable);
}
assert.ok(stockGrowthMetrics(rising, new Date('2027-01-01')).unavailable);
assert.ok(stockGrowthMetrics(rising, new Date('2026-09-01')).unavailable);
assert.ok(recoveryGraphModel({...holding, quantity: -1}, rising, metrics, now).unavailable);
assert.ok(recoveryGraphModel({...holding, quote:{price: 110}}, rising, metrics, now).unavailable);
console.log('Technical strength, recovery dates, history validation, and projection checks passed');

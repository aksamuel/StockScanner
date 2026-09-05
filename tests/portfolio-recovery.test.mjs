import assert from 'node:assert/strict';
import { technicalStrength, recoveryScenario, historicalRecovery } from '../portfolio-recovery.js';

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
console.log('Technical strength, breakeven, and historical recovery checks passed');

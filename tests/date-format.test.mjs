import assert from 'node:assert/strict';
import { formatDate, formatDateTime, parseDateInput, validateDateInputs } from '../date-format.js';

assert.equal(formatDate('2026-09-05'), '05/Sep/2026');
assert.equal(formatDate('2024-02-29'), '29/Feb/2024');
assert.equal(formatDate(null), '—');
assert.equal(formatDate('invalid'), '—');
assert.equal(parseDateInput('05/sEp/2026'), '2026-09-05');
assert.equal(parseDateInput('29/Feb/2024'), '2024-02-29');
for (const invalid of ['29/Feb/2026', '31/Apr/2026', '00/Jan/2026', '05/Xyz/2026', '2026-09-05']) {
  assert.equal(parseDateInput(invalid), null);
}
assert.ok(formatDateTime(new Date(2026, 8, 5, 12)).startsWith('05/Sep/2026, '));
let message;
const input = { value: '31/Feb/2026', setCustomValidity(value) { message = value; } };
const form = { querySelectorAll() { return [input]; }, reportValidity() { return !message; } };
assert.equal(validateDateInputs(form), false);
input.value = '28/Feb/2026';
assert.equal(validateDateInputs(form), true);
input.value = '';
assert.equal(validateDateInputs(form), true);
console.log('Date formatting and validation checks passed');

import assert from 'node:assert/strict';
import { formatDate, formatDateTime, formatTime, parseDateInput, validateDateInputs } from '../date-format.js';

assert.equal(formatDate('2026-09-05'), '05/Sep/2026');
assert.equal(formatDate('2024-02-29'), '29/Feb/2024');
assert.equal(formatDate(null), '—');
assert.equal(formatDate('invalid'), '—');
assert.equal(parseDateInput('05/sEp/2026'), '2026-09-05');
assert.equal(parseDateInput('29/Feb/2024'), '2024-02-29');
for (const invalid of ['29/Feb/2026', '31/Apr/2026', '00/Jan/2026', '05/Xyz/2026', '2026-09-05']) {
  assert.equal(parseDateInput(invalid), null);
}
for (const [value, expected] of [
  ['2026-09-05T18:07:59Z', '05/Sep/2026, 14:07 EDT'],
  ['2026-01-05T18:07:59Z', '05/Jan/2026, 13:07 EST'],
  ['2026-09-05T01:07:59Z', '04/Sep/2026, 21:07 EDT'],
  ['2026-01-01T04:59:59Z', '31/Dec/2025, 23:59 EST'],
  ['2026-09-05T04:00:59Z', '05/Sep/2026, 00:00 EDT'],
  ['2026-03-08T06:59:59Z', '08/Mar/2026, 01:59 EST'],
  ['2026-03-08T07:00:00Z', '08/Mar/2026, 03:00 EDT'],
  ['2026-11-01T05:30:00Z', '01/Nov/2026, 01:30 EDT'],
  ['2026-11-01T06:30:00Z', '01/Nov/2026, 01:30 EST'],
  ['2026-09-05T21:07:59+03:00', '05/Sep/2026, 14:07 EDT'],
]) {
  assert.equal(formatDateTime(value), expected);
  assert.equal(formatDateTime(new Date(value)), expected);
  assert.equal(formatTime(value), expected.split(', ')[1]);
  assert.equal(formatTime(value, false), expected.split(', ')[1].slice(0,5));
}
for (const value of [null, undefined, '', 'invalid']) {
  assert.equal(formatDateTime(value), '—');
  assert.equal(formatTime(value), '—');
}
let message;
const input = { value: '31/Feb/2026', setCustomValidity(value) { message = value; } };
const form = { querySelectorAll() { return [input]; }, reportValidity() { return !message; } };
assert.equal(validateDateInputs(form), false);
input.value = '28/Feb/2026';
assert.equal(validateDateInputs(form), true);
input.value = '';
assert.equal(validateDateInputs(form), true);
console.log('Date formatting and validation checks passed');

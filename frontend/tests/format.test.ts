import test from 'node:test';
import assert from 'node:assert/strict';
import {
  emptyReasonText,
  expiryLabel,
  formatDateTimeSG,
  monthHeading,
  parseInstant,
  cadenceLabel,
  inputStatusLabel,
} from '../src/lib/format.ts';
import { dict } from '../src/i18n/zh-CN.ts';

test('parseInstant rejects non-Z timestamps', () => {
  assert.throws(() => parseInstant('2026-10-24T12:00:00+08:00'));
  assert.throws(() => parseInstant('2026-10-24 12:00:00Z'));
  assert.ok(parseInstant('2026-10-24T12:00:00Z') instanceof Date);
});

test('expiry equality is not expired; strictly after is expired; null is unknown', () => {
  const t = '2026-10-31T12:00:00Z';
  assert.equal(expiryLabel(t, '2026-10-31T12:00:00Z'), 'current');
  assert.equal(expiryLabel(t, '2026-10-31T12:00:01Z'), 'expired');
  assert.equal(expiryLabel(t, '2026-10-31T11:59:59Z'), 'current');
  assert.equal(expiryLabel(null, t), 'unknown');
});

test('Singapore presentation is fixed regardless of host clock', () => {
  assert.equal(formatDateTimeSG('2026-10-24T12:00:00Z'), '2026-10-24 20:00 (UTC+8)');
  assert.equal(formatDateTimeSG('2026-10-24T20:30:00Z'), '2026-10-25 04:30 (UTC+8)');
});

test('month heading renders UTC calendar month', () => {
  assert.equal(monthHeading('2026-10-24'), '2026 年 10 月');
  assert.equal(monthHeading('2025-12-01'), '2025 年 12 月');
});

test('threshold explanation carries the verified prefix only when inputs verified', () => {
  const verified = emptyReasonText({ input_status: 'verified' }, 'threshold_unmet', dict);
  assert.ok(verified.startsWith(dict['empty.verifiedPrefix']));
  assert.ok(verified.includes(dict['empty.threshold']));
  const partial = emptyReasonText({ input_status: 'partial' }, 'threshold_unmet', dict);
  assert.ok(!partial.includes('输入已核验'));
  assert.equal(emptyReasonText({ input_status: 'verified' }, 'input_unavailable', dict), dict['empty.inputUnavailable']);
  assert.equal(emptyReasonText({ input_status: 'unknown' }, 'unknown', dict), dict['empty.unknown']);
});

test('dictionary lookups for cadence and input status', () => {
  assert.equal(cadenceLabel('weekly', dict), '周报');
  assert.equal(cadenceLabel('daily', dict), '日报');
  assert.equal(cadenceLabel('monthly', dict), '月报');
  assert.equal(inputStatusLabel('verified', dict), '输入已核验');
  assert.equal(inputStatusLabel('partial', dict), '输入部分可用');
  assert.equal(inputStatusLabel('unknown', dict), '输入状态未知');
});

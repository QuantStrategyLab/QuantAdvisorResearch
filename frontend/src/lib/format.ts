import type { Cadence, InputStatus, Summary } from './data/types.ts';
import type { UiDictionary } from '../i18n/zh-CN.ts';

const ISO_Z = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

export function parseInstant(iso: string): Date {
  if (!ISO_Z.test(iso)) {
    throw new Error(`Timestamp "${iso}" is not a normalized RFC 3339 Z instant`);
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new Error(`Timestamp "${iso}" is unparseable`);
  return d;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

// Human presentation is fixed to Asia/Singapore (UTC+8) regardless of the
// reader's clock; the machine-readable value stays in <time datetime>.
export function formatDateTimeSG(iso: string): string {
  const d = parseInstant(iso);
  const sg = new Date(d.getTime() + 8 * 3600 * 1000);
  return (
    `${sg.getUTCFullYear()}-${pad(sg.getUTCMonth() + 1)}-${pad(sg.getUTCDate())} ` +
    `${pad(sg.getUTCHours())}:${pad(sg.getUTCMinutes())} (UTC+8)`
  );
}

export function formatCalendarDate(asOf: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) {
    throw new Error(`Date "${asOf}" is not a YYYY-MM-DD calendar date`);
  }
  return asOf;
}

export function monthHeading(asOf: string): string {
  const [year, month] = asOf.split('-').map(Number);
  return `${year} 年 ${month} 月`;
}

export function cadenceLabel(cadence: Cadence, d: UiDictionary): string {
  return d[`cadence.${cadence}`];
}

export function inputStatusLabel(status: InputStatus, d: UiDictionary): string {
  if (status === 'verified') return d['meta.inputVerified'];
  if (status === 'partial') return d['meta.inputPartial'];
  return d['meta.inputUnknown'];
}

export type ExpiryLabel = 'current' | 'expired' | 'unknown';

// Strictly-after means expired; equality is not expired; null is unknown.
export function expiryLabel(expiresAt: string | null, evaluatedAt: string): ExpiryLabel {
  if (expiresAt === null) return 'unknown';
  const exp = parseInstant(expiresAt);
  const now = parseInstant(evaluatedAt);
  return now.getTime() > exp.getTime() ? 'expired' : 'current';
}

export function expiryLabelText(label: ExpiryLabel, d: UiDictionary): string {
  if (label === 'expired') return d['validity.expired'];
  if (label === 'unknown') return d['validity.unknown'];
  return d['validity.current'];
}

export function emptyReasonText(
  summary: Pick<Summary, 'input_status'>,
  reason: 'threshold_unmet' | 'input_unavailable' | 'unknown',
  d: UiDictionary,
): string {
  if (reason === 'threshold_unmet') {
    const prefix = summary.input_status === 'verified' ? d['empty.verifiedPrefix'] : '';
    return `${prefix}${d['empty.threshold']}`;
  }
  if (reason === 'input_unavailable') return d['empty.inputUnavailable'];
  return d['empty.unknown'];
}

export function localized(value: { 'zh-CN': string }, locale: 'zh-CN' | 'en'): string {
  if (locale === 'en') {
    const en = (value as Record<string, unknown>)['en'];
    if (typeof en === 'string' && en.length > 0) return en;
  }
  return value['zh-CN'];
}

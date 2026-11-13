import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { ContractError, schemaSource } from './loadBundle.ts';
import { canonicalUrl } from '../routes.ts';
import { parseInstant } from '../format.ts';
import type {
  ArchiveDoc,
  FeedDoc,
  IndexDoc,
  ManifestDoc,
  ReportDoc,
  SiteBundle,
  Summary,
} from './types.ts';

const SCHEMA_BASE =
  'https://quantstrategylab.github.io/QuantAdvisorResearch/schemas/site/1.0.0';
const SCHEMA_NAMES = ['common', 'index', 'archive', 'report', 'feed', 'manifest'] as const;

export const SUPPORTED_CONTRACT_VERSION = '1.0.0';

function createAjv() {
  const ajv = new Ajv2020({
    allErrors: true,
    // Mutation and coercion protections per ARCHITECTURE.md:
    coerceTypes: false,
    useDefaults: false,
    removeAdditional: false,
    strictRequired: true,
    // The pinned 1.0.0 schemas apply array keywords inside conditional
    // branches without repeating "type": "array"; accept them verbatim
    // instead of editing the contract copy.
    strictTypes: false,
  });
  addFormats(ajv);
  for (const name of SCHEMA_NAMES) {
    ajv.addSchema(JSON.parse(schemaSource(name)));
  }
  return ajv;
}

export function guardContractVersion(doc: { contract_version?: unknown }, source: string): void {
  if (doc.contract_version !== SUPPORTED_CONTRACT_VERSION) {
    throw new ContractError(
      `Unsupported contract version ${JSON.stringify(doc.contract_version)} in ${source}; only "${SUPPORTED_CONTRACT_VERSION}" renders`,
    );
  }
}

export function validateDocument<T>(
  ajv: ReturnType<typeof createAjv>,
  kind: (typeof SCHEMA_NAMES)[number],
  doc: unknown,
  source: string,
): T {
  const validate = ajv.getSchema(`${SCHEMA_BASE}/${kind}.schema.json`);
  if (!validate) throw new ContractError(`Schema for kind "${kind}" is not registered`);
  if (!validate(doc)) {
    const detail = (validate.errors ?? [])
      .map((e) => `${e.instancePath || source}: ${e.message}`)
      .join('; ');
    throw new ContractError(`${source} failed ${kind} schema validation: ${detail}`);
  }
  return doc as T;
}

export function createValidator() {
  return createAjv();
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(',')}}`;
}

function walkLocalized(node: unknown, onMissing: (path: string) => void, pathSoFar = '$'): void {
  if (Array.isArray(node)) {
    node.forEach((item, i) => walkLocalized(item, onMissing, `${pathSoFar}[${i}]`));
    return;
  }
  if (node !== null && typeof node === 'object') {
    const keys = Object.keys(node as Record<string, unknown>).sort().join(',');
    if (keys === 'en,zh-CN') {
      const en = (node as Record<string, unknown>).en;
      if (en === null) onMissing(pathSoFar);
      return;
    }
    for (const key of Object.keys(node as Record<string, unknown>)) {
      walkLocalized((node as Record<string, unknown>)[key], onMissing, `${pathSoFar}.${key}`);
    }
  }
}

interface SharedEnvelopeFields {
  release_id: string;
  built_at: string;
  default_locale: string;
  locales: string[];
}

export function validateBundleSemantics(
  docs: Pick<SiteBundle, 'manifest' | 'index' | 'archive' | 'feed' | 'reports'>,
): void {
  const problems: string[] = [];
  const { manifest, index, archive, feed, reports } = docs;

  // 1. One release across all five kinds.
  const envelopes: Array<[string, SharedEnvelopeFields]> = [
    ['manifest', manifest],
    ['index', index],
    ['archive', archive],
    ['feed', feed],
    ...[...reports.entries()].map(([p, d]) => [`reports/${p}`.replace('reports/reports/', 'reports/'), d] as [string, SharedEnvelopeFields]),
  ];
  for (const [, doc] of envelopes) {
    if (
      doc.release_id !== manifest.release_id ||
      doc.built_at !== manifest.built_at ||
      doc.default_locale !== manifest.default_locale ||
      canonicalJson(doc.locales) !== canonicalJson(manifest.locales)
    ) {
      problems.push('Envelope fields (release_id/built_at/locales) differ from the manifest');
      break;
    }
  }

  // 2. Summary identity rules.
  const checkSummary = (s: Summary, where: string) => {
    if (s.id !== `${s.as_of}-${s.cadence}`) {
      problems.push(`${where}: id "${s.id}" does not match as_of+cadence`);
    }
    if (s.route !== `${s.id}-model-recommendations.html`) {
      problems.push(`${where}: route "${s.route}" does not match id "${s.id}"`);
    }
  };
  if (index.data.latest) checkSummary(index.data.latest, 'index.latest');
  index.data.recent.forEach((s, i) => checkSummary(s, `index.recent[${i}]`));
  archive.data.reports.forEach((s, i) => checkSummary(s, `archive.reports[${i}]`));
  for (const [path, doc] of reports) {
    checkSummary(doc.data.summary, `report ${path}`);
    if (path !== `reports/${doc.data.summary.id}.json`) {
      problems.push(`Report file "${path}" does not match summary id "${doc.data.summary.id}"`);
    }
  }

  // 3. Archive uniqueness, order and file membership.
  const archiveIds = new Set<string>();
  const archiveRoutes = new Set<string>();
  let prevAsOf: string | null = null;
  for (const s of archive.data.reports) {
    if (archiveIds.has(s.id)) problems.push(`Duplicate archive id "${s.id}"`);
    archiveIds.add(s.id);
    if (archiveRoutes.has(s.route)) problems.push(`Duplicate archive route "${s.route}"`);
    archiveRoutes.add(s.route);
    if (prevAsOf !== null && s.as_of > prevAsOf) {
      problems.push(`Archive order violation: "${s.as_of}" follows "${prevAsOf}"`);
    }
    prevAsOf = s.as_of;
    const file = `reports/${s.id}.json`;
    if (!reports.has(file)) problems.push(`Archive entry "${s.id}" has no report file`);
    const listed = manifest.data.files.some((f) => f.path === file);
    if (!listed) problems.push(`Manifest is missing report file "${file}" for archive entry "${s.id}"`);
  }
  for (const file of reports.keys()) {
    if (!archive.data.reports.some((s) => `reports/${s.id}.json` === file)) {
      problems.push(`Report file "${file}" has no matching archive entry`);
    }
  }

  // 4. Repeated summaries are deeply equal.
  const summaryIndex = new Map<string, string>();
  const rememberSummary = (s: Summary, where: string) => {
    const json = canonicalJson(s);
    const existing = summaryIndex.get(s.id);
    if (existing === undefined) summaryIndex.set(s.id, json);
    else if (existing !== json) problems.push(`Summaries for "${s.id}" differ (${where})`);
  };
  archive.data.reports.forEach((s, i) => rememberSummary(s, `archive[${i}]`));
  if (index.data.latest) rememberSummary(index.data.latest, 'index.latest');
  index.data.recent.forEach((s, i) => rememberSummary(s, `index.recent[${i}]`));
  for (const [path, doc] of reports) rememberSummary(doc.data.summary, path);

  // 5. Index membership and validity semantics.
  if (index.data.latest && !archiveIds.has(index.data.latest.id)) {
    problems.push('index.latest id is not present in the archive');
  }
  for (const s of index.data.recent) {
    if (!archiveIds.has(s.id)) problems.push(`index.recent id "${s.id}" is not present in the archive`);
    if (index.data.latest && s.id === index.data.latest.id) {
      problems.push('index.recent must exclude the latest report');
    }
  }
  const validity = index.data.latest_validity;
  if (validity === 'none' && index.data.latest !== null) {
    problems.push('latest_validity "none" requires a null latest');
  }
  if (validity !== 'none') {
    if (index.data.latest === null) {
      problems.push(`latest_validity "${validity}" requires a latest summary`);
    } else {
      const evaluated = parseInstant(index.data.evaluated_at).getTime();
      const expires = index.data.latest.expires_at === null
        ? null
        : parseInstant(index.data.latest.expires_at).getTime();
      if (validity === 'current' && (expires === null || !(evaluated <= expires))) {
        problems.push('latest_validity "current" requires non-null expiry and evaluated_at <= expires_at');
      }
      if (validity === 'expired' && (expires === null || !(evaluated > expires))) {
        problems.push('latest_validity "expired" requires non-null expiry and evaluated_at > expires_at');
      }
      if (validity === 'unknown' && expires !== null) {
        problems.push('latest_validity "unknown" is only for reports without expiry evidence');
      }
    }
  }

  // 6. Feed membership, order and GUID binding.
  const feedMaxIndex = Math.min(feed.data.items.length, archive.data.reports.length);
  if (feed.data.items.length > 20) problems.push('feed has more than 20 items');
  feed.data.items.forEach((item, i) => {
    if (item.route !== `${item.report_id}-model-recommendations.html`) {
      problems.push(`feed item ${i}: route does not match report_id`);
    }
    if (item.guid !== canonicalUrl(item.route)) {
      problems.push(`feed item ${i}: guid is not the canonical report URL`);
    }
    if (!archiveIds.has(item.report_id)) problems.push(`feed item ${i}: report_id absent from archive`);
    const expected = archive.data.reports[i];
    if (i < feedMaxIndex && expected && expected.id !== item.report_id) {
      problems.push(`feed item ${i}: order does not follow the archive's newest-first list`);
    }
  });

  // 7. Report summary/card consistency, ranks, windows.
  const HORIZONS = ['long', 'medium', 'short'] as const;
  for (const [path, doc] of reports) {
    for (const h of HORIZONS) {
      const symbols = doc.data.summary.horizons[h].symbols;
      const cards = doc.data.cards[h];
      if (symbols.length !== cards.length) {
        problems.push(`${path} horizon ${h}: card count differs from summary symbols`);
      } else {
        for (let i = 0; i < cards.length; i += 1) {
          if (cards[i].symbol !== symbols[i]) {
            problems.push(`${path} horizon ${h}: card ${i} symbol differs from summary order`);
          }
          if (cards[i].rank !== i + 1) {
            problems.push(`${path} horizon ${h}: ranks are not contiguous from 1`);
          }
        }
      }
      const emptyReason = doc.data.summary.horizons[h].empty_reason;
      if (symbols.length > 0 && emptyReason !== null) {
        problems.push(`${path} horizon ${h}: populated column has an empty reason`);
      }
    }
  }

  // 8. Locale completeness: en listed means every localized field present.
  if (manifest.locales.includes('en')) {
    const targets: Array<[string, unknown]> = [
      ['manifest', manifest.data],
      ['index', index.data],
      ['archive', archive.data],
      ['feed', feed.data],
      ...[...reports.entries()].map(([p, d]) => [p, d.data] as [string, unknown]),
    ];
    for (const [name, data] of targets) {
      walkLocalized(data, (where) => problems.push(`${name}: locales include "en" but ${where} has null English text`));
    }
  }

  if (problems.length > 0) {
    throw new ContractError(`Bundle semantic validation failed: ${problems.join(' | ')}`);
  }
}

export { canonicalJson };

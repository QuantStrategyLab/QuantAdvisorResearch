import {
  ContractError,
  readBundleFileRaw,
  readManifestRaw,
  resolveBundleDir,
} from './loadBundle.ts';
import { checkManifestStructure, checkPayloadIntegrity } from './integrity.ts';
import {
  createValidator,
  guardContractVersion,
  validateBundleSemantics,
  validateDocument,
} from './validate.ts';
import type { ArchiveDoc, FeedDoc, IndexDoc, ManifestDoc, ReportDoc, SiteBundle } from './types.ts';

const CACHE_KEY = Symbol.for('quantadvisor.siteBundle');

interface CacheShape {
  dir: string;
  bundle: SiteBundle;
}

function parseJson(buffer: Buffer, source: string): Record<string, unknown> {
  try {
    return JSON.parse(buffer.toString('utf8')) as Record<string, unknown>;
  } catch (error) {
    throw new ContractError(`${source} is not valid JSON: ${String(error)}`);
  }
}

export function loadSiteBundle(bundleDir: string = resolveBundleDir()): SiteBundle {
  const globalCache = globalThis as Record<symbol, CacheShape | undefined>;
  if (globalCache[CACHE_KEY]?.dir === bundleDir) return globalCache[CACHE_KEY]!.bundle;

  const ajv = createValidator();

  const manifestRaw = readManifestRaw(bundleDir);
  const manifestDoc = parseJson(manifestRaw, 'manifest.json');
  guardContractVersion(manifestDoc, 'manifest.json');
  const manifest = validateDocument<ManifestDoc>(ajv, 'manifest', manifestDoc, 'manifest.json');
  if (manifest.kind !== 'manifest') throw new ContractError('manifest.json has the wrong kind');
  checkManifestStructure(manifest);

  const rawByPath = new Map<string, Buffer>();
  const parsedByKind = new Map<string, Record<string, unknown>>();
  for (const entry of manifest.data.files) {
    const raw = readBundleFileRaw(bundleDir, entry.path);
    rawByPath.set(entry.path, raw);
    parsedByKind.set(entry.path, parseJson(raw, entry.path));
  }
  checkPayloadIntegrity(manifest, rawByPath);

  let index: IndexDoc | null = null;
  let archive: ArchiveDoc | null = null;
  let feed: FeedDoc | null = null;
  const reports = new Map<string, ReportDoc>();
  for (const entry of manifest.data.files) {
    const doc = parsedByKind.get(entry.path)!;
    guardContractVersion(doc, entry.path);
    if (entry.kind === 'index') {
      index = validateDocument<IndexDoc>(ajv, 'index', doc, entry.path);
    } else if (entry.kind === 'archive') {
      archive = validateDocument<ArchiveDoc>(ajv, 'archive', doc, entry.path);
    } else if (entry.kind === 'feed') {
      feed = validateDocument<FeedDoc>(ajv, 'feed', doc, entry.path);
    } else {
      reports.set(entry.path, validateDocument<ReportDoc>(ajv, 'report', doc, entry.path));
    }
  }
  if (!index || !archive || !feed) {
    throw new ContractError('Bundle is missing index, archive or feed payload');
  }
  for (const [path, doc] of reports) {
    const expectedPath = `reports/${doc.data.summary.id}.json`;
    if (path !== expectedPath) throw new ContractError(`Report "${path}" kind/path mismatch`);
  }

  const bundle: SiteBundle = { bundleDir, manifest, index, archive, feed, reports };
  validateBundleSemantics(bundle);

  globalCache[CACHE_KEY] = { dir: bundleDir, bundle };
  return bundle;
}

export function reportSlugToBundlePath(slug: string): string {
  const suffix = '-model-recommendations';
  if (!slug.endsWith(suffix)) throw new ContractError(`Unexpected report slug "${slug}"`);
  return `reports/${slug.slice(0, -suffix.length)}.json`;
}

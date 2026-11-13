import { createHash } from 'node:crypto';
import { ContractError } from './loadBundle.ts';
import type { ManifestDoc } from './types.ts';

export function sha256Hex(buffer: Buffer): string {
  return createHash('sha256').update(buffer).digest('hex');
}

const KIND_BY_PATH: Record<string, 'index' | 'archive' | 'feed'> = {
  'index.json': 'index',
  'archive.json': 'archive',
  'feed.json': 'feed',
};

export function checkManifestStructure(manifest: ManifestDoc): void {
  const { files, report_count } = manifest.data;
  const seen = new Set<string>();
  for (const entry of files) {
    if (seen.has(entry.path)) throw new ContractError(`Duplicate manifest path "${entry.path}"`);
    seen.add(entry.path);
    if (entry.path === 'manifest.json') {
      throw new ContractError('The manifest must not list itself');
    }
    if (entry.path.startsWith('reports/')) {
      if (entry.kind !== 'report') throw new ContractError(`Report file "${entry.path}" has kind "${entry.kind}"`);
    } else {
      const expected = KIND_BY_PATH[entry.path];
      if (!expected || entry.kind !== expected) {
        throw new ContractError(`Manifest entry "${entry.path}" kind mismatch`);
      }
    }
  }
  if (files.length !== report_count + 3) {
    throw new ContractError(
      `Manifest lists ${files.length} files but report_count is ${report_count}; expected ${report_count + 3}`,
    );
  }
  for (const kind of ['index', 'archive', 'feed'] as const) {
    const n = files.filter((f) => f.kind === kind).length;
    if (n !== 1) throw new ContractError(`Expected exactly one "${kind}" file, found ${n}`);
  }
}

export function checkPayloadIntegrity(
  manifest: ManifestDoc,
  rawByPath: Map<string, Buffer>,
): void {
  const problems: string[] = [];
  for (const entry of manifest.data.files) {
    const raw = rawByPath.get(entry.path);
    if (!raw) {
      problems.push(`Missing bundle file "${entry.path}" listed in the manifest`);
      continue;
    }
    if (raw.byteLength !== entry.bytes) {
      problems.push(`Byte length mismatch for "${entry.path}"`);
    }
    if (sha256Hex(raw) !== entry.sha256) {
      problems.push(`SHA-256 mismatch for "${entry.path}"`);
    }
  }
  if (problems.length > 0) throw new ContractError(problems.join('; '));
}

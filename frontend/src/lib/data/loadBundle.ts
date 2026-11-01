import { readFileSync } from 'node:fs';
import path from 'node:path';

export class ContractError extends Error {}

const ALLOWED_PATH = /^(index|archive|feed)\.json$|^reports\/\d{4}-\d{2}-\d{2}-(daily|weekly|monthly)\.json$/;

declare const __QAR_FRONTEND_ROOT__: string | undefined;
// Vite injects the frontend package root at build time; plain Node runs
// (tests) execute with the frontend directory as the working directory.
const FRONTEND_ROOT =
  typeof __QAR_FRONTEND_ROOT__ !== 'undefined'
    ? __QAR_FRONTEND_ROOT__
    : path.resolve(process.cwd());
const DEFAULT_BUNDLE_DIR = path.join(FRONTEND_ROOT, 'tests/fixtures/bundles/populated-current');

export function resolveBundleDir(): string {
  const fromEnv = process.env.ADVISOR_BUNDLE_DIR;
  if (!fromEnv) return DEFAULT_BUNDLE_DIR;
  return path.resolve(process.cwd(), fromEnv);
}

// Strict allowlist plus containment: nothing outside the staged bundle is read.
export function readBundleFileRaw(bundleDir: string, relPath: string): Buffer {
  if (
    !ALLOWED_PATH.test(relPath) ||
    relPath.includes('..') ||
    relPath.includes('\\') ||
    path.isAbsolute(relPath) ||
    relPath.includes('?') ||
    relPath.includes('#')
  ) {
    throw new ContractError(`Path "${relPath}" is not in the bundle allowlist`);
  }
  const root = path.resolve(bundleDir);
  const full = path.resolve(root, relPath);
  if (full !== root && !full.startsWith(root + path.sep)) {
    throw new ContractError(`Path "${relPath}" escapes the bundle directory`);
  }
  try {
    return readFileSync(full);
  } catch (error) {
    throw new ContractError(`Bundle file "${relPath}" could not be read: ${String(error)}`);
  }
}

export function readManifestRaw(bundleDir: string): Buffer {
  try {
    return readFileSync(path.resolve(bundleDir, 'manifest.json'));
  } catch (error) {
    throw new ContractError(`manifest.json could not be read: ${String(error)}`);
  }
}

export function schemaSource(name: string): string {
  return readFileSync(path.join(FRONTEND_ROOT, 'schema-copies/1.0.0', `${name}.schema.json`), 'utf8');
}

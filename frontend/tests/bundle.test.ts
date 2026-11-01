import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { cp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSiteBundle } from '../src/lib/data/bundle.ts';
import { ContractError, readBundleFileRaw } from '../src/lib/data/loadBundle.ts';
import { sha256Hex } from '../src/lib/data/integrity.ts';

const FIXTURES = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures/bundles',
);

function serialize(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

async function cloneBundle(name: string): Promise<string> {
  const dir = mkdtempSync(path.join(os.tmpdir(), `qar-bundle-${name}-`));
  const target = path.join(dir, name);
  await cp(path.join(FIXTURES, name), target, { recursive: true });
  return target;
}

function patchPayload(bundleDir: string, relPath: string, transform: (doc: any) => void): void {
  const full = path.join(bundleDir, relPath);
  const doc = JSON.parse(readFileSync(full, 'utf8'));
  transform(doc);
  const bytes = Buffer.from(serialize(doc), 'utf8');
  writeFileSync(full, bytes);
  const manifestPath = path.join(bundleDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const entry = manifest.data.files.find((f: any) => f.path === relPath);
  if (entry) {
    entry.sha256 = sha256Hex(bytes);
    entry.bytes = bytes.byteLength;
  }
  writeFileSync(manifestPath, serialize(manifest));
}

function patchManifest(bundleDir: string, transform: (manifest: any) => void): void {
  const manifestPath = path.join(bundleDir, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  transform(manifest);
  writeFileSync(manifestPath, serialize(manifest));
}

test('positive fixtures load without mutation', () => {
  const populated = loadSiteBundle(path.join(FIXTURES, 'populated-current'));
  assert.equal(populated.archive.data.reports.length, 3);
  assert.equal(populated.reports.size, 3);
  assert.equal(populated.index.data.latest?.id, '2026-10-24-weekly');
  assert.equal(populated.index.data.latest_validity, 'current');

  const empty = loadSiteBundle(path.join(FIXTURES, 'empty-site'));
  assert.equal(empty.index.data.latest, null);
  assert.equal(empty.index.data.latest_validity, 'none');

  const expired = loadSiteBundle(path.join(FIXTURES, 'expired-empty'));
  assert.equal(expired.index.data.latest_validity, 'expired');

  // Loading is idempotent and non-mutating: re-parse equals first bytes.
  const raw = readFileSync(path.join(FIXTURES, 'populated-current/index.json'), 'utf8');
  assert.deepEqual(JSON.parse(raw), JSON.parse(raw));
});

async function expectFailure(name: string, relPath: string, transform: (doc: any) => void, matcher?: RegExp): Promise<void> {
  const dir = await cloneBundle(name);
  try {
    patchPayload(dir, relPath, transform);
    assert.throws(() => loadSiteBundle(dir), matcher ?? ContractError);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test('tampered payload hash fails integrity', async () => {
  const dir = await cloneBundle('populated-current');
  try {
    patchManifest(dir, (m) => {
      m.data.files[1].sha256 = '0'.repeat(64);
    });
    assert.throws(() => loadSiteBundle(dir), /SHA-256 mismatch/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('unsupported contract version is rejected before rendering', async () => {
  await expectFailure(
    'populated-current',
    'index.json',
    (doc) => {
      doc.contract_version = '2.0.0';
    },
    /Unsupported contract version/,
  );
});

test('unknown property fails closed schema', async () => {
  await expectFailure(
    'populated-current',
    'index.json',
    (doc) => {
      doc.data.extra_field = 1;
    },
    /schema validation/,
  );
});

test('non-Z timestamp fails format validation', async () => {
  await expectFailure(
    'populated-current',
    'index.json',
    (doc) => {
      doc.data.evaluated_at = '2026-10-25T08:00:00+08:00';
    },
    /schema validation/,
  );
});

test('recent may not include latest', async () => {
  await expectFailure(
    'populated-current',
    'index.json',
    (doc) => {
      doc.data.recent = [doc.data.latest, ...doc.data.recent];
    },
    /must exclude the latest/,
  );
});

test('archive order must stay newest first', async () => {
  await expectFailure(
    'populated-current',
    'archive.json',
    (doc) => {
      doc.data.reports.reverse();
    },
    /order violation/,
  );
});

test('id and route must agree with as_of and cadence', async () => {
  await expectFailure(
    'populated-current',
    'archive.json',
    (doc) => {
      doc.data.reports[0].route = '2026-10-24-daily-model-recommendations.html';
    },
    /route .* does not match id/,
  );
});

test('manifest count must equal report_count + 3', async () => {
  const dir = await cloneBundle('populated-current');
  try {
    patchManifest(dir, (m) => {
      m.data.files = m.data.files.filter((f: any) => f.kind !== 'report');
    });
    assert.throws(() => loadSiteBundle(dir), /Manifest lists .* expected|has no matching archive entry|missing report file/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('repeated summaries must be deeply equal', async () => {
  await expectFailure(
    'populated-current',
    'reports/2026-10-24-weekly.json',
    (doc) => {
      doc.data.summary.title['zh-CN'] = '改名后的摘要';
    },
    /differ/,
  );
});

test('ranks must be contiguous from 1', async () => {
  await expectFailure(
    'populated-current',
    'reports/2026-10-24-weekly.json',
    (doc) => {
      doc.data.cards.long[1].rank = 5;
    },
    /contiguous/,
  );
});

test('card symbols must match summary horizon order', async () => {
  await expectFailure(
    'populated-current',
    'reports/2026-10-24-weekly.json',
    (doc) => {
      doc.data.cards.short[0].symbol = 'SPY';
    },
    /differs from summary/,
  );
});

test('mixed release ids across payloads fail', async () => {
  await expectFailure(
    'populated-current',
    'archive.json',
    (doc) => {
      doc.release_id = '00000000-0000-4000-8000-000000000000';
    },
    /release_id/,
  );
});

test('locales with en require complete English text', async () => {
  const dir = await cloneBundle('populated-current');
  try {
    patchPayload(dir, 'index.json', (doc) => {
      doc.locales = ['zh-CN', 'en'];
    });
    patchManifest(dir, (m) => {
      m.locales = ['zh-CN', 'en'];
    });
    assert.throws(() => loadSiteBundle(dir), /null English text|differ from the manifest/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('current validity requires non-null expiry', async () => {
  await expectFailure(
    'populated-current',
    'index.json',
    (doc) => {
      doc.data.latest.expires_at = null;
    },
    /schema validation|current.*non-null|differ/,
  );
});

test('duplicate symbols within one horizon fail schema', async () => {
  await expectFailure(
    'populated-current',
    'archive.json',
    (doc) => {
      doc.data.reports[0].legacy_summary_symbols = ['NVDA', 'NVDA'];
    },
    /schema validation/,
  );
});

test('manifest self-listing and duplicates are rejected', async () => {
  const dir = await cloneBundle('populated-current');
  try {
    patchManifest(dir, (m) => {
      m.data.files.push({ ...m.data.files[0] });
    });
    assert.throws(() => loadSiteBundle(dir), /Duplicate manifest path|lists itself|expected 6/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('path loader rejects traversal and non-allowlisted paths', () => {
  const dir = path.join(FIXTURES, 'populated-current');
  assert.throws(() => readBundleFileRaw(dir, '../escape.json'), ContractError);
  assert.throws(() => readBundleFileRaw(dir, 'reports/../index.json'), ContractError);
  assert.throws(() => readBundleFileRaw(dir, '/etc/passwd'), ContractError);
  assert.throws(() => readBundleFileRaw(dir, 'manifest.json'), ContractError);
  assert.throws(() => readBundleFileRaw(dir, 'index.json?x=1'), ContractError);
});

test('feed guid must equal the canonical report URL', async () => {
  await expectFailure(
    'populated-current',
    'feed.json',
    (doc) => {
      doc.data.items[0].guid = 'https://example.com/other.html';
    },
    /schema validation|canonical/,
  );
});

# QuantAdvisorResearch frontend

Astro static renderer for the versioned site JSON contract (`contract_version: "1.0.0"`).
It builds the Chinese Latest, Archive, Report and 404 pages from a validated bundle.
The frontend never recalculates ranks, gates or timestamps; it only renders contract data.

## Requirements

- Node.js `>= 20.17.0` (development verified on Node 26).
- Dependencies are pinned in `package.json`; install with `npm ci` or `npm install`.

## Build and preview

```bash
npm install
npm run build          # renders dist/ from the default fixture bundle
npm run preview        # serves the built site locally
```

The bundle directory is resolved from the `ADVISOR_BUNDLE_DIR` environment variable and
defaults to `tests/fixtures/bundles/populated-current`. Any staged bundle with the layout
below can be rendered:

```bash
ADVISOR_BUNDLE_DIR=tests/fixtures/bundles/empty-site npm run build
ADVISOR_BUNDLE_DIR=tests/fixtures/bundles/expired-empty npm run build
```

Expected bundle layout:

```text
manifest.json
index.json
archive.json
feed.json
reports/{YYYY-MM-DD}-{daily|weekly|monthly}.json
```

A missing or non-conforming bundle fails the build before any page is emitted; the
renderer never fabricates reports, counts, dates or freshness states.

## Tests

```bash
npm test               # node --test tests/format.test.ts tests/bundle.test.ts
```

The suite covers time/format helpers, manifest integrity, schema validation and every
cross-file semantic rule, each with a positive fixture and a mutated negative case.
Fixture bundles are synthetic data only (`node scripts/make-fixtures.mjs` regenerates
them) and must never be used as production input.

## Schema copies under `schema-copies/`

`schema-copies/1.0.0/*.schema.json` are verbatim local copies of the contract in
`ARCHITECTURE.md`, so this package validates offline without network access. The
normative schemas are owned by the backend publisher at repository-root
`schemas/site/1.0.0/` (the directory name here differs because the root `.gitignore`
excludes any `site/` path); when that directory lands, the copies here must be
byte-compared against it and any drift fails the contract review. Do not edit one
side alone.

## Deliberately out of scope for this slice

- `feed.xml` serialization stays produced by the existing Python publisher; the frontend
  nav/RSS link points at the legacy URL until a build-time endpoint replaces it.
- English routes (`en/…`), sitemap, JSON-LD and hreflang generation.
- Playwright visual checks and axe accessibility matrices.
- Any workflow, deployment or Python publisher change.

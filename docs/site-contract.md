# Site Data Contract 1.0.0

The site data contract publishes advisory reports as versioned JSON documents for
a static frontend. It is additive: the existing HTML, RSS, `reports_index.json`
and manifest publication path is unchanged, and this contract is not wired into
the scheduled publish workflow.

The advisory report contract in [advisory-contract.md](advisory-contract.md)
still defines report fields and policy. This document defines only how selected
reports are projected into site documents.

## Artifacts

A release writes these files under the site root:

```text
data/v1/manifest.json
data/v1/index.json
data/v1/archive.json
data/v1/feed.json
data/v1/reports/<YYYY-MM-DD>-<cadence>.json
```

`<cadence>` is `daily`, `weekly` or `monthly`. A report's identifier is
`<as_of>-<cadence>`, and its unchanged HTML route is
`<identifier>-model-recommendations.html`.

JSON Schemas (Draft 2020-12) live in `schemas/site/1.0.0/`:

```text
common.schema.json
index.schema.json
archive.schema.json
report.schema.json
feed.schema.json
manifest.schema.json
```

Every payload starts with the same envelope:

```text
$schema           schema URL under schemas/site/1.0.0/
contract_version  1.0.0
kind              index | archive | report | feed | manifest
release_id        UUID shared by every file in the release
built_at          RFC 3339 UTC timestamp of the build
default_locale    zh-CN
locales           exact available locales
policy            research policy constants
data              kind-specific payload
```

`policy` keeps non-personalized recommendations allowed and execution,
portfolio allocation, personalized advice and account-specific advice disabled.

## Report Documents

`data/summary` carries the listing fields the frontend needs:

```text
id, route, as_of, cadence, source_schema
title, description
generated_at, reference_time, expires_at
input_status, final_recommendation_count
horizons.long|medium|short
top_themes
legacy_summary_symbols, legacy_horizon_symbols
```

- `source_schema` is the source report schema version, so v5 and v6 reports
  remain distinguishable.
- `input_status` is `verified` when every declared input checks out, `partial`
  when warnings or unavailable freshness inputs are present, and `unknown`
  otherwise.
- `final_recommendation_count` counts picks in `final_decisions`. It is `null`
  when the report has no final layer; it is never reported as zero for a
  missing layer.
- `horizons.<horizon>.empty_reason` is `null` when symbols are present,
  `threshold_unmet` when the pipeline evaluated thresholds and none passed,
  `input_unavailable` when inputs were missing or degraded, and `unknown` when
  no other reason applies.
- `legacy_summary_symbols` and `legacy_horizon_symbols` reproduce the existing
  `summary` and horizon labels. `horizons` uses ranked final picks and is the
  frontend source of truth for per-horizon cards.
- A v5 source keeps its own `reference_time` and `expires_at` values; the
  projection does not invent timestamps. A v6 source carries `reference_time`
  and `expires_at` from the report.

`data.cards.<horizon>` lists final picks in rank order:

```text
rank, symbol, name
horizon_action        recommend | watch | unknown
selection_basis       primary_horizon | long_fallback
window
business_summary, prospect_summary, risk_summary
```

`long_fallback` marks a long-horizon pick that qualified through the documented
fallback rather than primary long-context evidence. `ranks` are contiguous from
one within each horizon.

`data.lead` holds the ordered lead paragraphs (horizon conclusion, momentum
factor summary, report takeaway), and `data.disclaimer` is the public risk
notice. Both are localized text objects.

## Listing Documents

`index.json` publishes `evaluated_at`, the selected `latest` report summary (or
`null`), `latest_validity` (`current`, `expired`, `unknown` or `none`), and up
to five `recent` summaries. The latest report is the newest current report; if
every report is expired, the newest report is still listed with
`latest_validity = expired`.

`archive.json` publishes every report summary, newest first, up to 1000 entries.

`feed.json` publishes the feed title, description, home URL, feed route and the
newest 20 report items. Each item carries its report identifier, route, GUID,
title, description and the report's `generated_at` as `published_at`.

## Manifest Documents

`manifest.json` lists every payload file in the release:

```text
path, kind, sha256, bytes
```

The manifest also carries `report_count`. The file set, each digest and each
byte length are checked when the bundle is read or validated. Digests cover the
serialized site documents, so the source advisory files are never rewritten.

## Build and Validate

The module is `src/quant_advisor_research/site_contract.py`. It accepts reports
that already passed publication selection, so it reuses the existing
`require_publish_candidates` filtering instead of re-ranking reports.

Build a staging bundle:

```bash
python -m quant_advisor_research.site_contract \
  --reports output/2026-10-24-weekly.json \
  --mandatory-current output/2026-10-24-weekly.json \
  --built-at 2026-11-01T00:00:00Z \
  --evaluated-at 2026-11-01T00:00:00Z \
  --output-dir staging/site
```

`--built-at` and `--evaluated-at` are explicit so a rebuild is reproducible;
`--release-id` pins the UUID for byte-identical output. The command refuses an
empty report set unless `--allow-empty` is given.

Validate an existing bundle without network access:

```bash
python -m quant_advisor_research.site_contract --validate staging/site
```

Validation checks the JSON Schemas, the local `$ref` graph, locale rules,
manifest membership and digests, one shared release identifier, archive and feed
ordering, index membership and validity, report paths and ranks, and summary
equality between listing documents and report documents. The reader rejects
paths outside the manifest and non-finite JSON numbers.

## Offline Tests

`tests/test_site_contract.py` covers schema conformance, projection parity with
the existing publisher helpers, the golden bundle in `tests/fixtures/site/`,
cross-file semantic failures, and read/write round trips. Inputs are synthetic
fixtures under `tests/fixtures/site/inputs/`.

```bash
python -m pip install -e '.[test]'
python -m pytest -q tests/test_site_contract.py
```

## Limits

The JSON Schemas validate shape and vocabulary, not the truth of research
content. The manifest proves which bytes belong to a release after it was
built; it does not authenticate the producer. Deploying a bundle, switching the
public site to this contract, and generating HTML from it remain separate
changes.

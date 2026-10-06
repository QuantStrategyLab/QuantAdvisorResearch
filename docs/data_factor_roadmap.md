# Data Source and Factor Roadmap

[English](data_factor_roadmap.md) | [简体中文](data_factor_roadmap.zh-CN.md)

## Current Direction

`QuantAdvisorResearch` should remain the Intelligent Advisory Research System
coordinator instead of becoming a full multi-factor trading platform.

Two different research paths should stay separated:

- Backtestable/executable path: price, technical, momentum, volatility, snapshot,
  and strategy repositories that may eventually connect to broker platforms.
- Event/policy/news/AI-shadow path: less stable evidence that should only produce
  non-personalized intelligent-advisory reports and review artifacts.

For now, this repository consumes only:

- `PoliticalEventTrackingResearch` for source events and watchlists;
- `ResearchSignalContextPipelines` for medium-horizon theme context and
  long-horizon AI shadow context.

`UsEquitySnapshotPipelines`, `UsEquityStrategies`, `CryptoSnapshotPipelines`, and
`CryptoStrategies` remain independent reference material until there is enough
live evidence to justify a separate integration.

## Current Inputs

### PoliticalEventTrackingResearch

Owns the event evidence layer:

- official or semi-structured records;
- RSS/Atom feeds from durable public sources;
- alias-based ticker extraction;
- event study tooling for later review.

Stable default sources should be official records, issuer releases, regulatory
feeds, and other replayable primary sources. X, Truth Social, Longbridge login
sessions, and community content are excluded from the stable default pipeline
until they have reliable interfaces, clear permission boundaries, and saved
point-in-time artifacts.

### ResearchSignalContextPipelines

Owns reusable signal context:

- medium-horizon theme momentum (`2-12 weeks`);
- long-horizon AI shadow artifacts (`1-3 years`);
- static theme taxonomy and symbol exposures;
- saved `latest_signal.json` and `signal_history/*.json`;
- replay based on saved artifacts only.

This repository can provide background regime, theme, and risk context, but it
must not directly generate orders, target weights, or account actions.

### QuantAdvisorResearch

Owns final non-personalized intelligent-advisory research output:

- inputs: event CSV, watchlist CSV, saved AI shadow JSON, optional theme momentum, optional market confirmation CSV;
- outputs: JSON, Markdown, HTML, RSS, and optional Telegram summary;
- contract blocks orders, target weights, target share quantities, broker routing,
  account information, and suitability claims.

## Factors to Add Later

Priority order:

1. Primary policy and disclosure sources: SEC, issuer IR, White House, Federal
   Register, Congress, DoD/DOE/CHIPS, Treasury, USAspending, or SAM.gov.
2. Verified official social media: government, issuer, and executive accounts
   only when replayable and clearly attributable.
3. Financial media leads: low-confidence discovery only, never high-confidence
   recommendation evidence without primary-source confirmation.
4. Market confirmation: relative returns, abnormal volume, trend state,
   drawdown, volatility, and sector-relative moves.
5. Fundamentals and valuation: market cap, revenue growth, margins, leverage,
   earnings dates, and valuation bands.
6. Macro/risk regime: VIX, rates, dollar, credit spreads, oil, yield curve, and
   sector beta.

## 2026-10-06 input publication recovery (staged evidence)

At incident capture, the Advisor still built and published, but its checked-out
upstream inputs lagged generated artifacts. The
[earlier October 6 build](https://github.com/QuantStrategyLab/QuantAdvisorResearch/actions/runs/37460712408)
had `as_of=2026-10-03`, 42 market-confirmation rows, and zero final picks; its
warnings were `ai_signal_provenance_untrusted` and `theme_momentum_stale_as_of`.
Those gates remain unchanged.

- [x] Separate generation, protected publication, and consumer acceptance:
  RSCP's [fresh theme artifact](https://github.com/QuantStrategyLab/ResearchSignalContextPipelines/actions/runs/37132550227)
  was retained after a protected-main push rejection; PETR produced a manual
  publication handoff; the latest AI request failed without pushing files
- [x] Merge and verify [QAR #79](https://github.com/QuantStrategyLab/QuantAdvisorResearch/pull/79):
  Sunday 12:30/13:00 UTC schedules, unchanged closed-period helper and freshness contract
- [x] Review exact producer metadata, bytes, dates, and policy; merge the one-time
  theme import through [RSCP #55](https://github.com/QuantStrategyLab/ResearchSignalContextPipelines/pull/55)
  with successful required `test` checks on the actual PR head and merged main
- [x] Verify real consumption in [Weekly run 37515064136](https://github.com/QuantStrategyLab/QuantAdvisorResearch/actions/runs/37515064136):
  actual upstream commits, schema-2 theme hash, five-input digest, report/manifest
  hashes, and offline M0 report digest all match; no fixtures or date edits
- [ ] Recover trusted AI signal/manifest and accepted company-entity evidence in
  their owning workstreams; code validation fixes alone do not close these data gaps
- [ ] Confirm notification side effects of the existing publication entry point, publish, and verify the deployed report hash
- [ ] Establish recurring reviewed upstream publication; a one-time import does not close this loop

The accepted report uses the October 3 cutoff (`reference_time=2026-10-04T00:00:00Z`).
All 43 market rows are direct `yahoo_chart`, dated October 2, with 318 observations,
`price_age_days=1`, `price_observed`, and no warnings, proxy, cache, or theme fallback.
Its disjoint final lists are recommendations `MU, DELL, INTC, AMD` and watchlist
`CRWD, PANW, TSM, SMCI`; per-horizon buckets can repeat a symbol across horizons.
All eight items have zero company-source and long-AI contributions: existing theme
momentum and market-confirmation rules produce the results. All 11 source events
remain unaccepted as company evidence, and `ai_signal_provenance_untrusted` remains.

Pages and Telegram were not updated by this artifact-only acceptance run. The
existing frontend republisher only re-renders the already public archive and
cannot import this weekly artifact. The October 2 theme is stale for the October 10
report, despite its later declared expiry. Zero final picks remain valid when
evidence is insufficient. See [the recovery evidence](system_design.md#input-publication-recovery-2026-10-06)
for hashes, actual source commits, and the existing `ai_signal_score` alias semantics.

## Low-Risk Implementation Order

1. Keep public output focused on final recommendations. Preserve
   `theme_first_candidates[]` as JSON/Markdown explanation and audit material,
   not as a public buy list.
2. Improve stable real sources in `PoliticalEventTrackingResearch`: RSS, official
   releases, SEC/EDGAR, company IR, policy/procurement sources, alias maps, and
   source registry coverage.
3. Add optional market confirmation CSVs while keeping report generation working
   when the data is absent. The CSV now carries point-in-time returns, relative
   returns, abnormal volume, drawdown, volatility, `market_score`,
   `price_age_days`, `confirmation_quality`, source, row count, and warnings.
   `scripts/build_market_confirmation.py` generates it from watchlists, saved
   signal context, and theme momentum snapshots; if the free price endpoint is
   unavailable, it can retry through `--proxy-urls`,
   `--proxy-list`, `--proxy-pool-url`, or the workflow variables
   `MARKET_DATA_PROXY_URLS` / `MARKET_DATA_PROXY_POOL_URL` before falling back to
   saved theme momentum fields.
   It must not contain target weights or trade instructions.
4. Persist a lightweight price cache for market confirmation and recommendation
   review. Cache files should contain only point-in-time daily bars, source,
   update time, and no account data. GitHub Actions cache is acceptable for this
   early stage; a controlled snapshot repository or audited data provider is a
   better long-term source.
5. Keep the cross-repository contract tested with a no-network smoke run before
   treating workflow success as healthy. The smoke should build report/site
   artifacts from the three live repositories and upload artifacts for inspection.
6. Add recommendation follow-up review from cached prices and published reports.
   It should report absolute/benchmark-relative returns by horizon, not create
   new recommendations or trading targets.
7. Add event review inputs for 1/5/20/60 trading-day follow-up.
8. Add fundamentals/valuation snapshots for risk explanation, not execution.
9. Only then consider read-only references from existing snapshot repositories.

## Anti-Overfitting Rules

Long-lived advisory research should not chase only the current AI trade.

Use static, versioned taxonomy files in `ResearchSignalContextPipelines`:

```text
config/theme_taxonomy.csv
config/symbol_theme_exposure.csv
```

Rules:

1. Fix theme membership first, then observe future behavior.
2. AI may output theme bias and shadow context, but not position sizes.
3. Advisor may use theme bias and theme momentum as explanation inputs for final
   recommendations; theme candidates remain audit material by default.
4. Every taxonomy, universe, and scoring-rule change must be versioned.
5. Do not change weights just because MU, INTC, DELL, or any other name is
   currently popular.

# Data Source and Factor Roadmap

[English](data_factor_roadmap.md) | [简体中文](data_factor_roadmap.zh-CN.md)

## Current Direction

`QuantAdvisorResearch` should remain the final recommendation repository instead
of becoming a full multi-factor trading platform.

Two different research paths should stay separated:

- Backtestable/executable path: price, technical, momentum, volatility, snapshot,
  and strategy repositories that may eventually connect to broker platforms.
- Event/policy/news/AI-shadow path: less stable evidence that should only produce
  non-personalized recommendation reports and review artifacts.

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

Owns final non-personalized model recommendations:

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

## Low-Risk Implementation Order

1. Keep public output focused on final recommendations. Preserve
   `theme_first_candidates[]` as JSON/Markdown explanation and audit material,
   not as a public buy list.
2. Improve stable real sources in `PoliticalEventTrackingResearch`: RSS, official
   releases, SEC/EDGAR, company IR, policy/procurement sources, alias maps, and
   source registry coverage.
3. Add optional market confirmation CSVs while keeping report generation working
   when the data is absent. The CSV should carry point-in-time returns, relative
   returns, abnormal volume, drawdown, and volatility; it should not contain
   target weights or trade instructions.
4. Add event review inputs for 1/5/20/60 trading-day follow-up.
5. Add fundamentals/valuation snapshots for risk explanation, not execution.
6. Only then consider read-only references from existing snapshot repositories.

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

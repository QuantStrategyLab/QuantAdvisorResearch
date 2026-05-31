# Data Source and Factor Roadmap


## 中文摘要

- 完整中文版见 [`data_factor_roadmap.zh-CN.md`](data_factor_roadmap.zh-CN.md)；本节保留在英文文件顶部，方便从当前文件直接找到中文入口。
- 用途：本文档围绕 `Data Source and Factor Roadmap`，用于理解 `QuantAdvisorResearch` 的配置、运行、部署、研究或验收边界。
- 主要覆盖：`Current Direction`、`Current Inputs`、`PoliticalEventTrackingResearch`、`ResearchSignalContextPipelines`、`QuantAdvisorResearch`。
- 阅读顺序：先确认边界、输入输出和权限要求，再执行文档里的命令、CI、dry-run、发布或切换步骤。
- 风险提示：涉及实盘、密钥、权限、Cloud Run、交易所或券商 API 的变更，必须先在测试环境或 dry-run 验证；不要只凭示例直接修改生产。
- 英文正文保留更完整的命令、字段名和配置键；如果摘要和正文不一致，以正文中的实际命令和配置为准。
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

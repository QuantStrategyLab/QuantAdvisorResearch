# Intelligent Advisory Research System Design

[English](system_design.md) | [简体中文](system_design.zh-CN.md)

## Architecture

QuantStrategyLab keeps research evidence, signal context, final recommendations,
and broker execution separated:

- `PoliticalEventTrackingResearch`: point-in-time event evidence, catalysts, URLs,
  dates, and source confidence.
- `ResearchSignalContextPipelines`: reusable research signal context, including
  medium-horizon theme momentum and long-horizon AI shadow context.
- `QuantAdvisorResearch`: deterministic final composition layer for the
  Intelligent Advisory Research System.
- Broker/platform repositories: execution, credentials, runtime adapters, and
  operational alerts.

`QuantAdvisorResearch` does not merge with execution repositories and does not
turn advisory research artifacts into target allocations or orders.

## Data Flow

```text
PoliticalEventTrackingResearch
        |
        v
event evidence + source confidence
        |
        v
QuantAdvisorResearch <--- ResearchSignalContextPipelines latest_signal.json / theme_momentum_snapshot.json
        |
        v
intelligent-advisory artifact
        |
        v
GitHub artifact / static HTML / RSS / optional Telegram / manual review
```

Not connected by default:

```text
UsEquitySnapshotPipelines
UsEquityStrategies
broker platform repositories
```

Those repositories may be used as future read-only reference material, but not as
execution targets for this advisory pipeline.

## Horizon Ownership

- Short term (`1-10 trading days`): event evidence from
  `PoliticalEventTrackingResearch`, plus Advisor-generated market confirmation
  for relative strength, volume, drawdown, and volatility.
- Medium term (`2-12 weeks`): `theme_momentum_snapshot.json` from
  `ResearchSignalContextPipelines`, marked as `medium_horizon_theme_context`,
  focused on theme momentum and symbol momentum.
- Long term (`1-3 years`): `latest_signal.json` and `signal_history/*.json` from
  `ResearchSignalContextPipelines` as AI shadow context.

`QuantAdvisorResearch` records per-recommendation `supporting_context`,
`horizon_scores`, and `horizon_actions` so each final recommendation can be
traced back to short-, medium-, and long-horizon inputs and gates.
The report summary also records long-context availability diagnostics. This
keeps a genuinely weak long signal separate from an upstream ingestion gap.

## Design Patterns

- Ports and Adapters: isolate event sources and signal-context inputs.
- Strategy: keep scoring rules replaceable without changing the report contract.
- Pipeline: load inputs, aggregate candidates, score, apply risk rules, and
  render reports in separate stages.
- Repository: preserve point-in-time advisory artifacts for replay.
- Specification: encode non-personalized, no-execution, and no-allocation policy
  as explicit contract rules.

## Publishing Cadence

Do not switch the public report to monthly-only while the contract still contains
short- and medium-horizon windows.

Recommended cadence:

- `PoliticalEventTrackingResearch`: weekly event/source refresh, with manual
  dispatch when needed.
- `ResearchSignalContextPipelines`: weekly theme momentum; monthly long-horizon
  AI shadow signal.
- `QuantAdvisorResearch`: weekly public Intelligent Advisory HTML/JSON/RSS publication.
- Monthly advisory review: separate artifact for month-end change review; it does
  not replace weekly publication.

## Build and Verification Pipeline

The Advisor repository now uses one shared build command for weekly artifacts,
monthly artifacts, and Pages publication:

```text
scripts/build_advisory_artifacts.py
```

This command owns market-confirmation generation, report generation, manifest
writing, optional monthly review, optional recommendation follow-up review,
optional static-site rendering, and optional published-site archive recovery.
Workflows should call this command instead of duplicating shell logic for each
publication mode.

Market confirmation has a small price-cache adapter around the free Yahoo chart
endpoint. Scheduled workflows restore and save `.cache/market-data` with GitHub
Actions cache. This keeps the public report deterministic enough to publish when
Yahoo has a temporary outage, and it gives recommendation reviews a point-in-time
price source without turning the repository into a paid market-data store.

Recommendation follow-up review is a separate artifact. It reads past final
recommendations, cached prices, and a benchmark, then reports absolute and
relative returns by horizon. It is used for research accountability and data
quality checks; it does not create new recommendations or execution targets.

A separate no-network smoke command validates the three-repository contract:

```text
scripts/run_cross_repo_smoke.py
```

It reads live event/watchlist artifacts, live signal-context artifacts, builds a
report with theme-momentum fallback market confirmation, renders the static
site, and checks that the long/medium/short horizon outputs are present. This
keeps the advisory pipeline distinct from the backtestable/execution pipeline
while still catching interface drift across repositories.

Historical report recovery has two modes:

- the publish workflow recovers previously published report JSONs from
  `reports_index.json` when available;
- `scripts/backfill_site_archive.py` can rebuild a static archive from downloaded
  GitHub Actions artifacts.

## Public Output Boundary

The public HTML/RSS/Telegram outputs should stay direct:

- show final recommendations, horizons, stock background, recommendation reasons,
  and risks;
- render public recommendations as long-, medium-, and short-horizon columns;
- keep short and medium columns tied to each pick's `primary_horizon`, so auxiliary
  horizon actions do not inflate public short/medium conclusions;
- allow the long column to use long-horizon action/context as a fallback when no
  final pick has primary long horizon, preserving long-term context visibility;
- hide internal tags such as `source_mode`, mode labels, audience labels, and
  repository names;
- keep `theme_first_candidates[]`, `horizon_scores`, and `selection_trace` in
  JSON/Markdown as explanation and audit material, not as public page clutter;
- use theme momentum and optional market confirmation only inside deterministic
  `final_decisions` ranking;
- never show orders, target weights, target share quantities, account suitability,
  or account-specific allocation advice.

Market confirmation is optional at the contract level, but the scheduled weekly,
monthly, and publish workflows generate it automatically. Short-horizon gates
require market confirmation, medium-horizon gates are led by theme and symbol
momentum, and long-horizon gates require durable AI shadow or context strength.

## Fixture vs Live Inputs

Reports built from `examples/` are `source_mode=fixture` and are suitable for
local tests only. The public renderers no longer display fixture/source-mode
badges. Scheduled workflows default to `data/live/*` inputs from
`PoliticalEventTrackingResearch`, so published audit artifacts should be
`source_mode=operator_supplied`.

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
Any generated report or notification here is background evidence for content or
recommendation health, not AiGateway online service health, and it must not be
used as an automatic trading or auto-approval basis.

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
relative returns by horizon. Maturity is measured in trading observations:
short and medium horizons require at least 10 trading days, while long requires
252. Before maturity, an item remains `pending` or `in_progress` and cannot be
labeled `outperforming` or `lagging`. Summary metrics (sample size, mean,
median, and hit rate) stay within each horizon, and top symbols are
de-duplicated. It is used for research accountability and data quality checks;
it does not create new recommendations or execution targets.

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

## Input Publication Recovery (2026-10-06)

The bounded recovery changes scheduling and records one-time theme publication
and consumer acceptance. It does not change renderers, score thresholds, account
boundaries, or source contracts. The
[recovery checklist](data_factor_roadmap.md#2026-10-06-input-publication-recovery-staged-evidence)
tracks implementation, consumer acceptance, and public-site publication separately.

At incident capture, the weekly jobs ran on Saturday while `default_weekly_as_of()` selects
the last *fully closed* Saturday. For example, a 2026-10-03 Saturday run selects
2026-09-26, whose `reference_time` is 2026-09-27 00:00 UTC. A theme generated on
2026-10-03 must not pass that earlier cutoff. Merged [PR #79](https://github.com/QuantStrategyLab/QuantAdvisorResearch/pull/79)
schedules weekly review at 12:30 UTC Sunday and publication at 13:00 UTC Sunday,
preserving the existing times. Both use
the same helper after 00:00 UTC, so the new report's cutoff includes Saturday's
already-generated context. A delayed run must still use authentic source dates;
changing `generated_at`, expiry, or freshness limits is not a recovery mechanism.

`ResearchSignalContextPipelines` is public, and current workflows check out its
public Git content. That is not proof that the Advisor's job token can download
cross-repository Actions artifacts. The documented artifact download API needs
Actions read access to the producer repository. The current workflow exposes no
verified publisher identity or token with that target-repository permission.
Connector read access during investigation is not a substitute for CI access.
No cross-repository artifact reader is enabled by this plan.

The current theme job has `contents: write` only. It cannot be assumed to create
PRs, and required checks cannot be assumed to run automatically. GitHub's current
[`GITHUB_TOKEN` documentation](https://docs.github.com/en/actions/concepts/security/github_token)
says PR opened/synchronize/reopened events created with that token produce
approval-required runs. A normal reviewed PR must still have its actual head's
required checks completed. Do not change branch protection or grant new access
as part of this recovery.

An exact retained artifact may be considered for a separately reviewed one-time
PR. Before import, verify repository ID, approved workflow path and source SHA,
same-repository `main` run, event, conclusion, run attempt, artifact ID/name,
expiry, archive digest, exact member path and file hash, and the snapshot's
schema/policy/coverage/time contract. Extraction alone proves none of these.
Record generated, review-required, published, and consumer-accepted as distinct
states. A reviewed PR does not solve the remaining unattended CI identity gap.

Verified on October 6: RSCP [PR #55](https://github.com/QuantStrategyLab/ResearchSignalContextPipelines/pull/55)
imported the reviewed schema-2 snapshot without changing its bytes or source dates.
[Weekly run 37515064136, attempt 1](https://github.com/QuantStrategyLab/QuantAdvisorResearch/actions/runs/37515064136)
then consumed QAR `fe5b00375a4f5cca821fec07317ec92d61546cac`, PETR
`96e4d2a8f9cea9684a4594173397fd78e91119dd`, and RSCP
`0a40f173d98b3d715e59653766c180cf5846dc1c`. The real report has
`as_of=2026-10-03`, `reference_time=2026-10-04T00:00:00Z`, and
`generated_at=2026-10-06T18:56:15Z`; theme freshness is `fresh`.
The theme SHA256 is `f984a3d0b0e0eb14a8f1cf3aac258f909821b06eb2b89e57a766c70aca42ab12`.
Recomputing all five raw input hashes, including the run's market CSV, matches
report/manifest `input_digest=1ccd99bc53ebcbd513581ef1ec1061681778f65fbee7802ee1cd39bc939175ce`.
The [weekly artifact](https://github.com/QuantStrategyLab/QuantAdvisorResearch/actions/runs/37515064136/artifacts/11436757649)
contains the report, manifest, market CSV, and offline M0 evidence. This workflow
only writes its artifact and existing market cache; it does not update Pages or notify Telegram.

The existing `final_decisions` compatibility field `ai_signal_score` aliases
`medium_context_score`, derived from theme context. It does not establish trusted
long-horizon AI availability; this run still rejects AI provenance. No field or
protocol change is part of this evidence update.

References: [artifact API](https://docs.github.com/en/rest/actions/artifacts#download-an-artifact),
[fixed producer run](https://github.com/QuantStrategyLab/ResearchSignalContextPipelines/actions/runs/37132550227),
[consumer build](https://github.com/QuantStrategyLab/QuantAdvisorResearch/actions/runs/37460712408).

## Fixture vs Live Inputs

Reports built from `examples/` are `source_mode=fixture` and are suitable for
local tests only. The public renderers no longer display fixture/source-mode
badges. Scheduled workflows default to `data/live/*` inputs from
`PoliticalEventTrackingResearch`, so published audit artifacts should be
`source_mode=operator_supplied`.

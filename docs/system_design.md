# Smart Advisory Research System Design

[English](system_design.md) | [简体中文](system_design.zh-CN.md)

## Architecture

QuantStrategyLab keeps research evidence, signal context, final recommendations,
and broker execution separated:

- `PoliticalEventTrackingResearch`: point-in-time event evidence, catalysts, URLs,
  dates, and source confidence.
- `ResearchSignalContextPipelines`: reusable research signal context, including
  medium-horizon theme momentum and long-horizon AI shadow context.
- `QuantAdvisorResearch`: deterministic final composition layer for
  non-personalized model recommendations.
- Broker/platform repositories: execution, credentials, runtime adapters, and
  operational alerts.

`QuantAdvisorResearch` does not merge with execution repositories and does not
turn recommendation artifacts into target allocations or orders.

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
model-recommendation artifact
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
  `PoliticalEventTrackingResearch`.
- Medium term (`2-12 weeks`): `theme_momentum_snapshot.json` from
  `ResearchSignalContextPipelines`, marked as `medium_horizon_theme_context`.
- Long term (`1-3 years`): `latest_signal.json` and `signal_history/*.json` from
  `ResearchSignalContextPipelines` as AI shadow context.

`QuantAdvisorResearch` records per-recommendation `supporting_context` so each
final recommendation can be traced back to short-, medium-, and long-horizon
inputs.

## Design Patterns

- Ports and Adapters: isolate event sources and signal-context inputs.
- Strategy: keep scoring rules replaceable without changing the report contract.
- Pipeline: load inputs, aggregate candidates, score, apply risk rules, and
  render reports in separate stages.
- Repository: preserve point-in-time recommendation artifacts for replay.
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
- `QuantAdvisorResearch`: weekly public HTML/JSON/RSS publication.
- Monthly advisory review: separate artifact for month-end change review; it does
  not replace weekly publication.

## Public Output Boundary

The public HTML/RSS/Telegram outputs should stay direct:

- show final recommendations, horizons, stock background, recommendation reasons,
  and risks;
- hide internal tags such as `source_mode`, mode labels, audience labels, and
  repository names;
- keep `theme_first_candidates[]` in JSON/Markdown as explanation and audit
  material, not as a public buy list;
- never show orders, target weights, target share quantities, account suitability,
  or account-specific allocation advice.

## Fixture vs Live Inputs

Reports built from `examples/` are `source_mode=fixture` and are suitable for
local tests only. Scheduled workflows default to `data/live/*` inputs from
`PoliticalEventTrackingResearch`, so published reports should be
`source_mode=operator_supplied` and should not show fixture warnings.

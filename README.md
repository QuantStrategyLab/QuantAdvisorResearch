# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

Non-personalized model recommendation orchestration for QuantStrategyLab.

This repository combines deterministic event evidence, strategy/snapshot context,
and saved AI shadow context into audit-ready model recommendation reports. It
does not place orders, store broker credentials, manage portfolios, or
personalize advice for a specific investor.

## Repository Role

`QuantAdvisorResearch` is the coordinator for a future smart advisory research
system:

- consume political/public-event context from `PoliticalEventTrackingResearch`
- consume saved AI shadow context from `AiLongHorizonSignalPipelines`
- leave executable strategy math in `UsEquityStrategies`
- leave feature generation and backtests in `UsEquitySnapshotPipelines`
- leave broker execution in platform repositories

The output is a non-personalized model recommendation artifact and a readable daily, weekly,
or monthly report.

## Boundary

This repository owns:

- model recommendation artifact schemas
- deterministic scoring and review policy
- daily/weekly/monthly report generation
- evidence and risk summaries
- model recommendation history for later review

This repository does not own:

- broker API access or order placement
- target quantities, portfolio weights, or account rebalancing
- investor-specific suitability decisions
- model provider routing or prompt execution
- raw paid market-data redistribution

## Local Example

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/ai_long_horizon_signal.example.json \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

Run tests:

```bash
python -m pytest -q
```

Build the weekly report from sibling checkouts:

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events ../PoliticalEventTrackingResearch/examples/political_events.example.csv \
  --political-watchlist ../PoliticalEventTrackingResearch/examples/political_watchlist.example.csv \
  --ai-signal ../AiLongHorizonSignalPipelines/data/output/latest_signal.json \
  --output-json data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-md data/output/weekly_advisory_review/advisory_report_2026-05-30.md
```

`.github/workflows/weekly_advisory_review.yml` runs the same command on a weekly
schedule and uploads the report as a GitHub Actions artifact. It does not commit
files, create orders, or notify investors.

Publish a static HTML + RSS preview:

```bash
python scripts/publish_advisory_site.py \
  --reports data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-dir site \
  --site-url https://quantstrategylab.github.io/QuantAdvisorResearch
```

Open `site/index.html` locally or subscribe to `site/feed.xml`. The workflow
`.github/workflows/publish_advisory_site.yml` can deploy the same output to
GitHub Pages after Pages is enabled for the repository.

Notification channel rules are documented in
[`docs/notification_format.zh-CN.md`](docs/notification_format.zh-CN.md).

## Output Contract

The main JSON artifact is `ModelRecommendationReport`:

```text
schema_version = 3
as_of
generated_at
mode = model_recommendations
cadence = daily | weekly | monthly
audience_scope = non_personalized_model_research
policy.non_personalized_recommendations_allowed = true
policy.execution_allowed = false
policy.portfolio_allocation_allowed = false
policy.account_specific_advice_allowed = false
recommendations[]
```

Each recommendation carries:

```text
symbol
rating
rating_label
primary_horizon
suitable_horizons[]
strategy_style
score
evidence_score
risk_score
reasons[]
risk_notes[]
evidence_refs[]
review_checklist[]
```

## Regulatory Boundary

Even when no orders or allocations are generated, specific securities
recommendations can still raise investment-adviser or broker-dealer obligations
depending on compensation, audience, personalization, and business model. This
repository therefore keeps recommendations non-personalized and blocks execution,
allocation, and account-specific advice.

See:

- SEC investment adviser definition: <https://www.sec.gov/interps/legal/slbim11.htm>
- SEC automated investment advice resources: <https://www.sec.gov/about/divisions-offices/office-strategic-hub-innovation-financial-technology-finhub/automated-investment-advice>
- FINRA Regulation Best Interest: <https://www.finra.org/rules-guidance/key-topics/regulation-best-interest>
- FINRA suitability: <https://www.finra.org/rules-guidance/key-topics/suitability>

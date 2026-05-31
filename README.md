# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

Non-personalized model recommendation orchestration for QuantStrategyLab.

This repository combines deterministic event evidence and saved AI shadow context
into audit-ready model recommendation reports. It does not place orders, store
broker credentials, manage portfolios, or personalize advice for a specific
investor.

## Repository Role

`QuantAdvisorResearch` is the coordinator for a future smart advisory research
system:

- consume political/public-event context from `PoliticalEventTrackingResearch`
- consume saved AI shadow context from `AiLongHorizonSignalPipelines`
- keep other strategy and snapshot repositories independent from this pipeline
- leave broker execution in platform repositories

The current operating cadence is a weekly public recommendation snapshot,
supported by weekly event/theme refreshes and monthly long-horizon AI shadow
context. Monthly review reports can be added later for performance review, but
they should not replace the weekly publication while short-horizon windows are
part of the contract.

Live site:

<https://quantstrategylab.github.io/QuantAdvisorResearch/>

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

## AI Usage

This repository does not call Codex, OpenAI, Anthropic, or any other model API.
It only consumes saved `mode=shadow` artifacts from `AiLongHorizonSignalPipelines`.
The only repository in this three-repo flow that can involve AI is
`AiLongHorizonSignalPipelines`, and even there provider execution is delegated to
`QuantStrategyLab/CodexAuditBridge`. Model API keys and fallback routing belong
there, not in this repository.

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

The command also writes `data/output/advisory_report.example.json.manifest.json`.

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

`.github/workflows/publish_advisory_site.yml` publishes the HTML/JSON/RSS site on
a weekly schedule. If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured
as repository secrets, the workflow sends a short non-personalized Telegram
summary after a successful Pages deployment. If either secret is missing, the
notification step is skipped without failing the publication. Telegram delivery
errors are logged and do not block Pages/RSS output.

The weekly publication cadence is intentional: the report contract still
contains short-horizon (`1-10 trading days`) and medium-horizon (`2-12 weeks`)
windows, so a monthly-only public report would make short-horizon conclusions
stale. The AI shadow input remains monthly because it is long-horizon context,
not a weekly trading signal.

Publish a static HTML + RSS preview:

```bash
python scripts/publish_advisory_site.py \
  --reports data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-dir site \
  --site-url https://quantstrategylab.github.io/QuantAdvisorResearch
```

Open `site/index.html` locally or subscribe to `site/feed.xml`. The workflow
`.github/workflows/publish_advisory_site.yml` deploys the same output to
GitHub Pages:

<https://quantstrategylab.github.io/QuantAdvisorResearch/>

The published HTML, RSS feed title, and Telegram summary default to Simplified
Chinese (`zh-CN`) because the current audience is Chinese-language retail
research readers. JSON field names remain stable English contract keys.

For real-source publishing, dispatch the workflow with paths inside sibling
repositories:

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30 \
  -f political_events_path=data/live/political_events.csv \
  -f political_watchlist_path=data/live/political_watchlist.csv \
  -f ai_signal_path=data/output/latest_signal.json
```

Notification channel rules are documented in
[`docs/notification_format.md`](docs/notification_format.md) and
[`docs/notification_format.zh-CN.md`](docs/notification_format.zh-CN.md).

## Output Contract

The main JSON artifact is `ModelRecommendationReport`:

```text
schema_version = 5
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
theme_first_candidates[]
```

Each recommendation carries:

```text
symbol
rating
rating_label
recommendation_tier
recommendation_tier_label
primary_horizon
primary_horizon_label
primary_horizon_window
horizon_note
suitable_horizons[]
suitable_horizon_windows{}
strategy_style
score
evidence_score
risk_score
source_confidence
source_confidence_label
reasons[]
risk_notes[]
evidence_refs[]
review_checklist[]
```

`theme_first_candidates[]` is an optional display section derived from the
theme momentum snapshot. Public renderers present it as a 5-10 name "重点股票池":
industry/theme background, why the name entered the pool, event-confirmation
state, and key risks. It is still research-only and must not encode orders,
target weights, or account-level advice.

Default horizon windows:

- short: `1-10 trading days`
- medium: `2-12 weeks`
- long: `1-3 years`
- not_applicable: source check, defer, or background tracking only

## Versioning

The Python package version is `0.1.1`. Report artifacts are versioned separately:

- report schema: `schema_version = 5`
- report contract: `model_recommendations.v5`
- report manifest: `<output-json>.manifest.json`

The manifest records the JSON and Markdown SHA256 hashes, `as_of`, cadence,
source artifacts, policy boundary, Git SHA, GitHub run id, and contract version.
This mirrors the snapshot and AI artifact repos without turning recommendations
into executable strategy targets.

## Source Mode

Reports built from `examples/` inputs are marked `source_mode=fixture` and the
HTML/RSS output displays that warning. Live operator-provided inputs are marked
`source_mode=operator_supplied`.

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

## Theme Momentum Display

`build_advisory_report.py` accepts an optional theme momentum snapshot:

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/ai_long_horizon_signal.example.json \
  --theme-momentum examples/theme_momentum_snapshot.example.json \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

Theme momentum is display-first context: it highlights strong themes and creates
a `theme_first_candidates[]` stock-pool section so AI/high-tech candidates are
visible with industry/theme background and reasons even when stable event
evidence is still pending. It does not change recommendation ratings, scores,
allocations, or execution policy. Workflows skip the section when the snapshot
file is absent.

Yahoo chart downloads are only a temporary fallback.  Do not rely on random free
proxy pools for the stable pipeline; prefer audited price snapshots, cache files,
or a controlled proxy/data provider.

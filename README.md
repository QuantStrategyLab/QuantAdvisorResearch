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
- consume saved AI shadow context from `ResearchSignalContextPipelines`
- keep other strategy and snapshot repositories independent from this pipeline
- leave broker execution in platform repositories

The current operating cadence is a weekly public recommendation snapshot,
supported by weekly event/theme refreshes and monthly long-horizon AI shadow
context. Monthly review reports are generated separately for change review and
month-end inspection. They do not replace the weekly publication while
short-horizon windows are part of the contract.

Live site:

<https://quantstrategylab.github.io/QuantAdvisorResearch/>

Key documents:

- [System design](docs/system_design.md) / [系统设计](docs/system_design.zh-CN.md)
- [Data and factor roadmap](docs/data_factor_roadmap.md) / [数据源与因子路线](docs/data_factor_roadmap.zh-CN.md)
- [Notification format](docs/notification_format.md) / [通知格式](docs/notification_format.zh-CN.md)
- [Artifact contract](docs/advisory_contract.md)


## Horizon Source Split

Advisor is the final composition layer. Source ownership by horizon is:

- Short term (`1-10 trading days`): `source_events.csv` / `political_events.csv` from `PoliticalEventTrackingResearch` for event and policy/news catalysts.
- Medium term (`2-12 weeks`): `theme_momentum_snapshot.json` from `ResearchSignalContextPipelines`, now explicitly marked as `medium_horizon_theme_context`.
- Long term (`1-3 years`): `latest_signal.json` / `signal_history/*.json` from `ResearchSignalContextPipelines` as AI shadow context.

Final recommendations are still deterministic Advisor outputs. The signal context repository does not directly produce short-term recommendations or replace the final decision engine. Advisor now records separate short/medium/long horizon scores for each final pick; public pages keep the simpler final recommendation layout.

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
It only consumes saved `mode=shadow` artifacts from `ResearchSignalContextPipelines`.
The only repository in this three-repo flow that can involve AI is
`ResearchSignalContextPipelines`, and even there provider execution is delegated to
`QuantStrategyLab/CodexAuditBridge`. Model API keys and fallback routing belong
there, not in this repository.

## Local Example

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/research_signal_context.example.json \
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
  --ai-signal ../ResearchSignalContextPipelines/data/output/latest_signal.json \
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

Build the separate monthly review artifact:

```bash
python scripts/build_monthly_review.py \
  --current-report data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-json data/output/monthly_advisory_review/monthly_review_2026-05-30.json \
  --output-md data/output/monthly_advisory_review/monthly_review_2026-05-30.md
```

`.github/workflows/monthly_advisory_review.yml` runs monthly and uploads the
monthly report/review artifacts only. It is intentionally separate from the
weekly public HTML/RSS publication.

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

The scheduled publish workflow defaults to live source artifacts inside sibling
repositories. Manual dispatch can normally pass only `as_of`; override paths only
when intentionally testing a different artifact:

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30
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

`theme_first_candidates[]` is an optional internal explanation artifact derived
from the theme momentum snapshot. The current public HTML, RSS, and Telegram
outputs show only final recommendations; theme candidates remain available in
JSON/Markdown for audit and future review. They are still research-only and must
not encode orders, target weights, or account-level advice.

Default horizon windows:

- short: `1-10 trading days`
- medium: `2-12 weeks`
- long: `1-3 years`
- not_applicable: source check, defer, or background tracking only

## Versioning

The Python package version is `0.1.2`. Report artifacts are versioned separately:

- report schema: `schema_version = 5`
- report contract: `model_recommendations.v5`
- report manifest: `<output-json>.manifest.json`

The manifest records the JSON and Markdown SHA256 hashes, `as_of`, cadence,
source artifacts, policy boundary, Git SHA, GitHub run id, and contract version.
This mirrors the snapshot and AI artifact repos without turning recommendations
into executable strategy targets.

## Source Mode

Reports built from `examples/` inputs are still marked `source_mode=fixture` in
JSON, but public HTML/RSS/Telegram output no longer displays fixture or source-mode
badges. Scheduled weekly/monthly and Pages workflows default to `data/live/*`
inputs from `PoliticalEventTrackingResearch`, so published reports should be
`source_mode=operator_supplied` in the audit artifact.

`source_mode` remains in the JSON contract for auditability only.

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
  --ai-signal examples/research_signal_context.example.json \
  --theme-momentum examples/theme_momentum_snapshot.example.json \
  --market-confirmation examples/market_confirmation.example.csv \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

Theme momentum is explanation-first context: it highlights strong themes and
creates `theme_first_candidates[]` for JSON/Markdown audit material. The public
HTML, RSS, and Telegram outputs stay focused on final recommendations only, so
theme candidates are not mistaken for a buy list. The base `recommendations[]`
rating still comes from event/watchlist/AI evidence; `final_decisions` can use
medium-horizon theme momentum plus optional market confirmation to rank the final
public list. It never changes allocation or execution policy. Workflows skip this
context when the snapshot file is absent.

Yahoo chart downloads are only a temporary fallback.  Do not rely on random free
proxy pools for the stable pipeline; prefer audited price snapshots, cache files,
or a controlled proxy/data provider.

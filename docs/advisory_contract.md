# Intelligent Advisory Artifact Contract

## Report

Required top-level fields:

```text
schema_version: "5"
as_of: ISO date
generated_at: ISO datetime
mode: "model_recommendations"
cadence: "daily" | "weekly" | "monthly"
audience_scope: "non_personalized_model_research"
source_artifacts: object
summary: object
recommendations: list
theme_first_candidates: list, optional
final_decisions: object, optional
policy: object
```

## Policy

The policy block allows non-personalized intelligent-advisory research output but keeps account
actions and execution disabled:

```json
{
  "non_personalized_recommendations_allowed": true,
  "execution_allowed": false,
  "portfolio_allocation_allowed": false,
  "personalized_advice_allowed": false,
  "account_specific_advice_allowed": false,
  "downstream_use": "Intelligent advisory research only; do not route to broker execution or account-level allocation."
}
```

## Recommendation

Required fields:

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
suitable_horizons
suitable_horizon_windows
strategy_style
score
evidence_score
risk_score
source_confidence
source_confidence_label
reasons
risk_notes
evidence_refs
review_checklist
```

Allowed ratings:

- `recommend`
- `watch`
- `verify_source`
- `defer`
- `monitor`

Public Chinese renderers label `monitor` as `背景跟踪` to avoid implying an
actionable monitoring instruction. It means context-only and not recommended.

Allowed recommendation tiers:

- `tier_1`
- `tier_2`
- `watchlist`
- `source_check`
- `defer`
- `monitor`

Allowed horizons:

- `short`
- `medium`
- `long`
- `not_applicable`

Default horizon windows:

- `short`: `1-10个交易日`
- `medium`: `2-12周`
- `long`: `1-3年`
- `not_applicable`: `不适用`

Allowed source confidence values:

- `high`
- `medium`
- `low`
- `mixed`
- `no_event`
- `unknown`

Allowed strategy styles:

- `event_driven`
- `long_horizon_growth`
- `value_quality`
- `macro_context`
- `mixed_research`

The contract intentionally rejects account-action fields such as `target_weight`,
`target_quantity`, `shares`, `order_type`, `broker`, and `account_id`. The same
restriction applies to final picks and theme-first candidates.

## Theme-first Candidate

`theme_first_candidates` is optional and is derived from the theme momentum
snapshot. It is kept as JSON/Markdown explanation and audit material with
industry/theme background, reasons, event confirmation, and risks. The current
public HTML, RSS, and Telegram renderers show final recommendations only, so
theme candidates are not mistaken for a buy list. It is still research-only and
must not contain account-action fields.

Important fields:

```text
rank
symbol
candidate_type = theme_first
primary_theme_id
primary_theme_name
industry_background
symbol_momentum_score
advisor_status
source_confirmation
theme_ids
recommendation_summary
risk_summary
reasons
risk_notes
```

## Final Decisions

`final_decisions` is the public Intelligent Advisory recommendation layer. It keeps the simple public
list while preserving audit details in JSON:

```text
recommendations[]
watchlist[]
horizon_buckets.short | medium | long
horizon_rankings.short | medium | long
horizon_action_buckets.short | medium | long
```

Each final pick may carry:

```text
combined_score
source_score
momentum_score
medium_context_score
long_context_score
horizon_scores.short|medium|long
horizon_actions.short|medium|long
supporting_context.short|medium|long
selection_trace[]
business_summary
prospect_summary
why_selected[]
risk_summary
```

Scoring and gate intent by horizon:

- short: recent market confirmation is required; event/news evidence and momentum
  can upgrade confidence;
- medium: theme momentum and individual momentum are required for final
  recommendation; event/news and market confirmation are supporting inputs;
- long: saved AI shadow context or durable long-horizon context must be strong;
  event/news is supporting evidence.

These fields are audit metadata. Public HTML/RSS/Telegram renderers still show
only final recommendations, stock background, recommendation reasons, and risks.
If the primary long bucket is empty but final picks still pass the long-horizon
`watch` or `recommend` gate, the public HTML may show a compact long-context
symbol strip instead of exposing internal scores.

## Long-context Diagnostics

`summary` includes long-context health fields so an empty long bucket can be
debugged without reading renderer code:

```text
long_context_available
long_context_symbol_count
long_context_symbols
long_context_missing_reason
```

If `long_context_available=false`, `long_context_missing_reason` should point to
the first likely ingestion problem, such as missing AI shadow input, a non-long
`latest_signal` horizon, or missing symbol/theme coverage.

## Artifact Manifest

Every CLI-generated JSON report also writes:

```text
<output-json>.manifest.json
```

Required manifest fields:

```text
manifest_type = model_recommendation_report
artifact_type = model_recommendations
contract_version = model_recommendations.v5
schema_version = 5
version = <as_of>-<cadence>-schema-5-<run-or-sha>
source_project = QuantAdvisorResearch
producer.repository
producer.git_sha
producer.github_run_id
source_artifacts
summary
artifacts.json.sha256
artifacts.markdown.sha256
policy
generated_at
```

## Source Mode

`summary.source_mode` is:

- `fixture`: one or more inputs came from `examples/`; scheduled publication should avoid this mode.
- `operator_supplied`: inputs did not come from fixture paths. This is the expected mode for scheduled public publication.

`summary.data_quality_warnings` carries source-mode warnings for audit tooling. Public HTML, index, RSS, and Telegram summaries intentionally do not display `source_mode`; it remains an audit field in JSON.

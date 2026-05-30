# Model Recommendation Artifact Contract

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
policy: object
```

## Policy

The policy block allows non-personalized model recommendations but keeps account
actions and execution disabled:

```json
{
  "non_personalized_recommendations_allowed": true,
  "execution_allowed": false,
  "portfolio_allocation_allowed": false,
  "personalized_advice_allowed": false,
  "account_specific_advice_allowed": false,
  "downstream_use": "Model recommendation research only; do not route to broker execution or account-level allocation."
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
`target_quantity`, `shares`, `order_type`, `broker`, and `account_id`.

## Theme-first Candidate

`theme_first_candidates` is optional and is derived from the theme momentum
snapshot. It exists to make strong-theme candidates visible before the
event-confirmed recommendation list. It is still research-only and must not
contain account-action fields.

Important fields:

```text
rank
symbol
candidate_type = theme_first
primary_theme_id
primary_theme_name
symbol_momentum_score
advisor_status
source_confirmation
theme_ids
reasons
risk_notes
```

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

- `fixture`: one or more inputs came from `examples/`; public output must show a fixture warning.
- `operator_supplied`: inputs did not come from fixture paths.

`summary.data_quality_warnings` carries any source-mode warnings for renderers.

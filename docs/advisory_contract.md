# Model Recommendation Artifact Contract

## Report

Required top-level fields:

```text
schema_version: "3"
as_of: ISO date
generated_at: ISO datetime
mode: "model_recommendations"
cadence: "daily" | "weekly" | "monthly"
audience_scope: "non_personalized_model_research"
source_artifacts: object
summary: object
recommendations: list
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
primary_horizon
suitable_horizons
strategy_style
score
evidence_score
risk_score
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

Allowed horizons:

- `short`
- `medium`
- `long`
- `not_applicable`

Allowed strategy styles:

- `event_driven`
- `long_horizon_growth`
- `value_quality`
- `macro_context`
- `mixed_research`

The contract intentionally rejects account-action fields such as `target_weight`,
`target_quantity`, `shares`, `order_type`, `broker`, and `account_id`.

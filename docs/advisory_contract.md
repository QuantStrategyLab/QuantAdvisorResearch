# Advisory Artifact Contract

## Report

Required top-level fields:

```text
schema_version: "1"
as_of: ISO date
generated_at: ISO datetime
mode: "recommendation_only"
cadence: "daily" | "weekly" | "monthly"
audience_scope: "non_personalized_research"
source_artifacts: object
summary: object
recommendations: list
policy: object
```

## Policy

The policy block must always keep execution disabled:

```json
{
  "execution_allowed": false,
  "portfolio_allocation_allowed": false,
  "personalized_advice_allowed": false,
  "downstream_use": "Research review only; do not route to broker execution."
}
```

## Recommendation

Required fields:

```text
symbol
stance
action
style
conviction
evidence_score
risk_score
thesis
risks
evidence_refs
review_checklist
```

Allowed actions:

- `source_review_only`
- `watch`
- `research_candidate`
- `avoid_or_defer`
- `monitor`

Allowed styles:

- `event_driven_speculation`
- `long_horizon_growth`
- `value_quality_review`
- `defensive_macro_context`
- `mixed_research`


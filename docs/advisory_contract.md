# Research Radar Artifact Contract

## Report

Required top-level fields:

```text
schema_version: "2"
as_of: ISO date
generated_at: ISO datetime
mode: "research_radar"
cadence: "daily" | "weekly" | "monthly"
audience_scope: "non_personalized_research"
source_artifacts: object
summary: object
research_items: list
policy: object
```

## Policy

The policy block must always keep direct recommendations and execution disabled:

```json
{
  "execution_allowed": false,
  "portfolio_allocation_allowed": false,
  "personalized_advice_allowed": false,
  "direct_stock_recommendation_allowed": false,
  "downstream_use": "Research triage only; do not treat as buy/sell/hold signal, broker execution, or account-level allocation."
}
```

## Research Item

Required fields:

```text
symbol
research_view
review_status
research_lens
research_priority
evidence_score
risk_score
evidence_summary
risks
evidence_refs
review_checklist
not_investment_rating
```

Allowed review statuses:

- `verify_source`
- `observe`
- `evidence_review`
- `risk_defer`
- `context_monitor`

Allowed research lenses:

- `event_research`
- `long_horizon_context`
- `quality_review`
- `macro_context`
- `mixed_research`

The contract intentionally rejects legacy direct-recommendation wording such as
`action`, `stance`, `conviction`, and `recommendation` inside `research_items`.

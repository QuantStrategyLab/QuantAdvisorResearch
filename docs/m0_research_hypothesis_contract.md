# M0 ResearchHypothesis v1

`qsl.m0_research_hypothesis.v1` is a closed, research-only boundary between
the public advisory report and a later independent strategy-validation process.
It is an adapter output, not a new public-report format and not an execution
input.

The adapter accepts an already validated `model_recommendations.v5` or v6
report and emits one `asset_idea` hypothesis per unique advisory symbol.  It
keeps only a subject identifier, research state/horizon, limited context
metadata, source counts, and cryptographic provenance.  It intentionally does
not copy public-report prose, scores, source paths, targets, or strategy names.

The exact top-level fields are:

```text
schema_version: "qsl.m0_research_hypothesis.v1"
artifact_type: "research_hypothesis"
authority: "research_only"
no_order: true
hypothesis_id: stable digest-derived identifier
as_of, generated_at, expires_at
subject: { kind, identifier }
research_context: { state, primary_horizon, suitable_horizons, source_confidence, source_style, theme_ids }
evidence: { source_entry_digest, evidence_ref_count, risk_note_count }
provenance: source-report versions and digests
permitted_next_step: "research_validation_only"
```

`expires_at` is exactly seven days after `generated_at`.  For a v6 report it
matches the report expiry; for the existing v5 publisher it is derived from the
publisher timestamp.  Consumers must treat an expired M0 artifact as a stale
research lead, never as a fresh signal.

`no_order` is required and must be exactly `true`. It is the sole exception to
the recursive execution-field ban: a negative, non-actionable declaration, not
an instruction. `primary_horizon` and the de-duplicated `suitable_horizons`
retain the advisory report's short, medium, and long research context without
turning any horizon into an allocation or action.

The validator requires exact keys at every object level and recursively rejects
execution, account, position, allocation, broker, order (except top-level
`no_order: true`), platform, runtime,
routing, switching, credential, and similar semantic fields, including
camelCase variants.  The only next step it permits is independent research
validation.  It cannot name a strategy candidate, set a risk limit, route a
platform, change a runtime target, or submit an order.

The next repository-owned stage may map a valid M0 hypothesis to a bounded
research task.  Only later P1--P3 data, backtest, and audit evidence can create
an immutable strategy candidate for P0 Shadow selection.

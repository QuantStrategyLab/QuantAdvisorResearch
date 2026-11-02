# Intelligent Advisory Artifact Contract

## Report

Required top-level fields:

```text
schema_version: "6"
contract_version: "model_recommendations.v6"
as_of: ISO date
reference_time: exclusive start of the UTC day after as_of
generated_at: ISO datetime
expires_at: generated_at + 7 days
input_digest: 64 lowercase hexadecimal SHA-256 characters
freshness.ai_signal
freshness.theme_momentum
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

The current CLI and scheduled workflows produce v6. Readers continue to accept
legacy v5 reports, but no v6 field is silently accepted on a v5 report.

An explicit `as_of` is a UTC calendar date, not the invocation's local date.
Its entire UTC day must have ended before a report can be generated:
`generated_at >= reference_time`. For example, `as_of=2026-10-15` first becomes
valid at `2026-10-16T00:00:00Z` (`2026-10-16T08:00:00+08:00`). An earlier build
is rejected with the requested date, required UTC cutoff, and actual generation
time. Offsets are normalized to UTC before comparison; equality is accepted.

Leave the workflow's `as_of` input empty to select a fully closed period:
yesterday for daily reports, the latest completed Saturday for weekly reports,
or the last day of the previous month for monthly reports, all in UTC. A manual
override keeps its requested date and is rejected if that date has not closed;
the producer does not shift the cutoff or change generation timestamps to make
an early request pass.

### V6 default contract

A v6 report uses `contract_version = model_recommendations.v6` and adds these
required top-level fields:

```text
reference_time: exclusive start of the UTC day after as_of
expires_at: generated_at + 7 days
input_digest: 64 lowercase hexadecimal SHA-256 characters
freshness.ai_signal
freshness.theme_momentum
```

`freshness` is evaluated relative to the report's fixed `reference_time`, not
the reader's wall clock. Declared source context and freshness state must agree;
malformed, future, stale, or expired context fails closed. The checked-in
contract fixture is `tests/fixtures/advisory_report_v6.json`.

For a v6 producer, `input_digest` is the aggregate content identity of the
complete logical input set. The producer computes the SHA-256 of canonical JSON
whose keys are the sorted logical source roles and whose values are each source
file's lowercase SHA-256, or `null` when that optional role is absent. Canonical
JSON uses UTF-8, sorted keys, and separators `(',', ':')`. This binds the output
to source contents instead of mutable file paths. Changing this algorithm
requires a later schema version.

Readers validate the digest shape and the full report artifact digest. A reader
that also holds the original inputs may recompute `input_digest`; a report alone
cannot prove that its producer hashed honest source bytes. V6 manifests repeat
the report's exact `input_digest` so downstream lineage checks do not need to
infer it from `source_artifacts` paths.

### Optional publication fields

These additive fields are accepted by `validate_advisory_report` on v5 and v6
reports. New v6 builds emit them; older reports may omit them. Schema versions,
existing fields, scoring gates and research-only policy remain unchanged.
Consumers should hide the corresponding display when a field is absent.

| Field | Shape | Meaning |
| --- | --- | --- |
| `final_decisions.horizon_summary` | Object keyed by `short`, `medium`, `long` | Each entry contains `max_score` and `threshold`. |
| `input_checks` | Array of objects | Each entry contains `name`, `detail`, `status`, `as_of`. |
| `sources` | Array of objects | Each entry contains `url`, `type`, `fetched_at`, `status`. |

If `horizon_summary` is present, all three horizons and both entry fields are
required. `max_score` is a finite number in `[0, 1]`, or `null` when no candidate
was evaluated. It covers all evaluated candidates, including those excluded
from the recommendation and watch lists, before public list limits are applied.
`threshold` is a finite number in `[0, 1]`, taken from the existing recommendation
score gate: short `0.60`, medium `0.52`, long `0.62`. Meeting this score gate
alone does not imply a recommendation: the existing component, freshness and
market-confirmation gates still apply.

Each input check has non-empty string `name` and `detail`, a `status` from
`available`, `missing`, `stale`, `invalid`, `unknown`, and a required `as_of`
that is an ISO date or `null`. The producer emits checks for `political_events`,
`political_watchlist`, `ai_signal`, `theme_momentum`, and `market_confirmation`.
Context checks reuse the existing freshness/provenance assessment and expose
its reason or sanitized quality warning in `detail`. Unavailable or rejected
context is `invalid`; expired or stale context is `stale`; omitted context is
`missing`. Existing legacy-expiry warnings remain visible in `detail`.
CSV checks marked `available` mean parsed, not freshness-verified. Their dates
are the latest retained event/market dates when present; the watchlist is
undated. No timestamp is substituted for an unknown input date.

Each source has an absolute HTTP(S) `url` without userinfo, non-empty string
`type`, a required `fetched_at` that is a timezone-aware ISO datetime or `null`,
and a `status` from `unverified`, `available`, `missing`, `stale`, `invalid`,
`unknown`. The producer collects public links declared by retained political
events (`type: political_event`) and watchlist entries (`type: watchlist`),
deduplicated and sorted by `(url, type)`. Non-HTTP links and URLs with userinfo
are omitted. These CSV inputs do not attest URL retrieval: `fetched_at` stays
`null` and `status` stays `unverified`. The builder performs no network fetch
and does not claim that this list exhausts all upstream evidence.

Example of the new fields only (synthetic values):

```json
{
  "final_decisions": {
    "horizon_summary": {
      "short": {"max_score": 0.42, "threshold": 0.60},
      "medium": {"max_score": 0.50, "threshold": 0.52},
      "long": {"max_score": 0.35, "threshold": 0.62}
    }
  },
  "input_checks": [
    {"name": "ai_signal", "detail": "not_provided", "status": "missing", "as_of": null}
  ],
  "sources": [
    {"url": "https://example.invalid/evidence", "type": "political_event", "fetched_at": null, "status": "unverified"}
  ]
}
```

### Reports index

The existing `reports_index.json` filename, `schema_version: 1`, report ordering
(newest `as_of` first), and `as_of`, `cadence`, `html`, `json` fields are retained.
Each item additionally contains:

```json
{
  "recommendation_count": 2,
  "horizon_counts": {"short": 0, "medium": 1, "long": 1}
}
```

`recommendation_count` counts the public `final_decisions.recommendations`
list. `horizon_counts` counts those picks by `primary_horizon`, once per pick;
watchlist and overflow picks are excluded, as are secondary horizon actions.
An explicitly empty final list yields zero counts. Legacy reports without
`final_decisions` fall back to base recommendations with `rating: recommend`.
Picks outside the three named horizons count toward the total only. Empty
reports still include all three horizon keys with zero values. These fields
support archive filtering and count charts without opening each report.

V1 readers require `as_of`, `cadence`, `html`, and `json`, and ignore unknown
entry fields, including these optional display counts. This additive contract
keeps the v1 identity model and existing output version: display metadata does
not establish identity or verified evidence. `parse_v1_index` and the v1 path
of `parse_identity_index` apply the same rule. Required field types, period and
filename validation, variant rejection, and artifact-conflict checks remain
unchanged; the top-level index shape stays strict. Older readers that enforce
an exact entry key set must adopt this rule before consuming the extended index.

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
overflow_recommendations[]
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

Section semantics are strict: `recommendations[]` and
`overflow_recommendations[]` contain only items with `action = "recommend"`;
`watchlist[]` contains only items with `action = "watch"`.
`overflow_recommendations[]` preserves valid recommendations outside the public
top-N list without relabeling them as watchlist items.

For compatibility, `summary.recommendation_count` remains the base-layer
`recommendations[]` count. The final layer separately reports
`base_recommendation_count`, `final_recommendation_count`,
`final_watchlist_count`, and `final_overflow_recommendation_count`.

Scoring and gate intent by horizon:

- short: recent market confirmation is required; event/news evidence and momentum
  can upgrade confidence;
- medium: theme momentum and individual momentum are required for final
  recommendation; event/news and market confirmation are supporting inputs;
- long: saved AI shadow context or durable long-horizon context must be strong;
  event/news is supporting evidence.

These fields are audit metadata. Public HTML/RSS/Telegram renderers still show
only final recommendations, stock background, recommendation reasons, and risks.
Public HTML renders final picks independently per horizon. If a pick passes both
medium and long gates, it can appear as a full card in both columns, with the
column-specific horizon window and score.

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

## Recommendation Follow-up Review

Recommendation follow-up reviews are separate audit artifacts generated from
past final recommendations and cached point-in-time prices:

```text
schema_version = 2
mode = recommendation_review
as_of
generated_at
benchmark
source_reports[]
summary
review_items[]
data_quality_warnings[]
policy
```

Each `review_items[]` row carries the original report date, review date, symbol,
primary horizon, price interval, absolute return, benchmark return,
benchmark-relative return, trading-observation count, maturity status, outcome
label, market data source, and original selection scores when present. The
minimum maturity is 10 trading days for short/medium and 252 trading days for
long. Summary performance metrics are reported separately for each horizon.

Allowed outcome labels:

- `pending`
- `in_progress`
- `insufficient_price_data`
- `outperforming`
- `inline`
- `lagging`

This artifact is for research accountability only. It must not be interpreted as
a new buy list, target allocation, or execution signal.

## Artifact Manifest

Every CLI-generated JSON report also writes:

```text
<output-json>.manifest.json
```

Required manifest fields:

```text
manifest_type = model_recommendation_report
artifact_type = model_recommendations
contract_version = model_recommendations.v6
schema_version = 6
version = <as_of>-<cadence>-schema-6-<run-or-sha>
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
input_digest
```

The v6 manifest carries the exact top-level `input_digest`. Legacy v5 manifests
remain readable and omit this field.

## Source Mode

`summary.source_mode` is:

- `fixture`: one or more inputs came from `examples/`; scheduled publication should avoid this mode.
- `operator_supplied`: inputs did not come from fixture paths. This is the expected mode for scheduled public publication.

`summary.data_quality_warnings` carries source-mode warnings for audit tooling. Public HTML, index, RSS, and Telegram summaries intentionally do not display `source_mode`; it remains an audit field in JSON.

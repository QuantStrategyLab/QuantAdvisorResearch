# QAR clean-slate vNext identity contract

Status: approved for QAR-N1 foundation.

## Wire namespace

The vNext index uses the exact top-level shape:

```json
{"schema_version":"qar_vnext.identity_index.v1","entries":[...]}
```

`entries` contain only clean `V3_CANONICAL` or `V3_VARIANT` identities. The
codec does not read, migrate, or silently fall back to legacy index versions.
`LEGACY_V2` is not a valid vNext entry.

The entry fields are the validated period/as-of/cadence and report/contract
evidence, semantic and artifact digest versions/digests, `json`/`html` names,
optional `md`/`manifest` names, identity class, canonical flag, and display
evidence. Status and trust are not wire claims; parsed bindings are pending
artifact validation until a later authorized integration stage.

All vNext public targets are cadence-aware. Canonical JSON/Markdown/manifest
use `advisory_report_<as_of>-<cadence>` as their stem; canonical HTML uses
`<as_of>-<cadence>-model-recommendations`. Variants insert
`.variant-<full artifact_integrity_digest>` before the extension, and every
declared artifact for one binding uses the same suffix. Thus daily, weekly,
and monthly reports for one `as_of` cannot collide.

## Allocation

- `EXACT_ARTIFACT_REUSE` returns only an exact clean vNext binding and requires
  attachment/display policy equality. An exact `CURRENT_MANDATORY` hit reuses
  the immutable binding and reports `reused_existing=True`; it does not create
  an identical variant. CURRENT may supply new display placement for the
  publication plan without mutating the stored binding; EXACT reuse requires
  stored display equality, while historical reuse treats display as separate
  from identity. All modes still require exact attachment presence.
- `CURRENT_MANDATORY` may bootstrap one canonical identity in an empty period;
  a rerun in an occupied period receives a full artifact-digest variant.
- `HISTORICAL_RECOVERY` requires an existing canonical identity and otherwise
  fails closed.

Raw report, context, requested artifacts, display placement, and the complete
vNext index are validated before lookup or allocation. The report source
identity never determines public target names. A publication plan may bind a
current candidate to a variant target and keep display evidence independent.

This foundation is pure: no filesystem, network, publisher, build, workflow,
Pages, or production writes.

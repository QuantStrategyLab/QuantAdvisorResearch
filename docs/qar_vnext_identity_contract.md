# QAR clean-slate vNext N1 identity contract

The independent wire namespace is exactly
`qar_vnext.identity_index.v1` with top-level keys `schema_version` and
`entries`. It accepts only `V3_CANONICAL` and `V3_VARIANT`; legacy identity
classes, old index versions, migration and fallback are rejected.

Every public target is cadence-aware:

- canonical: `advisory_report_<as_of>-<cadence>.(json|md)` and
  `<as_of>-<cadence>-model-recommendations.html`;
- variant: the same names with
  `.variant-<full artifact_integrity_digest>` before the extension;
- manifest uses the matching JSON stem and suffix.

Optional `md` and `manifest` are presence-sensitive: omission means the target
was not requested; a present key must contain a valid basename string. `null`,
empty strings and other types are invalid and cannot be silently dropped by
serialization.

`EXACT_ARTIFACT_REUSE`, `CURRENT_MANDATORY` and `HISTORICAL_RECOVERY` validate
all inputs before lookup. An identical current artifact reuses its immutable
canonical binding; a changed artifact in an occupied period receives a full
artifact-digest variant. Current publication display is separate from stored
identity, while exact reuse requires stored display equality and historical
reuse does not treat display as identity.

This foundation is pure: it performs no filesystem, network, publisher,
build, workflow, Pages, migration or production I/O. The old runtime/index
path is isolated and is not a vNext compatibility mode.

# V3 Identity Ledger Contract

## Boundary

`V3IdentityIndex` is a persistent immutable identity ledger. It is **not** a
Stage 2B selected-candidate group and does not decide homepage/latest/RSS
selection. Candidate selection and display ordering are later concerns.

## Entry invariants

- The top-level index has `schema_version=3`; entries use
  `report_schema_version` for the report's v5/v6 schema.
- Every entry has internally consistent `period_key`, `as_of`, `cadence`,
  report/contract versions, names, semantic digest, and artifact-integrity
  digest.
- A complete index has exactly one canonical binding per period.
- `V3_CANONICAL` uses unsuffixed declared names.
- `V3_VARIANT` uses the full artifact-integrity digest as the suffix of every
  declared public artifact name.
- `LEGACY_V2` preserves the old v2 name grammar; its artifact digest is
  pending evidence and does not change the old semantic suffix.
- Same-period bindings may have different semantic digests. A canonical
  binding plus a semantically different, artifact-aware variant is valid when
  all identity/name/artifact invariants hold.
- Semantic digest may repeat across periods. Artifact-integrity digest may not
  bind conflicting full metadata or public identities in one complete index.
- `canonical_identity` is persistent ownership; `display_primary` and
  `display_order` are independent evidence for a later selected view. A
  canonical binding may have `display_primary=false`, while a variant may have
  `display_primary=true`.

The parser therefore rejects only internal contract conflicts. It does not
enforce semantic uniformity and does not perform selection, allocation,
serialization, or publication.

## Trust and migration

Parsed entries are `PENDING_ARTIFACT_VALIDATION`. The public ledger is not a
trust root; real report revalidation belongs to the later allocation/migration
stage. v1/v2 readers retain their existing wire semantics and are never
silently upgraded to v3.

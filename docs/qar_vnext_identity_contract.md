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

## Allocation

- `EXACT_ARTIFACT_REUSE` returns only an exact clean vNext binding and requires
  attachment/display policy equality.
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

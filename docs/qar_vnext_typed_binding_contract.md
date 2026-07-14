# QAR-N1 typed-binding contract

The clean-slate wire namespace is `qar_vnext`, index schema version `1`, and
binding version `1`. The top-level index requires exactly `namespace`,
`schema_version`, and `entries`; each entry carries the binding discriminator
`binding_namespace=qar_vnext` and `binding_version=1`.

`VNextIdentityBinding` is a distinct in-memory type from legacy
`V3IdentityBinding`. The parser, allocator and vNext `PublicationPlan` path
dispatch by actual binding type or parsed wire namespace. There is no caller
`identity_namespace` flag and no filename-based routing. Legacy bindings stay
on the existing validator and cannot enter a vNext index; vNext bindings cannot
be decoded as legacy entries.

All targets are cadence-aware. Canonical names are unsuffixed; variants use
the complete artifact-integrity digest suffix consistently across JSON, HTML,
optional Markdown and manifest. Optional attachment omission means not
requested; an explicit key must be a valid basename string, never `null`.

`display_order` is a non-boolean integer in `0..(2**53-1)` at every wire and
in-memory boundary. Allocation modes are exact reuse, current mandatory and
historical recovery; identical current artifacts reuse immutable bindings,
changed occupied-period artifacts become variants, and historical recovery
without a canonical fails closed.

This is a pure foundation with no migration, publisher, build, workflow,
Pages, producer, filesystem, network or other production I/O.

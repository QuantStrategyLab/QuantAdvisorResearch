# QAR vNext schema-v1 identity foundation

`qar_vnext_identity.v1` is a clean-slate immutable identity/index wire namespace. It is independent from legacy identity codecs and has no dual-read, migration, compatibility fallback, publisher, allocation, report verification, or I/O path.

The top-level schema version and entry discriminator are fixed. The semantic and artifact algorithm pair is fixed for schema-v1; unknown/future/mismatched versions fail closed. Future algorithm changes require a new schema/namespace.

The foundation validates period/cadence, report schema-contract pairing, digest/version fields, V3 canonical/variant class, pending status, cadence-aware targets, canonical/variant suffixes, optional attachment key presence, full artifact identity uniqueness, target/canonical/digest collisions, per-period display-primary/order invariants, safe integer bounds, and deterministic parse/serialize ordering. It does not claim that report bytes have been verified and does not create a publication plan.

from __future__ import annotations

import pytest

from quant_advisor_research.identity_lifecycle import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    V1ProvisionalBinding,
    V2IdentityBinding,
    parse_v1_index,
    parse_v2_index,
    make_verified_report_evidence,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def v1_entry(as_of: str = "2026-06-20", cadence: str = "weekly", *, json_name: str | None = None) -> dict:
    return {
        "as_of": as_of,
        "cadence": cadence,
        "json": json_name or f"advisory_report_{as_of}.json",
        "html": f"{as_of}-{cadence}-model-recommendations.html",
    }


def v2_entry(
    *,
    as_of: str = "2026-06-20",
    cadence: str = "weekly",
    digest: str = DIGEST_A,
    variant: bool = False,
    canonical: bool | None = None,
) -> dict:
    suffix = f".variant-{digest}" if variant else ""
    return {
        "period_key": f"{cadence}:2026-06-15:2026-06-21" if cadence == "weekly" else f"{cadence}:2026-06-20:2026-06-20",
        "as_of": as_of,
        "cadence": cadence,
        "schema_version": "5",
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint_digest": digest,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "md": f"advisory_report_{as_of}{suffix}.md",
        "manifest": f"advisory_report_{as_of}{suffix}.json.manifest.json",
        "canonical_identity": not variant if canonical is None else canonical,
        "display_primary": True,
        "display_order": 0,
    }


def test_v1_parser_returns_provisional_binding_without_v2_claims() -> None:
    index = parse_v1_index({"schema_version": 1, "reports": [v1_entry()]})

    assert isinstance(index.bindings[0], V1ProvisionalBinding)
    assert index.bindings[0].status == "PROVISIONAL"
    assert index.bindings[0].period_key == "weekly:2026-06-15:2026-06-21"


def test_v1_allows_multiple_legacy_identities_in_one_period() -> None:
    entries = [
        v1_entry(as_of="2026-06-20"),
        v1_entry(as_of="2026-06-21", json_name="advisory_report_2026-06-21.json"),
    ]

    assert len(parse_v1_index({"schema_version": 1, "reports": entries}).bindings) == 2


def test_v1_declared_basename_collision_fails_closed() -> None:
    entries = [
        v1_entry(cadence="daily"),
        v1_entry(cadence="weekly"),
    ]

    with pytest.raises(IdentityMetadataError, match="identity_artifact_conflict"):
        parse_v1_index({"schema_version": 1, "reports": entries})


def test_v1_exact_duplicate_identity_is_rejected() -> None:
    entry = v1_entry()

    with pytest.raises(IdentityMetadataError, match="identity_artifact_conflict"):
        parse_v1_index({"schema_version": 1, "reports": [entry, dict(entry)]})


@pytest.mark.parametrize(
    "entry",
    [
        {**v1_entry(), "json": "../advisory_report_2026-06-20.json"},
        {**v1_entry(), "json": "/tmp/advisory_report_2026-06-20.json"},
        {**v1_entry(), "json": "advisory_report_2026-06-20.variant-a.json"},
        {**v1_entry(), "debug": "raw"},
    ],
)
def test_v1_malformed_names_and_unknown_fields_are_sanitized(entry: dict) -> None:
    with pytest.raises(IdentityMetadataError):
        parse_v1_index({"schema_version": 1, "reports": [entry]})


def test_v2_parser_accepts_canonical_and_multiple_variants() -> None:
    entries = [
        v2_entry(),
        v2_entry(as_of="2026-06-21", digest=DIGEST_B, variant=True),
    ]

    index = parse_v2_index({"schema_version": 2, "reports": entries})

    assert isinstance(index.bindings[0], V2IdentityBinding)
    assert sum(binding.canonical_identity for binding in index.bindings) == 1


def test_v2_variant_suffix_must_equal_full_digest() -> None:
    entry = v2_entry(variant=True)
    entry["fingerprint_digest"] = DIGEST_B

    with pytest.raises(IdentityMetadataError, match="identity_digest_mismatch"):
        parse_v2_index({"schema_version": 2, "reports": [entry]})


@pytest.mark.parametrize("field", ["md", "manifest"])
def test_v2_explicit_null_attachment_is_rejected(field: str) -> None:
    entry = v2_entry()
    entry[field] = None

    with pytest.raises(IdentityMetadataError, match="invalid_identity_name"):
        parse_v2_index({"schema_version": 2, "reports": [entry]})


def test_v2_only_one_canonical_binding_per_period() -> None:
    entries = [
        v2_entry(),
        v2_entry(as_of="2026-06-21", digest=DIGEST_B, canonical=True),
    ]

    with pytest.raises(IdentityMetadataError, match="identity_canonical_conflict"):
        parse_v2_index({"schema_version": 2, "reports": entries})


def test_v2_duplicate_identity_rejects_any_metadata_or_digest_difference() -> None:
    first = v2_entry()
    duplicate = dict(first)
    duplicate["display_order"] = 1
    duplicate["fingerprint_digest"] = DIGEST_B

    with pytest.raises(IdentityMetadataError, match="identity_content_conflict"):
        parse_v2_index({"schema_version": 2, "reports": [first, duplicate]})


def test_v2_same_period_digest_cannot_map_to_two_identities() -> None:
    first = v2_entry()
    second = v2_entry(as_of="2026-06-21", digest=DIGEST_A, variant=True)

    with pytest.raises(IdentityMetadataError, match="identity_digest_conflict"):
        parse_v2_index({"schema_version": 2, "reports": [first, second]})


def test_v2_same_digest_across_periods_is_allowed() -> None:
    first = v2_entry()
    second = v2_entry(as_of="2026-06-27", digest=DIGEST_A)
    second["period_key"] = "weekly:2026-06-22:2026-06-28"

    assert len(parse_v2_index({"schema_version": 2, "reports": [first, second]}).bindings) == 2


@pytest.mark.parametrize("name_field", ["json", "md", "manifest"])
def test_v2_each_declared_basename_collision_is_rejected(name_field: str) -> None:
    first = v2_entry(variant=True)
    second = v2_entry(cadence="daily", variant=True)
    second[name_field] = first[name_field]

    with pytest.raises(IdentityMetadataError, match="identity_artifact_conflict"):
        parse_v2_index({"schema_version": 2, "reports": [first, second]})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 5),
        ("display_order", True),
        ("fingerprint_digest", "short"),
        ("period_key", "weekly:wrong"),
    ],
)
def test_v2_wire_types_and_period_are_strict(field: str, value: object) -> None:
    entry = v2_entry()
    entry[field] = value

    with pytest.raises(IdentityMetadataError):
        parse_v2_index({"schema_version": 2, "reports": [entry]})


def test_report_evidence_factory_is_not_a_v2_identity() -> None:
    evidence = make_verified_report_evidence(
        as_of="2026-06-20",
        cadence="weekly",
        schema_version="5",
        fingerprint_digest=DIGEST_A,
    )

    assert evidence.period_key == "weekly:2026-06-15:2026-06-21"
    assert not hasattr(evidence, "canonical_identity")


@pytest.mark.parametrize("digest", [None, "x", True])
def test_report_evidence_digest_is_strict(digest: object) -> None:
    with pytest.raises(IdentityMetadataError, match="invalid_fingerprint_digest"):
        make_verified_report_evidence(
            as_of="2026-06-20",
            cadence="weekly",
            schema_version="5",
            fingerprint_digest=digest,
        )

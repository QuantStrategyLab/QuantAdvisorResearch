from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.publication_identity import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    ReportsIndex,
    parse_reports_index,
    serialize_reports_index_v2,
    verify_identity_binding,
)


ROOT = Path(__file__).resolve().parents[1]


def build_report(*, as_of: str = "2026-06-20", schema_version: str = "5") -> dict:
    report = build_advisory_report(
        as_of=as_of,
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if schema_version == "6":
        report.update(
            {
                "schema_version": "6",
                "contract_version": "model_recommendations.v6",
                "reference_time": canonical_period_identity("weekly", as_of).period_end.isoformat(),
                "expires_at": "2026-06-28T12:00:00.123456Z",
                "freshness": {
                    "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                    "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
                },
            }
        )
    return report


def digest_for(report: dict) -> str:
    return hashlib.sha256(report_content_fingerprint(report).encode("utf-8")).hexdigest()


def v1_entry(as_of: str = "2026-06-20") -> dict:
    return {
        "as_of": as_of,
        "cadence": "weekly",
        "json": f"advisory_report_{as_of}.json",
        "html": f"{as_of}-weekly-model-recommendations.html",
    }


def v2_entry(report: dict, *, digest: str | None = None, variant: bool = False) -> dict:
    as_of = report["as_of"]
    digest = digest or digest_for(report)
    suffix = f".variant-{digest}" if variant else ""
    return {
        "period_key": canonical_period_identity(report["cadence"], as_of).key,
        "as_of": as_of,
        "cadence": report["cadence"],
        "schema_version": report["schema_version"],
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint_digest": digest,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-weekly-model-recommendations{suffix}.html",
        "md": f"advisory_report_{as_of}{suffix}.md",
        "manifest": f"advisory_report_{as_of}{suffix}.json.manifest.json",
        "canonical_identity": not variant,
        "display_primary": True,
        "display_order": 0,
    }


def test_v1_canonical_is_provisional_until_report_verification() -> None:
    index = parse_reports_index({"schema_version": 1, "reports": [v1_entry()]})

    binding = index.bindings[0]
    assert binding.period_key == "weekly:2026-06-15:2026-06-21"
    assert binding.fingerprint_digest is None
    assert binding.verification_status == "PENDING_REPORT_VALIDATION"
    assert binding.canonical_identity is True


def test_v1_binding_can_be_verified_without_exposing_fingerprint_payload() -> None:
    report = build_report()
    binding = parse_reports_index({"schema_version": 1, "reports": [v1_entry()]}).bindings[0]

    verified = verify_identity_binding(binding, report)

    assert verified.verification_status == "VERIFIED"
    assert verified.fingerprint_version == FINGERPRINT_VERSION
    assert verified.fingerprint_digest == digest_for(report)
    parsed = parse_reports_index({"schema_version": 2, "reports": [v2_entry(report)]})
    verified_index = ReportsIndex(2, (verify_identity_binding(parsed.bindings[0], report),))
    assert '"symbol"' not in serialize_reports_index_v2(verified_index)


def test_v2_canonical_and_variant_accept_full_digest_and_optional_files() -> None:
    report = build_report()
    canonical = v2_entry(report)
    variant_report = build_report()
    variant_report["recommendations"][0]["reasons"] = ["variant content"]
    variant = v2_entry(variant_report, variant=True)

    index = parse_reports_index({"schema_version": 2, "reports": [canonical, variant]})

    assert len(index.bindings) == 2
    assert index.bindings[0].fingerprint_digest == digest_for(report)
    assert index.bindings[1].canonical_identity is False


def test_v2_optional_md_and_manifest_may_be_absent() -> None:
    report = build_report()
    entry = v2_entry(report)
    del entry["md"]
    del entry["manifest"]

    binding = parse_reports_index({"schema_version": 2, "reports": [entry]}).bindings[0]

    assert binding.markdown_name is None
    assert binding.manifest_name is None


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("period_key", "weekly:2026-06-14:2026-06-20", "period_mismatch"),
        ("as_of", "2026-06-21", "identity_name_mismatch"),
        ("cadence", "monthly", "period_mismatch"),
        ("schema_version", 5, "invalid_schema_version"),
        ("fingerprint_version", "other.v1", "invalid_fingerprint_version"),
        ("fingerprint_digest", "a" * 63, "invalid_fingerprint_digest"),
        ("json", "nested/advisory_report_2026-06-20.json", "invalid_identity_name"),
        ("html", "/tmp/2026-06-20-weekly-model-recommendations.html", "invalid_identity_name"),
    ],
)
def test_v2_mismatch_and_wire_type_errors_are_stable(field: str, value: object, code: str) -> None:
    report = build_report()
    entry = v2_entry(report)
    entry[field] = value

    with pytest.raises(IdentityMetadataError) as error:
        parse_reports_index({"schema_version": 2, "reports": [entry]})
    assert str(error.value) == code


def test_v2_variant_digest_must_match_every_public_variant_name() -> None:
    report = build_report()
    entry = v2_entry(report, variant=True)
    entry["html"] = entry["html"].replace(entry["fingerprint_digest"], "0" * 64)

    with pytest.raises(IdentityMetadataError, match="identity_name_mismatch"):
        parse_reports_index({"schema_version": 2, "reports": [entry]})


@pytest.mark.parametrize("mutation", ["missing", "unknown", "bool_int"])
def test_v2_missing_unknown_and_bool_int_fields_fail_closed(mutation: str) -> None:
    report = build_report()
    entry = v2_entry(report)
    if mutation == "missing":
        del entry["fingerprint_digest"]
        expected = "invalid_v2_entry"
    elif mutation == "unknown":
        entry["debug_payload"] = "must not be accepted"
        expected = "invalid_v2_entry"
    else:
        entry["display_order"] = True
        expected = "invalid_display_order"

    with pytest.raises(IdentityMetadataError, match=expected):
        parse_reports_index({"schema_version": 2, "reports": [entry]})


def test_v2_duplicate_identity_or_digest_conflicts_fail_closed() -> None:
    report = build_report()
    first = v2_entry(report)
    same_identity = dict(first)
    same_identity["fingerprint_digest"] = "1" * 64
    other_report = build_report(as_of="2026-06-21")
    same_digest = v2_entry(other_report, digest=digest_for(report), variant=True)

    with pytest.raises(IdentityMetadataError, match="identity_content_conflict"):
        parse_reports_index({"schema_version": 2, "reports": [first, same_identity]})
    with pytest.raises(IdentityMetadataError, match="identity_digest_conflict"):
        parse_reports_index({"schema_version": 2, "reports": [first, same_digest]})


def test_same_digest_is_allowed_across_different_periods() -> None:
    first_report = build_report(as_of="2026-06-20")
    second_report = build_report(as_of="2026-06-27")
    digest = digest_for(first_report)

    index = parse_reports_index(
        {
            "schema_version": 2,
            "reports": [v2_entry(first_report, digest=digest), v2_entry(second_report, digest=digest)],
        }
    )

    assert {binding.period_key for binding in index.bindings} == {
        "weekly:2026-06-15:2026-06-21",
        "weekly:2026-06-22:2026-06-28",
    }


def test_v1_verified_binding_cannot_be_serialized_as_incomplete_v2() -> None:
    report = build_report()
    binding = parse_reports_index({"schema_version": 1, "reports": [v1_entry()]}).bindings[0]
    verified_v1 = verify_identity_binding(binding, report)

    with pytest.raises(IdentityMetadataError, match="v2_serialization_invalid_binding"):
        serialize_reports_index_v2(ReportsIndex(2, (verified_v1,)))


def test_complete_v2_binding_serializes_and_parses_round_trip() -> None:
    report = build_report()
    parsed = parse_reports_index({"schema_version": 2, "reports": [v2_entry(report)]})
    verified = verify_identity_binding(parsed.bindings[0], report)

    round_tripped = parse_reports_index(
        json.loads(serialize_reports_index_v2(ReportsIndex(2, (verified,))))
    ).bindings[0]

    assert round_tripped.period_key == verified.period_key
    assert round_tripped.fingerprint_digest == verified.fingerprint_digest
    assert round_tripped.json_name == verified.json_name
    assert round_tripped.verification_status == "PENDING_REPORT_VALIDATION"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda binding: replace(binding, display_order=None),
        lambda binding: replace(binding, display_order=-1),
        lambda binding: replace(binding, display_order=True),
        lambda binding: replace(binding, fingerprint_version=None),
        lambda binding: replace(binding, fingerprint_digest=None),
        lambda binding: replace(binding, schema_version=None),
    ],
)
def test_serializer_revalidates_complete_v2_invariants(mutation) -> None:
    report = build_report()
    parsed = parse_reports_index({"schema_version": 2, "reports": [v2_entry(report)]})
    verified = verify_identity_binding(parsed.bindings[0], report)

    with pytest.raises(IdentityMetadataError, match="v2_serialization"):
        serialize_reports_index_v2(ReportsIndex(2, (mutation(verified),)))


@pytest.mark.parametrize("key", ["md", "manifest"])
def test_optional_identity_names_are_validated_when_declared(key: str) -> None:
    report = build_report()
    entry = v2_entry(report)
    entry[key] = "../secret"

    with pytest.raises(IdentityMetadataError, match="invalid_identity_name"):
        parse_reports_index({"schema_version": 2, "reports": [entry]})


def test_serializer_is_deterministic_and_does_not_store_full_fingerprint_or_report() -> None:
    report = build_report()
    parsed = parse_reports_index({"schema_version": 2, "reports": [v2_entry(report)]})
    index = ReportsIndex(2, (verify_identity_binding(parsed.bindings[0], report),))

    first = serialize_reports_index_v2(index)
    second = serialize_reports_index_v2(index)

    assert first == second
    assert report_content_fingerprint(report) not in first
    assert '"symbol"' not in first
    assert '"fingerprint_version": "semantic_fingerprint.v1.sha256"' in first


def test_schema_evidence_accepts_v5_and_v6_but_not_bool_or_int() -> None:
    v5 = v2_entry(build_report(schema_version="5"))
    v6 = v2_entry(build_report(schema_version="6"))

    assert len(parse_reports_index({"schema_version": 2, "reports": [v5, v6]}).bindings) == 2
    v5["schema_version"] = True
    with pytest.raises(IdentityMetadataError, match="invalid_schema_version"):
        parse_reports_index({"schema_version": 2, "reports": [v5]})

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.identity_lifecycle import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    V1ProvisionalBinding,
    V2IdentityBinding,
    allocate_identity,
    make_verified_report_evidence,
    parse_v1_index,
    parse_v2_index,
    verify_existing_identity,
    verify_report_evidence,
)
from quant_advisor_research.publisher import report_content_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DIGEST_B = "b" * 64


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
                "reference_time": "2026-06-21T23:59:59Z",
                "expires_at": "2026-06-28T12:00:00.123456Z",
                "freshness": {
                    "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                    "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
                },
            }
        )
    return report


def digest_for(report: dict) -> str:
    return hashlib.sha256(report_content_fingerprint(report).encode()).hexdigest()


def v1_binding(as_of: str = "2026-06-20") -> V1ProvisionalBinding:
    return parse_v1_index(
        {
            "schema_version": 1,
            "reports": [
                {
                    "as_of": as_of,
                    "cadence": "weekly",
                    "json": f"advisory_report_{as_of}.json",
                    "html": f"{as_of}-weekly-model-recommendations.html",
                }
            ],
        }
    ).bindings[0]


def v2_binding(report: dict, *, variant: bool = False, digest: str | None = None) -> V2IdentityBinding:
    as_of = report["as_of"]
    digest = digest or digest_for(report)
    suffix = f".variant-{digest}" if variant else ""
    entry = {
        "period_key": "weekly:2026-06-15:2026-06-21",
        "as_of": as_of,
        "cadence": "weekly",
        "schema_version": report["schema_version"],
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint_digest": digest,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-weekly-model-recommendations{suffix}.html",
        "canonical_identity": not variant,
        "display_primary": False,
        "display_order": 3,
    }
    return parse_v2_index({"schema_version": 2, "reports": [entry]}).bindings[0]


def test_v1_verification_returns_evidence_only() -> None:
    report = build_report()

    evidence = verify_report_evidence(report, provisional=v1_binding())

    assert evidence.status == "VERIFIED_REPORT_EVIDENCE"
    assert not hasattr(evidence, "json_name")
    assert not hasattr(evidence, "canonical_identity")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(as_of="2026-06-21"),
        lambda report: report.update(cadence="daily"),
        lambda report: report.update(schema_version=5),
    ],
)
def test_verification_rejects_report_metadata_mismatch(mutation) -> None:
    report = build_report()
    mutation(report)

    with pytest.raises(IdentityMetadataError, match="report_invalid|identity_metadata_mismatch"):
        verify_report_evidence(report, provisional=v1_binding())


def test_verification_rejects_expected_digest_mismatch() -> None:
    with pytest.raises(IdentityMetadataError, match="identity_content_conflict"):
        verify_report_evidence(
            build_report(),
            expected=make_verified_report_evidence(
                as_of="2026-06-20", cadence="weekly", schema_version="5", fingerprint_digest=DIGEST_B
            ),
        )


@pytest.mark.parametrize("bad_value", [set(["bad"]), Path("bad")])
def test_verification_fingerprint_serialization_failures_are_sanitized(bad_value: object) -> None:
    report = build_report()
    report["unserializable"] = bad_value

    with pytest.raises(IdentityMetadataError, match="report_invalid"):
        verify_report_evidence(report)


def test_verification_circular_value_is_sanitized() -> None:
    report = build_report()
    cycle: list[object] = []
    cycle.append(cycle)
    report["circular"] = cycle

    with pytest.raises(IdentityMetadataError, match="report_invalid"):
        verify_report_evidence(report)


def test_forged_or_replaced_evidence_cannot_be_allocated() -> None:
    evidence = verify_report_evidence(build_report())
    forged = replace(evidence, fingerprint_digest=DIGEST_B)

    with pytest.raises(IdentityMetadataError, match="report_evidence_untrusted"):
        allocate_identity(forged, current_period_key=evidence.period_key)


def test_existing_identity_requires_report_bytes_and_digest_match() -> None:
    first = build_report()
    binding = v2_binding(first)

    with pytest.raises(IdentityMetadataError, match="identity_content_conflict"):
        verify_existing_identity(replace_report_content(first), binding)


def replace_report_content(report: dict) -> dict:
    changed = json.loads(json.dumps(report))
    changed["recommendations"][0]["reasons"] = ["changed content"]
    return changed


def test_exact_verified_identity_is_reused_immutably() -> None:
    report = build_report()
    evidence = verify_report_evidence(report)
    existing = verify_existing_identity(report, v2_binding(report))

    allocated = allocate_identity(evidence, existing_identities=[existing])

    assert allocated.json_name == existing.binding.json_name
    assert allocated.html_name == existing.binding.html_name
    assert allocated.canonical_identity is True


def test_current_period_without_existing_canonical_allocates_canonical() -> None:
    evidence = verify_report_evidence(build_report())

    allocated = allocate_identity(evidence, current_period_key=evidence.period_key)

    assert allocated.canonical_identity is True
    assert ".variant-" not in allocated.json_name


def test_current_period_with_existing_different_canonical_allocates_variant() -> None:
    old_report = build_report()
    new_report = replace_report_content(old_report)
    old_identity = verify_existing_identity(old_report, v2_binding(old_report))
    new_evidence = verify_report_evidence(new_report)

    allocated = allocate_identity(new_evidence, existing_identities=[old_identity], current_period_key=new_evidence.period_key)

    assert allocated.canonical_identity is False
    assert f".variant-{new_evidence.fingerprint_digest}" in allocated.json_name
    assert allocated.json_name != old_identity.binding.json_name


def test_historical_new_content_always_allocates_variant() -> None:
    evidence = verify_report_evidence(build_report())

    allocated = allocate_identity(evidence)

    assert allocated.canonical_identity is False
    assert f".variant-{evidence.fingerprint_digest}" in allocated.html_name


def test_allocation_is_input_order_independent() -> None:
    first = build_report()
    second = replace_report_content(first)
    first_identity = verify_existing_identity(first, v2_binding(first))
    second_digest = digest_for(second)
    second_binding = replace(
        v2_binding(first),
        fingerprint_digest=second_digest,
        json_name=f"advisory_report_{second['as_of']}.variant-{second_digest}.json",
        html_name=f"{second['as_of']}-weekly-model-recommendations.variant-{second_digest}.html",
        canonical_identity=False,
    )
    second_identity = verify_existing_identity(second, second_binding)
    evidence = verify_report_evidence(build_report(as_of="2026-06-27"))

    one = allocate_identity(evidence, existing_identities=[first_identity, second_identity])
    two = allocate_identity(evidence, existing_identities=[second_identity, first_identity])

    assert one == two

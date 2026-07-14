from __future__ import annotations

import hashlib
import json
import gc
import pickle
import weakref
import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.identity_lifecycle import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    V1ProvisionalBinding,
    V2IdentityBinding,
    V2IdentityIndex,
    allocate_identity,
    make_complete_identity_inventory,
    make_verified_report_evidence,
    parse_v1_index,
    parse_v2_index,
    verify_existing_identity,
    verify_report_evidence,
)
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.time_contract import canonical_reference_time, normalize_aware_datetime


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
        generated_at = normalize_aware_datetime(report["generated_at"])
        reference_time = canonical_reference_time(dt.date.fromisoformat(as_of))
        report.update(
            {
                "schema_version": "6",
                "contract_version": "model_recommendations.v6",
                "reference_time": reference_time.isoformat().replace("+00:00", "Z"),
                "expires_at": (generated_at + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z"),
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


def test_public_candidate_requires_explicit_report_revalidation_for_trust() -> None:
    report = build_report()
    candidate = make_verified_report_evidence(
        as_of=report["as_of"], cadence=report["cadence"], schema_version=report["schema_version"],
        fingerprint_digest=digest_for(report),
    )
    assert candidate.status == "UNTRUSTED_REPORT_EVIDENCE_CANDIDATE"
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, ()), ())

    with pytest.raises(IdentityMetadataError, match="report_evidence_untrusted"):
        allocate_identity(candidate, inventory=inventory, current_period_key=candidate.period_key)

    trusted = verify_report_evidence(report, expected=candidate)
    assert allocate_identity(trusted, inventory=inventory, current_period_key=trusted.period_key).canonical_identity


def test_equal_copy_and_pickle_roundtrip_do_not_retain_ephemeral_trust() -> None:
    trusted = verify_report_evidence(build_report())
    copied = replace(trusted)
    unpickled = pickle.loads(pickle.dumps(trusted))
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, ()), ())

    for candidate in (copied, unpickled):
        with pytest.raises(IdentityMetadataError, match="report_evidence_untrusted"):
            allocate_identity(candidate, inventory=inventory)


def test_legacy_subset_argument_fails_closed() -> None:
    trusted = verify_report_evidence(build_report())

    with pytest.raises(IdentityMetadataError, match="identity_inventory_required"):
        allocate_identity(trusted, existing_identities=[])


def test_report_capability_registry_does_not_keep_evidence_alive() -> None:
    trusted = verify_report_evidence(build_report())
    reference = weakref.ref(trusted)
    del trusted
    gc.collect()

    assert reference() is None


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
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (existing.binding,)), (existing,))

    allocated = allocate_identity(evidence, inventory=inventory)

    assert allocated.json_name == existing.binding.json_name
    assert allocated.html_name == existing.binding.html_name
    assert allocated.canonical_identity is True


def test_current_period_without_existing_canonical_allocates_canonical() -> None:
    evidence = verify_report_evidence(build_report())
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, ()), ())

    allocated = allocate_identity(evidence, inventory=inventory, current_period_key=evidence.period_key)

    assert allocated.canonical_identity is True
    assert ".variant-" not in allocated.json_name


def test_current_period_with_existing_different_canonical_allocates_variant() -> None:
    old_report = build_report()
    new_report = replace_report_content(old_report)
    old_identity = verify_existing_identity(old_report, v2_binding(old_report))
    new_evidence = verify_report_evidence(new_report)
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (old_identity.binding,)), (old_identity,))

    allocated = allocate_identity(new_evidence, inventory=inventory, current_period_key=new_evidence.period_key)

    assert allocated.canonical_identity is False
    assert f".variant-{new_evidence.fingerprint_digest}" in allocated.json_name
    assert allocated.json_name != old_identity.binding.json_name


def test_same_period_digest_with_different_as_of_fails_closed_without_new_variant() -> None:
    old_report = build_report(as_of="2026-06-20")
    new_report = build_report(as_of="2026-06-21")
    old_identity = verify_existing_identity(old_report, v2_binding(old_report))
    new_evidence = verify_report_evidence(new_report)
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (old_identity.binding,)), (old_identity,))

    with pytest.raises(IdentityMetadataError, match="identity_metadata_conflict"):
        allocate_identity(new_evidence, inventory=inventory)


def test_same_period_digest_with_different_schema_fails_closed() -> None:
    old_report = build_report(schema_version="5")
    new_report = build_report(schema_version="6")
    old_identity = verify_existing_identity(old_report, v2_binding(old_report))
    new_evidence = verify_report_evidence(new_report)
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (old_identity.binding,)), (old_identity,))

    with pytest.raises(IdentityMetadataError, match="identity_metadata_conflict"):
        allocate_identity(new_evidence, inventory=inventory)


def test_same_digest_across_periods_does_not_reuse_old_identity() -> None:
    old_report = build_report(as_of="2026-06-20")
    new_report = build_report(as_of="2026-06-27")
    old_identity = verify_existing_identity(old_report, v2_binding(old_report))
    new_evidence = verify_report_evidence(new_report)
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (old_identity.binding,)), (old_identity,))

    allocated = allocate_identity(new_evidence, inventory=inventory)

    assert allocated.canonical_identity is False
    assert allocated.fingerprint_digest == old_identity.report_digest


def test_historical_new_content_always_allocates_variant() -> None:
    evidence = verify_report_evidence(build_report())
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, ()), ())

    allocated = allocate_identity(evidence, inventory=inventory)

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
    inventory = make_complete_identity_inventory(
        V2IdentityIndex(2, (first_identity.binding, second_identity.binding)),
        [first_identity, second_identity],
    )

    one = allocate_identity(evidence, inventory=inventory)
    two = allocate_identity(evidence, inventory=inventory)

    assert one == two


def test_complete_inventory_requires_one_to_one_full_index_coverage() -> None:
    report = build_report()
    existing = verify_existing_identity(report, v2_binding(report))
    full_index = V2IdentityIndex(2, (existing.binding,))

    with pytest.raises(IdentityMetadataError, match="identity_inventory_incomplete"):
        make_complete_identity_inventory(full_index, ())
    with pytest.raises(IdentityMetadataError, match="identity_inventory_incomplete"):
        make_complete_identity_inventory(V2IdentityIndex(2, ()), (existing,))


def test_complete_inventory_rejects_duplicate_or_filtered_bindings() -> None:
    report = build_report()
    existing = verify_existing_identity(report, v2_binding(report))
    duplicate_index = V2IdentityIndex(2, (existing.binding, existing.binding))

    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_identity_inventory(duplicate_index, (existing, existing))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda binding: "malformed",
        lambda binding: replace(binding, display_order=True),
        lambda binding: replace(binding, json_name=Path("absolute")),
        lambda binding: replace(binding, fingerprint_version="other"),
    ],
)
def test_complete_inventory_sanitizes_malformed_public_index_bindings(mutation) -> None:
    existing = verify_existing_identity(build_report(), v2_binding(build_report()))
    malformed = mutation(existing.binding)

    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_identity_inventory(V2IdentityIndex(2, (malformed,)), (existing,))


def test_rehydrated_identity_evidence_requires_binding_revalidation() -> None:
    report = build_report()
    trusted = verify_existing_identity(report, v2_binding(report))
    reconstructed = pickle.loads(pickle.dumps(trusted))

    with pytest.raises(IdentityMetadataError, match="identity_evidence_untrusted"):
        make_complete_identity_inventory(V2IdentityIndex(2, (trusted.binding,)), (reconstructed,))

    revalidated = verify_existing_identity(report, trusted.binding)
    inventory = make_complete_identity_inventory(V2IdentityIndex(2, (revalidated.binding,)), (revalidated,))
    assert allocate_identity(verify_report_evidence(report), inventory=inventory).json_name == revalidated.binding.json_name

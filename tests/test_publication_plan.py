from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifact_integrity import artifact_integrity_digest
from quant_advisor_research.identity_lifecycle import FINGERPRINT_VERSION
from quant_advisor_research.identity_v3 import parse_v3_index
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.publication_plan import (
    PublicationEntry,
    PublicationPlanError,
    PublicationRole,
    QuarantineEvidence,
    SelectedCandidate,
    build_publication_plan,
)
from quant_advisor_research.time_contract import contract_version_for_schema


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_VERSION = "validated_report.v1.canonical-json.sha256"


def report(*, as_of: str = "2026-06-20", generated_at: str | None = None) -> dict:
    value = build_advisory_report(
        as_of=as_of,
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if generated_at is not None:
        value["generated_at"] = generated_at
    return value


def binding_entry(value: dict, *, canonical: bool) -> dict[str, object]:
    as_of = value["as_of"]
    cadence = value["cadence"]
    schema = value["schema_version"]
    contract = contract_version_for_schema(schema)
    semantic = hashlib.sha256(report_content_fingerprint(value).encode("utf-8")).hexdigest()
    artifact = artifact_integrity_digest(value)
    suffix = "" if canonical else f".variant-{artifact}"
    return {
        "period_key": canonical_period_identity(cadence, as_of).key,
        "as_of": as_of,
        "cadence": cadence,
        "report_schema_version": schema,
        "contract_version": contract,
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic,
        "artifact_integrity_version": ARTIFACT_VERSION,
        "artifact_integrity_digest": artifact,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": "V3_CANONICAL" if canonical else "V3_VARIANT",
        "canonical_identity": canonical,
        "display_primary": False,
        "display_order": 0,
    }


def bindings_for(*pairs: tuple[dict, bool]):
    payload = {"schema_version": 3, "reports": [binding_entry(value, canonical=canonical) for value, canonical in pairs]}
    return parse_v3_index(payload).bindings


def candidate(value: dict, source: str) -> SelectedCandidate:
    return SelectedCandidate.from_report(value, source_identity=source)


def entry(value: dict, binding, role: PublicationRole, *, primary: bool = False, order: int = 0) -> PublicationEntry:
    return PublicationEntry(candidate(value, f"source-{value['as_of']}-{binding.identity_class}"), binding, role, primary, order)


def test_current_source_can_bind_variant_public_target() -> None:
    old = report()
    current = report(generated_at="2026-07-15T00:00:00Z")
    canonical, variant = bindings_for((old, True), (current, False))

    plan = build_publication_plan(
        [
            entry(old, canonical, PublicationRole.RECOVERED_HISTORY),
            entry(current, variant, PublicationRole.MANDATORY_CURRENT, primary=True),
        ]
    )

    current_entry = next(item for item in plan.entries if item.role is PublicationRole.MANDATORY_CURRENT)
    assert ".variant-" in current_entry.binding.json_name
    assert current_entry.candidate.source_identity != current_entry.binding.json_name
    assert current_entry.display_primary is True


def test_recovered_only_or_missing_current_fails_closed() -> None:
    value = report()
    binding = bindings_for((value, True))[0]
    recovered = entry(value, binding, PublicationRole.RECOVERED_HISTORY)

    with pytest.raises(PublicationPlanError, match="mandatory_current_invalid"):
        build_publication_plan([recovered])
    with pytest.raises(PublicationPlanError, match="mandatory_current_invalid"):
        build_publication_plan([])


def test_recovered_entry_cannot_claim_current_by_source_or_metadata() -> None:
    value = report()
    binding = bindings_for((value, True))[0]
    recovered = entry(value, binding, PublicationRole.RECOVERED_HISTORY)

    with pytest.raises(PublicationPlanError, match="mandatory_current_invalid"):
        build_publication_plan([recovered, dataclasses.replace(recovered, role=PublicationRole.RECOVERED_HISTORY)])


def test_legacy_binding_is_not_a_publication_plan_identity() -> None:
    value = report()
    binding = bindings_for((value, True))[0]
    legacy = dataclasses.replace(binding, identity_class="LEGACY_V2")

    with pytest.raises(PublicationPlanError, match="legacy_binding_not_migrated"):
        entry(value, legacy, PublicationRole.MANDATORY_CURRENT)


def test_metadata_and_digest_mismatch_fail_closed() -> None:
    value = report()
    changed = report(generated_at="2026-07-15T00:00:00Z")
    canonical = bindings_for((value, True))[0]

    with pytest.raises(PublicationPlanError, match="candidate_binding_mismatch"):
        entry(changed, canonical, PublicationRole.MANDATORY_CURRENT)


def test_duplicate_public_targets_fail_before_publication() -> None:
    first = report()
    first_binding = bindings_for((first, True))[0]

    with pytest.raises(PublicationPlanError, match="publication_target_collision|identity_binding_invalid"):
        build_publication_plan([
            entry(first, first_binding, PublicationRole.MANDATORY_CURRENT),
            entry(first, first_binding, PublicationRole.RECOVERED_HISTORY),
        ])


@pytest.mark.parametrize("display_primary,display_order", [(True, True), (False, -1)])
def test_malformed_display_evidence_fails_closed(display_primary: bool, display_order: int) -> None:
    value = report()
    binding = bindings_for((value, True))[0]

    with pytest.raises(PublicationPlanError, match="display_evidence_invalid"):
        entry(value, binding, PublicationRole.MANDATORY_CURRENT, primary=display_primary, order=display_order)


def test_plan_normalization_is_permutation_stable_and_quarantine_sanitized() -> None:
    older = report(as_of="2026-06-12")
    current = report()
    old_binding, current_binding = bindings_for((older, True), (current, True))
    old_entry = entry(older, old_binding, PublicationRole.RECOVERED_HISTORY, order=3)
    current_entry = entry(current, current_binding, PublicationRole.MANDATORY_CURRENT, primary=True, order=0)
    quarantine = QuarantineEvidence("bad-artifact", "INVALID", "contract_invalid")

    left = build_publication_plan([old_entry, current_entry], quarantine=[quarantine])
    right = build_publication_plan([current_entry, old_entry], quarantine=[quarantine])

    assert left == right
    assert left.preflight_targets == tuple(item.targets for item in left.entries)
    assert all("/" not in item.source_identity for item in left.quarantine)


def test_candidate_snapshot_is_stable_after_input_mutation() -> None:
    value = report()
    selected = candidate(value, "stable-source")
    digest = selected.artifact_integrity_digest
    value["generated_at"] = "2026-07-15T00:00:00Z"

    assert selected.artifact_integrity_digest == digest
    assert selected.report_snapshot["generated_at"] != value["generated_at"]


@pytest.mark.parametrize("bad_source", ["/tmp/report.json", "../report.json", "", " source"])
def test_source_identity_is_sanitized_and_not_a_path(bad_source: str) -> None:
    with pytest.raises(PublicationPlanError, match="candidate_source_identity_invalid"):
        candidate(report(), bad_source)

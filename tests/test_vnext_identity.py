from __future__ import annotations

import hashlib
import json
import dataclasses
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifact_integrity import artifact_integrity_digest
from quant_advisor_research.identity_lifecycle import FINGERPRINT_VERSION
from quant_advisor_research.identity_v3 import V3_CANONICAL, V3_VARIANT
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.publication_plan import PublicationRole
from quant_advisor_research.time_contract import contract_version_for_schema
from quant_advisor_research.vnext_identity import (
    VNEXT_INDEX_SCHEMA,
    AllocationContext,
    DisplayPlacement,
    RequestedArtifactSet,
    VNextIdentityError,
    VNextIdentityIndex,
    allocate_vnext_identity,
    empty_vnext_index,
    parse_vnext_index,
    serialize_vnext_index,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_VERSION = "validated_report.v1.canonical-json.sha256"
REQUESTED = RequestedArtifactSet(False, False)
DISPLAY = DisplayPlacement(False, 0)


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


def binding_payload(value: dict, *, canonical: bool) -> dict[str, object]:
    as_of = value["as_of"]
    cadence = value["cadence"]
    schema = value["schema_version"]
    semantic = hashlib.sha256(report_content_fingerprint(value).encode("utf-8")).hexdigest()
    artifact = artifact_integrity_digest(value)
    suffix = "" if canonical else f".variant-{artifact}"
    return {
        "period_key": canonical_period_identity(cadence, as_of).key,
        "as_of": as_of,
        "cadence": cadence,
        "report_schema_version": schema,
        "contract_version": contract_version_for_schema(schema),
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic,
        "artifact_integrity_version": ARTIFACT_VERSION,
        "artifact_integrity_digest": artifact,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": V3_CANONICAL if canonical else V3_VARIANT,
        "canonical_identity": canonical,
        "display_primary": False,
        "display_order": 0,
    }


def index_for(*pairs: tuple[dict, bool]) -> VNextIdentityIndex:
    return parse_vnext_index({
        "schema_version": VNEXT_INDEX_SCHEMA,
        "entries": [binding_payload(value, canonical=canonical) for value, canonical in pairs],
    })


def allocate(value: dict, index: VNextIdentityIndex, context: AllocationContext, display: DisplayPlacement = DISPLAY):
    return allocate_vnext_identity(
        value,
        index=index,
        context=context,
        requested_artifacts=REQUESTED,
        display_placement=display,
        source_identity=f"source-{value['as_of']}",
    )


def test_empty_current_bootstraps_clean_canonical_and_publication_plan() -> None:
    value = report()
    result = allocate(value, empty_vnext_index(), AllocationContext.current_mandatory(canonical_period_identity("weekly", value["as_of"]).key))

    assert result.reused_existing is False
    assert result.binding.identity_class == V3_CANONICAL
    assert result.publication_plan is not None
    assert result.publication_entry is not None
    assert result.publication_entry.role is PublicationRole.MANDATORY_CURRENT


def test_current_rerun_allocates_artifact_digest_variant() -> None:
    old = report()
    current = report(generated_at="2026-07-15T00:00:00Z")
    index = index_for((old, True))
    result = allocate(current, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, 1))

    assert result.binding.identity_class == V3_VARIANT
    assert result.binding.canonical_identity is False
    assert result.binding.artifact_integrity_digest in result.binding.json_name
    assert result.publication_entry is not None
    assert result.publication_entry.display_primary is True


def test_exact_hit_requires_complete_policy_and_exact_miss_is_stable() -> None:
    value = report()
    index = index_for((value, True))
    result = allocate(value, index, AllocationContext.exact_artifact_reuse())
    assert result.reused_existing is True
    assert result.publication_plan is None

    with pytest.raises(VNextIdentityError, match="identity_reuse_mismatch"):
        allocate_vnext_identity(
            value,
            index=index,
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=RequestedArtifactSet(True, False),
            display_placement=DISPLAY,
            source_identity="source-2026-06-20",
        )
    changed = report(generated_at="2026-07-15T00:00:00Z")
    with pytest.raises(VNextIdentityError, match="exact_artifact_not_found"):
        allocate_vnext_identity(
            changed,
            index=index,
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
            source_identity="source-changed",
        )


def test_historical_requires_existing_canonical_and_then_allocates_variant() -> None:
    value = report()
    with pytest.raises(VNextIdentityError, match="canonical_bootstrap_required"):
        allocate(report(), empty_vnext_index(), AllocationContext.historical_recovery())
    changed = report(generated_at="2026-07-15T00:00:00Z")
    result = allocate(changed, index_for((value, True)), AllocationContext.historical_recovery())
    assert result.binding.identity_class == V3_VARIANT
    assert result.publication_plan is None


def test_malformed_display_is_rejected_before_exact_miss() -> None:
    with pytest.raises(VNextIdentityError, match="display_evidence_invalid"):
        allocate_vnext_identity(
            report(generated_at="2026-07-15T00:00:00Z"),
            index=empty_vnext_index(),
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
            display_placement=DisplayPlacement(False, -1),
            source_identity="source-bad-display",
        )


def test_legacy_binding_is_rejected_without_old_index_fallback() -> None:
    value = report()
    legacy = dataclasses.replace(index_for((value, True)).bindings[0], identity_class="LEGACY_V2")
    with pytest.raises(VNextIdentityError, match="legacy_identity_rejected"):
        serialize_vnext_index(VNextIdentityIndex(VNEXT_INDEX_SCHEMA, (legacy,)))


def test_wire_codec_is_independent_strict_and_deterministic() -> None:
    value = report()
    index = index_for((value, True))
    encoded = serialize_vnext_index(index)
    assert json.loads(encoded)["schema_version"] == VNEXT_INDEX_SCHEMA
    assert parse_vnext_index(encoded and json.loads(encoded)) == index
    assert serialize_vnext_index(parse_vnext_index(json.loads(encoded))) == encoded

    with pytest.raises(VNextIdentityError, match="unsupported_vnext_schema"):
        parse_vnext_index({"schema_version": "old.identity.v1", "entries": []})
    with pytest.raises(VNextIdentityError, match="identity_index_invalid"):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [], "reports": []})


def test_wire_entries_are_canonicalized_independent_of_input_order() -> None:
    older = report(as_of="2026-06-12")
    newer = report()
    left = index_for((older, True), (newer, True))
    right = VNextIdentityIndex(VNEXT_INDEX_SCHEMA, tuple(reversed(left.bindings)))

    assert serialize_vnext_index(left) == serialize_vnext_index(right)


def test_duplicate_target_and_digest_conflicts_fail_closed() -> None:
    value = report()
    binding = index_for((value, True)).bindings[0]
    duplicate = VNextIdentityIndex(VNEXT_INDEX_SCHEMA, (binding, binding))
    with pytest.raises(VNextIdentityError, match="identity_content_conflict|identity_target_collision"):
        serialize_vnext_index(duplicate)


def test_input_permutation_does_not_change_wire_or_current_plan() -> None:
    value = report()
    index = index_for((value, True))
    left = allocate(value, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DISPLAY)
    right = allocate(dict(reversed(list(value.items()))), index, AllocationContext.current_mandatory(index.bindings[0].period_key), DISPLAY)
    assert left == right
    assert serialize_vnext_index(index) == serialize_vnext_index(parse_vnext_index(json.loads(serialize_vnext_index(index))))


def test_source_identity_is_required_and_sanitized() -> None:
    with pytest.raises(VNextIdentityError, match="candidate_source_identity_invalid"):
        allocate_vnext_identity(
            report(),
            index=empty_vnext_index(),
            context=AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
            source_identity="/absolute/report.json",
        )


@pytest.mark.parametrize("bad", [None, True, 1, "report.json"])
def test_bad_report_shape_is_sanitized(bad: object) -> None:
    with pytest.raises(VNextIdentityError) as caught:
        allocate_vnext_identity(
            bad,  # type: ignore[arg-type]
            index=empty_vnext_index(),
            context=AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
            source_identity="source-bad",
        )
    assert "/" not in str(caught.value)

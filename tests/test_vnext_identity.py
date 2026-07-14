from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifact_integrity import artifact_integrity_digest
from quant_advisor_research.identity_lifecycle import FINGERPRINT_VERSION
from quant_advisor_research.identity_v3 import V3_CANONICAL, V3_VARIANT
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publication_plan import PublicationEntry, PublicationRole, SelectedCandidate
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.time_contract import contract_version_for_schema
from quant_advisor_research.vnext_identity import (
    VNEXT_INDEX_SCHEMA,
    AllocationContext,
    DisplayPlacement,
    RequestedArtifactSet,
    VNextIdentityError,
    allocate_vnext_identity,
    empty_vnext_index,
    parse_vnext_index,
    serialize_vnext_index,
)
from quant_advisor_research.vnext_binding import MAX_SAFE_JSON_INTEGER


ROOT = Path(__file__).resolve().parents[1]
REQUESTED = RequestedArtifactSet(False, False)
DISPLAY = DisplayPlacement(False, 0)
ARTIFACT_VERSION = "validated_report.v1.canonical-json.sha256"


def report(*, as_of: str = "2026-06-20", cadence: str = "weekly", generated_at: str | None = None) -> dict:
    value = build_advisory_report(
        as_of=as_of,
        cadence=cadence,
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if generated_at is not None:
        value["generated_at"] = generated_at
    return value


def binding_payload(value: dict, *, canonical: bool, md: bool = False, manifest: bool = False) -> dict[str, object]:
    as_of = value["as_of"]
    cadence = value["cadence"]
    artifact = artifact_integrity_digest(value)
    semantic = hashlib.sha256(report_content_fingerprint(value).encode("utf-8")).hexdigest()
    suffix = "" if canonical else f".variant-{artifact}"
    stem = f"advisory_report_{as_of}-{cadence}"
    payload: dict[str, object] = {
        "period_key": canonical_period_identity(cadence, as_of).key,
        "as_of": as_of,
        "cadence": cadence,
        "report_schema_version": value["schema_version"],
        "contract_version": contract_version_for_schema(value["schema_version"]),
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic,
        "artifact_integrity_version": ARTIFACT_VERSION,
        "artifact_integrity_digest": artifact,
        "json": f"{stem}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": V3_CANONICAL if canonical else V3_VARIANT,
        "canonical_identity": canonical,
        "display_primary": False,
        "display_order": 0,
    }
    if md:
        payload["md"] = f"{stem}{suffix}.md"
    if manifest:
        payload["manifest"] = f"{stem}{suffix}.json.manifest.json"
    return payload


def index_for(*pairs: tuple[dict, bool]) -> object:
    return parse_vnext_index({
        "schema_version": VNEXT_INDEX_SCHEMA,
        "entries": [binding_payload(value, canonical=canonical) for value, canonical in pairs],
    })


def allocate(value: dict, index, context, display: DisplayPlacement = DISPLAY):
    return allocate_vnext_identity(
        value,
        index=index,
        context=context,
        requested_artifacts=REQUESTED,
        display_placement=display,
        source_identity=f"source-{value['as_of']}-{value['cadence']}",
    )


def test_empty_current_bootstraps_canonical_and_plan() -> None:
    value = report()
    period = canonical_period_identity(value["cadence"], value["as_of"]).key
    result = allocate(value, empty_vnext_index(), AllocationContext.current_mandatory(period))
    assert result.binding.identity_class == V3_CANONICAL
    assert result.publication_entry is not None
    assert result.publication_entry.role is PublicationRole.MANDATORY_CURRENT


def test_current_exact_reuses_canonical_and_new_display_does_not_rewrite_binding() -> None:
    value = report()
    index = index_for((value, True))
    result = allocate(value, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, 8))
    assert result.reused_existing is True
    assert result.binding == index.bindings[0]
    assert result.binding.identity_class == V3_CANONICAL
    assert ".variant-" not in result.binding.json_name
    assert result.publication_entry is not None
    assert (result.publication_entry.display_primary, result.publication_entry.display_order) == (True, 8)


def test_publication_entry_namespace_is_required() -> None:
    value = report()
    binding = index_for((value, True)).bindings[0]
    with pytest.raises(TypeError):
        PublicationEntry(  # type: ignore[call-arg]
            SelectedCandidate.from_report(value, source_identity="source"),
            binding,
            PublicationRole.MANDATORY_CURRENT,
            False,
            0,
        )


def test_current_changed_artifact_in_occupied_period_is_variant() -> None:
    old = report()
    changed = report(generated_at="2026-07-15T00:00:00Z")
    index = index_for((old, True))
    result = allocate(changed, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, 1))
    assert result.binding.identity_class == V3_VARIANT
    assert result.binding.artifact_integrity_digest in result.binding.json_name


def test_historical_requires_canonical_and_allocates_variant_when_present() -> None:
    value = report()
    with pytest.raises(VNextIdentityError, match="canonical_bootstrap_required"):
        allocate(value, empty_vnext_index(), AllocationContext.historical_recovery())
    changed = report(generated_at="2026-07-15T00:00:00Z")
    result = allocate(changed, index_for((value, True)), AllocationContext.historical_recovery(), DisplayPlacement(True, 2))
    assert result.binding.identity_class == V3_VARIANT
    assert result.publication_plan is None


def test_exact_miss_validates_display_and_attachment_before_miss() -> None:
    with pytest.raises(VNextIdentityError, match="display_evidence_invalid"):
        allocate_vnext_identity(
            report(), index=empty_vnext_index(), context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED, display_placement=DisplayPlacement(False, -1), source_identity="source",
        )
    with pytest.raises(VNextIdentityError, match="publication_policy_invalid"):
        allocate_vnext_identity(
            report(), index=empty_vnext_index(), context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=replace(REQUESTED, include_markdown=1), display_placement=DISPLAY, source_identity="source",
        )


@pytest.mark.parametrize("order", [0, MAX_SAFE_JSON_INTEGER])
def test_display_order_safe_boundaries_are_accepted(order: int) -> None:
    value = report()
    index = index_for((value, True))
    result = allocate(value, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, order))
    assert result.publication_entry is not None
    assert result.publication_entry.display_order == order


@pytest.mark.parametrize("order", [-1, MAX_SAFE_JSON_INTEGER + 1, True, "1"])
def test_display_order_unsafe_values_are_rejected(order: object) -> None:
    value = report()
    index = index_for((value, True))
    with pytest.raises(VNextIdentityError, match="display_evidence_invalid|identity_reuse_mismatch"):
        allocate(value, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, order))  # type: ignore[arg-type]


@pytest.mark.parametrize("cadence", ["daily", "weekly", "monthly"])
def test_same_as_of_cadences_have_distinct_all_targets(cadence: str) -> None:
    value = report(cadence=cadence)
    payload = binding_payload(value, canonical=True, md=True, manifest=True)
    parsed = parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [payload]})
    binding = parsed.bindings[0]
    assert cadence in binding.json_name and cadence in binding.html_name
    assert cadence in binding.markdown_name and cadence in binding.manifest_name


def test_daily_weekly_monthly_same_as_of_coexist_without_collision() -> None:
    values = [report(cadence=cadence) for cadence in ("daily", "weekly", "monthly")]
    parsed = parse_vnext_index({
        "schema_version": VNEXT_INDEX_SCHEMA,
        "entries": [binding_payload(value, canonical=True, md=True, manifest=True) for value in values],
    })
    names = [name for binding in parsed.bindings for name in (
        binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name,
    ) if name is not None]
    assert len(names) == len(set(names)) == 12


@pytest.mark.parametrize("field", ["json", "html", "md", "manifest"])
def test_vnext_rejects_legacy_filename_for_each_declared_target(field: str) -> None:
    value = report()
    payload = binding_payload(value, canonical=True, md=True, manifest=True)
    payload[field] = {
        "json": f"advisory_report_{value['as_of']}.json",
        "html": f"{value['as_of']}-model-recommendations.html",
        "md": f"advisory_report_{value['as_of']}.md",
        "manifest": f"advisory_report_{value['as_of']}.json.manifest.json",
    }[field]
    with pytest.raises(VNextIdentityError):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [payload]})


@pytest.mark.parametrize("field", ["md", "manifest"])
def test_optional_attachment_omission_is_valid_but_null_is_rejected(field: str) -> None:
    value = report()
    omitted = binding_payload(value, canonical=True)
    assert parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [omitted]})
    explicit_null = binding_payload(value, canonical=True)
    explicit_null[field] = None
    with pytest.raises(VNextIdentityError):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [explicit_null]})


def test_variant_requires_full_artifact_digest_suffix_on_all_declared_targets() -> None:
    value = report(generated_at="2026-07-15T00:00:00Z")
    payload = binding_payload(value, canonical=False, md=True, manifest=True)
    parsed = parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [
        binding_payload(report(), canonical=True), payload,
    ]})
    assert parsed.bindings[1].artifact_integrity_digest in parsed.bindings[1].manifest_name
    payload["manifest"] = payload["manifest"].replace(".variant-", ".variant-" + "0")
    with pytest.raises(VNextIdentityError):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [binding_payload(report(), canonical=True), payload]})


@pytest.mark.parametrize("field", ["period_key", "report_schema_version", "contract_version", "semantic_fingerprint_version", "artifact_integrity_version", "semantic_digest", "artifact_integrity_digest", "identity_class"])
def test_cadence_aware_names_do_not_bypass_metadata_validation(field: str) -> None:
    value = report()
    payload = binding_payload(value, canonical=True)
    payload[field] = {
        "period_key": "weekly:2026-06-08:2026-06-14",
        "report_schema_version": "unknown",
        "contract_version": "model_recommendations.v6",
        "semantic_fingerprint_version": "wrong",
        "artifact_integrity_version": "wrong",
        "semantic_digest": "A" * 64,
        "artifact_integrity_digest": "B" * 64,
        "identity_class": "LEGACY_V2",
    }[field]
    with pytest.raises(VNextIdentityError):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [payload]})


def test_wire_round_trip_is_deterministic_and_strict() -> None:
    index = index_for((report(), True))
    encoded = serialize_vnext_index(index)
    assert serialize_vnext_index(parse_vnext_index(json.loads(encoded))) == encoded
    with pytest.raises(VNextIdentityError, match="unsupported_vnext_schema"):
        parse_vnext_index({"schema_version": "old.identity.v1", "entries": []})
    with pytest.raises(VNextIdentityError, match="identity_index_invalid"):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [], "reports": []})


def test_input_permutation_does_not_change_wire_or_plan() -> None:
    older = report(as_of="2026-06-12")
    current = report()
    left = index_for((older, True), (current, True))
    right = type(left)(left.schema_version, tuple(reversed(left.bindings)))
    assert serialize_vnext_index(left) == serialize_vnext_index(right)
    result = allocate(current, left, AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"))
    assert result.reused_existing is True


def test_legacy_binding_class_is_rejected_without_fallback() -> None:
    value = report()
    payload = binding_payload(value, canonical=True)
    payload["identity_class"] = "LEGACY_V2"
    with pytest.raises(VNextIdentityError, match="legacy_identity_rejected"):
        parse_vnext_index({"schema_version": VNEXT_INDEX_SCHEMA, "entries": [payload]})


@pytest.mark.parametrize("bad", [None, True, 1, "report.json"])
def test_bad_report_shape_is_sanitized(bad: object) -> None:
    with pytest.raises(VNextIdentityError):
        allocate_vnext_identity(
            bad, index=empty_vnext_index(),
            context=AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"),
            requested_artifacts=REQUESTED, display_placement=DISPLAY, source_identity="source",
        )

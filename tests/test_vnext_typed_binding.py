from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifact_integrity import artifact_integrity_digest
from quant_advisor_research.identity_lifecycle import FINGERPRINT_VERSION, IdentityMetadataError
from quant_advisor_research.identity_v3 import V3_CANONICAL, V3_VARIANT, V3IdentityBinding, parse_v3_index
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publication_plan import PublicationEntry, PublicationPlan, PublicationRole, SelectedCandidate
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.time_contract import contract_version_for_schema
from quant_advisor_research.vnext_binding import (
    MAX_SAFE_JSON_INTEGER,
    VNEXT_BINDING_VERSION,
    VNEXT_WIRE_NAMESPACE,
    VNextBindingError,
    VNextIdentityBinding,
    binding_payload,
    validate_vnext_binding,
)
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


ROOT = Path(__file__).resolve().parents[1]
REQUESTED = RequestedArtifactSet(False, False)
DISPLAY = DisplayPlacement(False, 0)
ARTIFACT_VERSION = "validated_report.v1.canonical-json.sha256"


def report(*, as_of="2026-06-20", cadence="weekly", generated_at=None):
    value = build_advisory_report(
        as_of=as_of, cadence=cadence,
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if generated_at is not None:
        value["generated_at"] = generated_at
    return value


def entry_payload(value: dict, *, canonical=True, md=False, manifest=False):
    as_of, cadence = value["as_of"], value["cadence"]
    artifact = artifact_integrity_digest(value)
    semantic = hashlib.sha256(report_content_fingerprint(value).encode()).hexdigest()
    suffix = "" if canonical else f".variant-{artifact}"
    stem = f"advisory_report_{as_of}-{cadence}"
    payload = {
        "binding_namespace": VNEXT_WIRE_NAMESPACE,
        "binding_version": VNEXT_BINDING_VERSION,
        "period_key": canonical_period_identity(cadence, as_of).key,
        "as_of": as_of, "cadence": cadence,
        "report_schema_version": value["schema_version"],
        "contract_version": contract_version_for_schema(value["schema_version"]),
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic,
        "artifact_integrity_version": ARTIFACT_VERSION,
        "artifact_integrity_digest": artifact,
        "json": f"{stem}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": V3_CANONICAL if canonical else V3_VARIANT,
        "canonical_identity": canonical, "display_primary": False, "display_order": 0,
    }
    if md:
        payload["md"] = f"{stem}{suffix}.md"
    if manifest:
        payload["manifest"] = f"{stem}{suffix}.json.manifest.json"
    return payload


def index_for(*values):
    return parse_vnext_index({
        "namespace": VNEXT_WIRE_NAMESPACE,
        "schema_version": VNEXT_INDEX_SCHEMA,
        "entries": [entry_payload(value, canonical=canonical) for value, canonical in values],
    })


def allocate(value, index, context, display=DISPLAY):
    return allocate_vnext_identity(
        value, index=index, context=context, requested_artifacts=REQUESTED,
        display_placement=display, source_identity=f"source-{value['as_of']}-{value['cadence']}",
    )


def test_empty_current_bootstraps_typed_canonical_and_plan() -> None:
    value = report()
    period = canonical_period_identity("weekly", value["as_of"]).key
    result = allocate(value, empty_vnext_index(), AllocationContext.current_mandatory(period))
    assert type(result.binding) is VNextIdentityBinding
    assert result.binding.identity_class == V3_CANONICAL
    assert result.publication_entry is not None


def test_exact_current_reuses_typed_canonical_with_new_display() -> None:
    value = report()
    index = index_for((value, True))
    result = allocate(value, index, AllocationContext.current_mandatory(index.bindings[0].period_key), DisplayPlacement(True, 4))
    assert result.reused_existing is True
    assert result.binding == index.bindings[0]
    assert result.publication_entry is not None
    assert (result.publication_entry.display_primary, result.publication_entry.display_order) == (True, 4)


def test_changed_current_is_typed_variant_and_historical_requires_canonical() -> None:
    old = report()
    changed = report(generated_at="2026-07-15T00:00:00Z")
    result = allocate(changed, index_for((old, True)), AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"))
    assert type(result.binding) is VNextIdentityBinding
    assert result.binding.identity_class == V3_VARIANT
    with pytest.raises(VNextIdentityError, match="canonical_bootstrap_required"):
        allocate(old, empty_vnext_index(), AllocationContext.historical_recovery())


def test_type_dispatch_is_explicit_and_no_namespace_flag_exists() -> None:
    assert "identity_namespace" not in PublicationEntry.__dataclass_fields__
    value = report()
    binding = index_for((value, True)).bindings[0]
    candidate = SelectedCandidate.from_report(value, source_identity="source")
    entry = PublicationEntry(candidate, binding, PublicationRole.MANDATORY_CURRENT, False, 0)
    assert type(entry.binding) is VNextIdentityBinding
    with pytest.raises(TypeError):
        PublicationEntry(candidate, binding, PublicationRole.MANDATORY_CURRENT, False, 0, "vnext")  # type: ignore[call-arg]


def test_legacy_binding_cannot_enter_vnext_index() -> None:
    value = report()
    payload = entry_payload(value)
    payload["identity_class"] = "LEGACY_V2"
    with pytest.raises(VNextIdentityError, match="legacy_identity_rejected"):
        parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1, "entries": [payload]})


def test_vnext_wire_cannot_decode_as_legacy_binding() -> None:
    value = report()
    binding = index_for((value, True)).bindings[0]
    assert type(binding) is VNextIdentityBinding
    assert not isinstance(binding, V3IdentityBinding)
    with pytest.raises(IdentityMetadataError):
        parse_v3_index({"schema_version": 3, "reports": [binding_payload(binding)]})


def test_vnext_shaped_legacy_type_cannot_enter_vnext_index() -> None:
    value = report()
    typed = index_for((value, True)).bindings[0]
    legacy_payload = binding_payload(typed)
    legacy_payload.pop("binding_namespace")
    legacy_payload.pop("binding_version")
    legacy_payload["json"] = f"advisory_report_{value['as_of']}.json"
    legacy_payload["html"] = f"{value['as_of']}-weekly-model-recommendations.html"
    legacy = parse_v3_index({"schema_version": 3, "reports": [legacy_payload]}).bindings[0]
    with pytest.raises(VNextIdentityError, match="vnext_binding_type_required"):
        from quant_advisor_research.vnext_identity import VNextIdentityIndex
        from quant_advisor_research.vnext_identity import serialize_vnext_index
        serialize_vnext_index(VNextIdentityIndex(1, (legacy,)))  # type: ignore[arg-type]


def test_direct_forged_typed_binding_is_revalidated() -> None:
    binding = validate_vnext_binding(entry_payload(report()))
    with pytest.raises(VNextBindingError, match="identity_binding_invalid"):
        replace(binding, display_order=MAX_SAFE_JSON_INTEGER + 1)


def test_publication_plan_dispatches_mixed_legacy_and_vnext_types() -> None:
    old = report(as_of="2026-06-12")
    current = report()
    typed = index_for((current, True)).bindings[0]
    legacy_payload = entry_payload(old)
    legacy_payload.pop("binding_namespace")
    legacy_payload.pop("binding_version")
    legacy_payload["json"] = f"advisory_report_{old['as_of']}.json"
    legacy_payload["html"] = f"{old['as_of']}-weekly-model-recommendations.html"
    legacy = parse_v3_index({"schema_version": 3, "reports": [legacy_payload]}).bindings[0]
    plan = PublicationPlan((
        PublicationEntry(SelectedCandidate.from_report(current, source_identity="current"), typed, PublicationRole.MANDATORY_CURRENT, True, 0),
        PublicationEntry(SelectedCandidate.from_report(old, source_identity="old"), legacy, PublicationRole.RECOVERED_HISTORY, False, 1),
    ))
    assert {type(entry.binding) for entry in plan.entries} == {VNextIdentityBinding, V3IdentityBinding}


@pytest.mark.parametrize("field", ["md", "manifest"])
def test_optional_omission_is_valid_null_is_not(field: str) -> None:
    value = report()
    payload = entry_payload(value)
    assert validate_vnext_binding(payload)
    payload[field] = None
    with pytest.raises(VNextBindingError, match="identity_name_invalid"):
        validate_vnext_binding(payload)


@pytest.mark.parametrize("order", [0, MAX_SAFE_JSON_INTEGER])
def test_display_order_boundaries(order: int) -> None:
    value = report()
    result = allocate(value, index_for((value, True)), AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"), DisplayPlacement(True, order))
    assert result.publication_entry is not None
    assert result.publication_entry.display_order == order


@pytest.mark.parametrize("order", [-1, MAX_SAFE_JSON_INTEGER + 1, True, "1"])
def test_display_order_invalid_in_memory(order: object) -> None:
    value = report()
    with pytest.raises(VNextIdentityError, match="display_evidence_invalid"):
        allocate(value, index_for((value, True)), AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"), DisplayPlacement(True, order))  # type: ignore[arg-type]


def test_display_order_invalid_on_wire() -> None:
    payload = entry_payload(report())
    payload["display_order"] = MAX_SAFE_JSON_INTEGER + 1
    with pytest.raises(VNextIdentityError, match="identity_binding_invalid"):
        parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1, "entries": [payload]})


def test_cadence_targets_and_variant_suffix_are_strict() -> None:
    old, changed = report(), report(generated_at="2026-07-15T00:00:00Z")
    payload = entry_payload(changed, canonical=False, md=True, manifest=True)
    parsed = parse_vnext_index({
        "namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1,
        "entries": [entry_payload(old), payload],
    })
    assert changed["cadence"] in parsed.bindings[1].json_name
    assert parsed.bindings[1].artifact_integrity_digest in parsed.bindings[1].manifest_name
    payload["manifest"] = payload["manifest"].replace(".variant-", ".variant-0")
    with pytest.raises(VNextIdentityError):
        parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1, "entries": [entry_payload(old), payload]})


def test_namespace_schema_and_roundtrip_are_strict() -> None:
    index = index_for((report(), True))
    encoded = serialize_vnext_index(index)
    assert serialize_vnext_index(parse_vnext_index(json.loads(encoded))) == encoded
    with pytest.raises(VNextIdentityError, match="unsupported_vnext_namespace"):
        parse_vnext_index({"namespace": "legacy", "schema_version": 1, "entries": []})
    with pytest.raises(VNextIdentityError, match="unsupported_vnext_schema"):
        parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 2, "entries": []})
    with pytest.raises(VNextIdentityError, match="identity_index_invalid"):
        parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1, "entries": [], "legacy": True})


def test_schema_contract_and_metadata_forgery_fail_closed() -> None:
    value = report()
    for field, replacement in {
        "report_schema_version": "unknown", "contract_version": "model_recommendations.v6",
        "period_key": "weekly:2026-06-08:2026-06-14", "semantic_digest": "A" * 64,
        "artifact_integrity_digest": "B" * 64, "binding_namespace": "legacy",
    }.items():
        payload = entry_payload(value)
        payload[field] = replacement
        with pytest.raises(VNextIdentityError):
            parse_vnext_index({"namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1, "entries": [payload]})


def test_same_as_of_cadences_have_no_target_collision() -> None:
    values = [report(cadence=cadence) for cadence in ("daily", "weekly", "monthly")]
    parsed = parse_vnext_index({
        "namespace": VNEXT_WIRE_NAMESPACE, "schema_version": 1,
        "entries": [entry_payload(value, md=True, manifest=True) for value in values],
    })
    names = [name for binding in parsed.bindings for name in (
        binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name,
    ) if name is not None]
    assert len(names) == len(set(names)) == 12


def test_permutation_and_collision_fail_closed() -> None:
    older, current = report(as_of="2026-06-12"), report()
    left = index_for((older, True), (current, True))
    right = type(left)(left.schema_version, tuple(reversed(left.bindings)))
    assert serialize_vnext_index(left) == serialize_vnext_index(right)
    duplicate = type(left)(left.schema_version, (left.bindings[0], left.bindings[0]))
    with pytest.raises(VNextIdentityError):
        serialize_vnext_index(duplicate)

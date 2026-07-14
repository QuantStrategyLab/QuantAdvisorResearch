from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.vnext_identity_v1 import (
    ARTIFACT_ALGORITHM_VERSION,
    MAX_SAFE_JSON_INTEGER,
    SEMANTIC_FINGERPRINT_VERSION,
    V3_CANONICAL,
    V3_VARIANT,
    VNEXT_BINDING_NAMESPACE,
    VNEXT_STATUS,
    VNextIdentityBinding,
    VNextIdentityError,
    VNextIdentityIndex,
    parse_vnext_index,
    serialize_vnext_index,
)
from quant_advisor_research.vnext_publication_plan import (
    AllocationContext,
    AllocationMode,
    DisplayPlacement,
    PublicationEntry,
    PublicationRole,
    RequestedArtifacts,
    SelectedCandidate,
    VNextPublicationError,
    allocate_identity,
    build_publication_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def report(*, as_of="2026-06-20", cadence="weekly", generated_at=None):
    value = build_advisory_report(
        as_of=as_of, cadence=cadence,
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if generated_at is not None:
        value["generated_at"] = generated_at
    return value


def candidate(value, source="source"):
    return SelectedCandidate.from_report(value, source_identity=source)


def binding(c, cls=V3_CANONICAL, *, md=False, manifest=False, primary=False, order=0):
    suffix = "" if cls == V3_CANONICAL else f".variant-{c.artifact_integrity_digest}"
    stem = f"advisory_report_{c.as_of}-{c.cadence}{suffix}"
    return VNextIdentityBinding(
        c.period_key, c.as_of, c.cadence, c.report_schema_version, c.contract_version,
        SEMANTIC_FINGERPRINT_VERSION, c.semantic_digest, ARTIFACT_ALGORITHM_VERSION,
        c.artifact_integrity_digest, f"{stem}.json",
        f"{c.as_of}-{c.cadence}-model-recommendations{suffix}.html",
        f"{stem}.md" if md else None,
        f"{stem}.json.manifest.json" if manifest else None,
        cls, cls == V3_CANONICAL, primary, order, VNEXT_STATUS,
    )


def wire(*entries):
    return {"schema_version": 1, "namespace": "qar_vnext_identity.v1", "reports": list(entries)}


def entry(c, cls=V3_CANONICAL, **kwargs):
    b = binding(c, cls, **kwargs)
    result = {
        "binding_namespace": VNEXT_BINDING_NAMESPACE,
        "period_key": b.period_key, "as_of": b.as_of, "cadence": b.cadence,
        "report_schema_version": b.report_schema_version, "contract_version": b.contract_version,
        "semantic_fingerprint_version": b.semantic_fingerprint_version, "semantic_digest": b.semantic_digest,
        "artifact_integrity_version": b.artifact_integrity_version, "artifact_integrity_digest": b.artifact_integrity_digest,
        "json": b.json_name, "html": b.html_name, "identity_class": b.identity_class,
        "canonical_identity": b.canonical_identity, "display_primary": b.display_primary,
        "display_order": b.display_order, "status": b.status,
    }
    if b.markdown_name is not None:
        result["md"] = b.markdown_name
    if b.manifest_name is not None:
        result["manifest"] = b.manifest_name
    return result


def test_clean_schema_v1_canonical_and_variant_roundtrip():
    current = candidate(report(generated_at="2026-06-21T00:00:00Z"))
    old = candidate(report())
    index = VNextIdentityIndex((binding(old), binding(current, V3_VARIANT, order=1)))
    payload = serialize_vnext_index(index)
    assert parse_vnext_index(payload) == index
    assert serialize_vnext_index(parse_vnext_index(payload)) == payload
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == json.dumps(
        serialize_vnext_index(parse_vnext_index(payload)), sort_keys=True, separators=(",", ":")
    )
    reversed_payload = wire(
        entry(current, V3_VARIANT, order=1),
        entry(old, order=0),
    )
    assert parse_vnext_index(payload) == parse_vnext_index(reversed_payload)
    assert serialize_vnext_index(parse_vnext_index(payload)) == serialize_vnext_index(parse_vnext_index(reversed_payload))


def test_daily_weekly_monthly_same_as_of_have_distinct_clean_targets():
    candidates = [candidate(report(cadence=cadence)) for cadence in ("daily", "weekly", "monthly")]
    index = VNextIdentityIndex(tuple(binding(item, order=position) for position, item in enumerate(candidates)))
    names = {item.json_name for item in index.bindings}
    assert len(names) == 3


@pytest.mark.parametrize("cadence", ["daily", "weekly", "monthly"])
def test_all_targets_are_cadence_aware_and_same_date_can_coexist(cadence):
    c = candidate(report(cadence=cadence))
    payload = wire(entry(c))
    parsed = parse_vnext_index(payload)
    assert parsed.bindings[0].html_name.startswith(f"{c.as_of}-{cadence}-")
    assert f"-{cadence}.json" in parsed.bindings[0].json_name


def test_variant_uses_full_artifact_digest_and_optional_attachments_are_omittable():
    c = candidate(report(generated_at="2026-06-21T00:00:00Z"))
    payload = wire(entry(candidate(report()), md=False), entry(c, V3_VARIANT, md=True, manifest=True, order=1))
    assert len(parse_vnext_index(payload).bindings) == 2
    bad = entry(c, V3_VARIANT, md=True)
    bad["md"] = bad["md"].replace(c.artifact_integrity_digest, "0" * 64)
    with pytest.raises(VNextIdentityError, match="target_digest_mismatch"):
        parse_vnext_index(wire(entry(candidate(report())), bad))


def test_explicit_null_optional_attachment_is_rejected():
    c = candidate(report())
    bad = entry(c)
    bad["md"] = None
    with pytest.raises(VNextIdentityError, match="invalid_target_name"):
        parse_vnext_index(wire(bad))


@pytest.mark.parametrize("field,value", [
    ("namespace", "legacy"), ("schema_version", 2), ("binding_namespace", "legacy"),
    ("status", "VERIFIED"), ("report_schema_version", 7), ("semantic_fingerprint_version", "future"),
    ("artifact_integrity_version", "future"), ("canonical_identity", False),
])
def test_unknown_or_forged_contract_fields_fail_closed(field, value):
    c = candidate(report())
    payload = wire(entry(c))
    if field in {"namespace", "schema_version"}:
        payload[field] = value
    else:
        payload["reports"][0][field] = value
    with pytest.raises(VNextIdentityError):
        parse_vnext_index(payload)


def test_legacy_filename_and_extra_wire_keys_never_enter_vnext():
    c = candidate(report())
    bad = entry(c)
    bad["json"] = f"advisory_report_{c.as_of}.json"
    with pytest.raises(VNextIdentityError):
        parse_vnext_index(wire(bad))
    bad = entry(c)
    bad["debug"] = "legacy"
    with pytest.raises(VNextIdentityError):
        parse_vnext_index(wire(bad))


def test_exactly_one_canonical_and_display_policy_per_period():
    c = candidate(report())
    variant = candidate(report(generated_at="2026-06-21T00:00:00Z"))
    with pytest.raises(VNextIdentityError, match="canonical_missing"):
        VNextIdentityIndex((binding(variant, V3_VARIANT),))
    with pytest.raises(VNextIdentityError, match="canonical_conflict"):
        VNextIdentityIndex((binding(c), binding(variant, V3_CANONICAL)))
    duplicate_primary = binding(variant, V3_VARIANT, primary=True)
    with pytest.raises(VNextIdentityError, match="display_primary_conflict"):
        VNextIdentityIndex((binding(c, primary=True), duplicate_primary))
    duplicate_order = binding(variant, V3_VARIANT, order=0)
    with pytest.raises(VNextIdentityError, match="display_order_conflict"):
        VNextIdentityIndex((binding(c), duplicate_order))


def test_same_exact_artifact_cannot_have_two_public_identities():
    c = candidate(report())
    canonical = binding(c, md=False)
    different_policy = binding(c, md=True)
    with pytest.raises(VNextIdentityError, match="identity_duplicate"):
        VNextIdentityIndex((canonical, different_policy))


def test_display_order_safe_integer_boundaries_and_bool_rejection():
    c = candidate(report())
    assert binding(c, order=MAX_SAFE_JSON_INTEGER).display_order == MAX_SAFE_JSON_INTEGER
    for value in (-1, MAX_SAFE_JSON_INTEGER + 1, True, "0"):
        with pytest.raises(VNextIdentityError, match="display_order_invalid"):
            binding(c, order=value)


def test_mapping_snapshot_and_serializer_are_deterministic():
    c = candidate(report())
    payload = wire(entry(c))
    ordered = OrderedDict((key, payload[key]) for key in reversed(list(payload)))
    assert parse_vnext_index(MappingProxyType(ordered)) == parse_vnext_index(payload)
    assert serialize_vnext_index(parse_vnext_index(payload)) == serialize_vnext_index(parse_vnext_index(ordered))


def test_allocation_modes_bootstrap_rerun_exact_and_historical():
    old = candidate(report())
    current = candidate(report(generated_at="2026-06-21T00:00:00Z"))
    empty = VNextIdentityIndex(())
    current_context = AllocationContext(AllocationMode.CURRENT_MANDATORY, RequestedArtifacts(), DisplayPlacement(True, 0), old.period_key)
    first = allocate_identity(empty, old, current_context)
    assert first.binding.identity_class == V3_CANONICAL and not first.reused_existing
    rerun = allocate_identity(VNextIdentityIndex((first.binding,)), old, current_context)
    assert rerun.reused_existing and rerun.binding == first.binding
    changed = allocate_identity(
        VNextIdentityIndex((first.binding,)), current,
        AllocationContext(AllocationMode.CURRENT_MANDATORY, RequestedArtifacts(), DisplayPlacement(False, 1), old.period_key),
    )
    assert changed.binding.identity_class == V3_VARIANT
    with pytest.raises(VNextPublicationError, match="canonical_bootstrap_required"):
        allocate_identity(empty, old, AllocationContext(AllocationMode.HISTORICAL_RECOVERY, RequestedArtifacts(), DisplayPlacement(False, 0)))
    with pytest.raises(VNextPublicationError, match="identity_reuse_not_found"):
        allocate_identity(empty, old, AllocationContext(AllocationMode.EXACT_ARTIFACT_REUSE, RequestedArtifacts(), DisplayPlacement(False, 0)))


def test_exact_miss_validates_display_and_policy_before_miss():
    c = candidate(report())
    with pytest.raises(VNextPublicationError, match="display_invalid"):
        DisplayPlacement(False, -1)
    with pytest.raises(VNextPublicationError, match="identity_reuse_not_found"):
        allocate_identity(VNextIdentityIndex(()), c, AllocationContext(AllocationMode.EXACT_ARTIFACT_REUSE, RequestedArtifacts(), DisplayPlacement(False, 0)))


def test_publication_plan_uses_binding_targets_not_source_basename():
    c = candidate(report())
    b = binding(c, V3_CANONICAL, primary=True)
    plan = build_publication_plan((PublicationEntry(c, b, PublicationRole.MANDATORY_CURRENT, True, 0),))
    assert plan.entries[0].binding.json_name != c.source_identity
    assert plan.entries[0].role is PublicationRole.MANDATORY_CURRENT


def test_current_variant_is_a_valid_mandatory_publication_entry():
    old = candidate(report())
    current = candidate(report(generated_at="2026-06-21T00:00:00Z"))
    old_binding = binding(old)
    current_binding = binding(current, V3_VARIANT, order=1)
    plan = build_publication_plan((
        PublicationEntry(old, old_binding, PublicationRole.RECOVERED_HISTORY, False, 1),
        PublicationEntry(current, current_binding, PublicationRole.MANDATORY_CURRENT, True, 0),
    ))
    assert plan.entries[0].role is PublicationRole.MANDATORY_CURRENT
    assert ".variant-" in plan.entries[0].binding.json_name


def test_publication_plan_rejects_collision_and_legacy_shape():
    c = candidate(report())
    b = binding(c)
    with pytest.raises(VNextPublicationError, match="publication_target_collision"):
        build_publication_plan((
            PublicationEntry(c, b, PublicationRole.MANDATORY_CURRENT, True, 0),
            PublicationEntry(c, b, PublicationRole.RECOVERED_HISTORY, False, 1),
        ))
    with pytest.raises(VNextPublicationError, match="publication_entry_invalid"):
        PublicationEntry(c, object(), PublicationRole.MANDATORY_CURRENT, True, 0)

from __future__ import annotations

from collections import OrderedDict
from types import MappingProxyType

import pytest

from quant_advisor_research.vnext_identity_schema_v1 import (
    ARTIFACT_ALGORITHM_VERSION,
    MAX_SAFE_JSON_INTEGER,
    SEMANTIC_ALGORITHM_VERSION,
    V3_CANONICAL,
    V3_VARIANT,
    VNEXT_BINDING_NAMESPACE,
    VNEXT_NAMESPACE,
    VNEXT_STATUS,
    VNextIdentityBinding,
    VNextIdentityError,
    VNextIdentityIndex,
    parse_vnext_identity_index,
    serialize_vnext_identity_index,
)
from quant_advisor_research.period_contract import canonical_period_identity

A = "a" * 64
B = "b" * 64


def binding(*, as_of="2026-06-20", cadence="weekly", cls=V3_CANONICAL, artifact=A,
            semantic=A, md=False, manifest=False, primary=False, order=0):
    suffix = "" if cls == V3_CANONICAL else f".variant-{artifact}"
    stem = f"advisory_report_{as_of}-{cadence}{suffix}"
    return VNextIdentityBinding(
        period_key=canonical_period_identity(cadence, as_of).key,
        as_of=as_of, cadence=cadence, report_schema_version="5", contract_version="model_recommendations.v5",
        semantic_fingerprint_version=SEMANTIC_ALGORITHM_VERSION, semantic_digest=semantic,
        artifact_integrity_version=ARTIFACT_ALGORITHM_VERSION, artifact_integrity_digest=artifact,
        json_name=f"{stem}.json", html_name=f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        markdown_name=f"{stem}.md" if md else None,
        manifest_name=f"{stem}.json.manifest.json" if manifest else None,
        identity_class=cls, canonical_identity=cls == V3_CANONICAL,
        display_primary=primary, display_order=order, status=VNEXT_STATUS,
    )


def payload(*bindings):
    return {"schema_version": 1, "namespace": VNEXT_NAMESPACE,
            "reports": [wire_entry(item) for item in bindings]}


def wire_entry(item):
    value = {
        "binding_namespace": VNEXT_BINDING_NAMESPACE, "period_key": item.period_key, "as_of": item.as_of,
        "cadence": item.cadence, "report_schema_version": item.report_schema_version,
        "contract_version": item.contract_version, "semantic_fingerprint_version": item.semantic_fingerprint_version,
        "semantic_digest": item.semantic_digest, "artifact_integrity_version": item.artifact_integrity_version,
        "artifact_integrity_digest": item.artifact_integrity_digest, "json": item.json_name,
        "html": item.html_name, "identity_class": item.identity_class, "canonical_identity": item.canonical_identity,
        "display_primary": item.display_primary, "display_order": item.display_order, "status": item.status,
    }
    if item.markdown_name is not None:
        value["md"] = item.markdown_name
    if item.manifest_name is not None:
        value["manifest"] = item.manifest_name
    return value


def test_schema_v1_roundtrip_and_input_permutation_are_deterministic():
    canonical = binding()
    variant = binding(cls=V3_VARIANT, artifact=B, semantic=B, order=1, md=True, manifest=True)
    left = parse_vnext_identity_index(payload(canonical, variant))
    right = parse_vnext_identity_index(payload(variant, canonical))
    assert left == right
    assert hash(left) == hash(right)
    assert serialize_vnext_identity_index(left) == serialize_vnext_identity_index(right)
    assert parse_vnext_identity_index(serialize_vnext_identity_index(left)) == left


def test_cadence_aware_targets_allow_same_date_daily_weekly_monthly():
    entries = [binding(cadence=cadence, artifact=digest, semantic=digest, order=position)
               for position, (cadence, digest) in enumerate((("daily", A), ("weekly", B), ("monthly", "c" * 64)))]
    index = VNextIdentityIndex(tuple(entries))
    assert len({item.json_name for item in index.bindings}) == 3


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("namespace", "legacy"), ("binding_namespace", "legacy"),
    ("report_schema_version", 6), ("contract_version", "model_recommendations.v6"),
    ("semantic_fingerprint_version", "future"), ("artifact_integrity_version", "future"),
    ("identity_class", "LEGACY_V2"), ("status", "VERIFIED"),
])
def test_unknown_future_legacy_and_mismatched_versions_fail_closed(field, value):
    item = binding()
    wire = payload(item)
    if field in {"schema_version", "namespace"}:
        wire[field] = value
    else:
        wire["reports"][0][field] = value
    with pytest.raises(VNextIdentityError):
        parse_vnext_identity_index(wire)


@pytest.mark.parametrize("optional", ["md", "manifest"])
def test_optional_attachment_omission_is_distinct_from_null(optional):
    item = binding()
    wire = payload(item)
    wire["reports"][0][optional] = None
    with pytest.raises(VNextIdentityError, match="target_invalid"):
        parse_vnext_identity_index(wire)
    assert parse_vnext_identity_index(payload(item)).bindings[0].markdown_name is None


def test_variant_all_declared_targets_use_full_artifact_digest():
    item = binding(cls=V3_VARIANT, artifact=B, semantic=A, md=True, manifest=True, order=1)
    wire = payload(binding(), item)
    assert len(parse_vnext_identity_index(wire).bindings) == 2
    wire["reports"][1]["md"] = wire["reports"][1]["md"].replace(B, A)
    with pytest.raises(VNextIdentityError, match="target_digest_mismatch"):
        parse_vnext_identity_index(wire)


def test_index_requires_one_canonical_and_enforces_display_policy():
    variant = binding(cls=V3_VARIANT, artifact=B, order=1)
    with pytest.raises(VNextIdentityError, match="canonical_missing"):
        VNextIdentityIndex((variant,))
    second = binding(cls=V3_VARIANT, artifact=B, order=0)
    with pytest.raises(VNextIdentityError, match="display_order_conflict"):
        VNextIdentityIndex((binding(), second))
    with pytest.raises(VNextIdentityError, match="display_primary_conflict"):
        VNextIdentityIndex((binding(primary=True), binding(cls=V3_VARIANT, artifact=B, primary=True, order=1)))


def test_full_artifact_identity_and_target_collisions_fail_closed():
    with pytest.raises(VNextIdentityError, match="identity_duplicate"):
        VNextIdentityIndex((binding(), binding(md=True)))
    with pytest.raises(VNextIdentityError, match="artifact_digest_conflict"):
        VNextIdentityIndex((binding(), binding(cls=V3_VARIANT, semantic=B, order=1)))


def test_display_order_is_safe_json_integer_and_not_bool():
    assert binding(order=MAX_SAFE_JSON_INTEGER).display_order == MAX_SAFE_JSON_INTEGER
    for value in (-1, MAX_SAFE_JSON_INTEGER + 1, True, "0"):
        with pytest.raises(VNextIdentityError, match="display_order_invalid"):
            binding(order=value)


def test_mapping_snapshot_and_wire_shape_are_sanitized():
    item = binding()
    value = payload(item)
    ordered = OrderedDict((key, value[key]) for key in reversed(value))
    assert parse_vnext_identity_index(MappingProxyType(ordered)) == parse_vnext_identity_index(value)
    with pytest.raises(VNextIdentityError, match="wire_invalid"):
        parse_vnext_identity_index({"schema_version": 1, "namespace": VNEXT_NAMESPACE, "reports": [{"raw": object()}]})

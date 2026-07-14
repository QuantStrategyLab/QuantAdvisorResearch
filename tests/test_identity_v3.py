from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from quant_advisor_research.artifact_integrity import ARTIFACT_INTEGRITY_VERSION
from quant_advisor_research.identity_lifecycle import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    V1ProvisionalIndex,
    V2IdentityIndex,
)
from quant_advisor_research.identity_v3 import (
    PENDING_ARTIFACT_VALIDATION,
    V3IdentityIndex,
    parse_identity_index,
    parse_v3_index,
)
from quant_advisor_research.period_contract import canonical_period_identity


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def v3_entry(
    *,
    as_of: str = "2026-06-20",
    cadence: str = "weekly",
    identity_class: str = "V3_CANONICAL",
    semantic_digest: str = DIGEST_A,
    artifact_digest: str = DIGEST_A,
    schema: str = "5",
    md: bool = True,
    manifest: bool = True,
) -> dict:
    period_key = canonical_period_identity(cadence, as_of).key
    suffix = ""
    if identity_class == "V3_VARIANT":
        suffix = f".variant-{artifact_digest}"
    elif identity_class == "LEGACY_V2" and artifact_digest == DIGEST_D:
        suffix = f".variant-{semantic_digest}"
    canonical = identity_class != "V3_VARIANT" and not (
        identity_class == "LEGACY_V2" and artifact_digest == DIGEST_D
    )
    entry = {
        "period_key": period_key,
        "as_of": as_of,
        "cadence": cadence,
        "report_schema_version": schema,
        "contract_version": f"model_recommendations.v{schema}",
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic_digest,
        "artifact_integrity_version": ARTIFACT_INTEGRITY_VERSION,
        "artifact_integrity_digest": artifact_digest,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": identity_class,
        "canonical_identity": canonical,
        "display_primary": canonical,
        "display_order": 0,
    }
    if md:
        entry["md"] = f"advisory_report_{as_of}{suffix}.md"
    if manifest:
        entry["manifest"] = f"advisory_report_{as_of}{suffix}.json.manifest.json"
    return entry


def v3_payload(*entries: dict) -> dict:
    return {"schema_version": 3, "reports": list(entries)}


def test_v3_canonical_and_artifact_variants_parse_with_pending_status() -> None:
    canonical = v3_entry()
    variant = v3_entry(
        identity_class="V3_VARIANT",
        semantic_digest=DIGEST_A,
        artifact_digest=DIGEST_B,
        md=False,
        manifest=False,
    )

    index = parse_v3_index(v3_payload(canonical, variant))

    assert isinstance(index, V3IdentityIndex)
    assert index.bindings[0].status == PENDING_ARTIFACT_VALIDATION
    assert index.bindings[1].status == PENDING_ARTIFACT_VALIDATION


@pytest.mark.parametrize("optional", ["md", "manifest", "both"])
def test_variant_optional_attachments_are_independent_but_suffixed(optional: str) -> None:
    canonical = v3_entry()
    variant = v3_entry(
        identity_class="V3_VARIANT",
        semantic_digest=DIGEST_A,
        artifact_digest=DIGEST_B,
        md=optional in {"md", "both"},
        manifest=optional in {"manifest", "both"},
    )

    assert len(parse_v3_index(v3_payload(canonical, variant)).bindings) == 2


def test_v3_variant_must_use_artifact_digest_not_semantic_digest() -> None:
    canonical = v3_entry()
    variant = v3_entry(identity_class="V3_VARIANT", semantic_digest=DIGEST_A, artifact_digest=DIGEST_B)
    variant["json"] = variant["json"].replace(DIGEST_B, DIGEST_A)

    with pytest.raises(IdentityMetadataError, match="identity_digest_mismatch"):
        parse_v3_index(v3_payload(canonical, variant))


def test_legacy_v2_names_keep_semantic_suffix_and_artifact_is_pending_only() -> None:
    canonical = v3_entry(identity_class="LEGACY_V2", artifact_digest=DIGEST_C)
    legacy_variant = v3_entry(
        identity_class="LEGACY_V2",
        semantic_digest=DIGEST_B,
        artifact_digest=DIGEST_D,
    )
    legacy_variant["canonical_identity"] = False
    legacy_variant["display_primary"] = False
    legacy_variant["json"] = legacy_variant["json"].replace(".variant-" + DIGEST_D, ".variant-" + DIGEST_B)
    legacy_variant["html"] = legacy_variant["html"].replace(".variant-" + DIGEST_D, ".variant-" + DIGEST_B)
    legacy_variant["md"] = legacy_variant["md"].replace(".variant-" + DIGEST_D, ".variant-" + DIGEST_B)
    legacy_variant["manifest"] = legacy_variant["manifest"].replace(".variant-" + DIGEST_D, ".variant-" + DIGEST_B)

    index = parse_v3_index(v3_payload(canonical, legacy_variant))

    assert index.bindings[1].artifact_integrity_digest == DIGEST_D
    assert f".variant-{DIGEST_B}" in index.bindings[1].json_name


def test_v3_same_semantic_digest_different_artifact_is_allowed() -> None:
    canonical = v3_entry(semantic_digest=DIGEST_A, artifact_digest=DIGEST_A)
    variant = v3_entry(identity_class="V3_VARIANT", semantic_digest=DIGEST_A, artifact_digest=DIGEST_B)

    assert len(parse_v3_index(v3_payload(canonical, variant)).bindings) == 2


def test_same_period_different_semantic_and_artifact_variants_are_allowed() -> None:
    canonical = v3_entry(semantic_digest=DIGEST_A, artifact_digest=DIGEST_A)
    variant = v3_entry(identity_class="V3_VARIANT", semantic_digest=DIGEST_B, artifact_digest=DIGEST_B)

    assert len(parse_v3_index(v3_payload(canonical, variant)).bindings) == 2


def test_semantic_digest_can_repeat_across_periods() -> None:
    first = v3_entry(semantic_digest=DIGEST_A, artifact_digest=DIGEST_A)
    second = v3_entry(as_of="2026-06-27", semantic_digest=DIGEST_A, artifact_digest=DIGEST_B)

    assert len(parse_v3_index(v3_payload(first, second)).bindings) == 2


def test_artifact_digest_cannot_bind_conflicting_period_metadata() -> None:
    first = v3_entry(artifact_digest=DIGEST_A)
    second = v3_entry(as_of="2026-06-27", artifact_digest=DIGEST_A)

    with pytest.raises(IdentityMetadataError, match="identity_integrity_conflict"):
        parse_v3_index(v3_payload(first, second))


@pytest.mark.parametrize("mutation", [
    lambda entry: entry.update(identity_class="V3_VARIANT", canonical_identity=True),
    lambda entry: entry.update(identity_class="V3_CANONICAL", canonical_identity=False),
    lambda entry: entry.update(contract_version="model_recommendations.v6"),
    lambda entry: entry.update(report_schema_version="6"),
    lambda entry: entry.update(semantic_fingerprint_version="other"),
    lambda entry: entry.update(artifact_integrity_version="other"),
    lambda entry: entry.update(semantic_digest=True),
    lambda entry: entry.update(display_order=True),
    lambda entry: entry.update(status="VERIFIED"),
    lambda entry: entry.update(debug="raw"),
])
def test_v3_wire_contract_mismatches_are_sanitized(mutation) -> None:
    entry = v3_entry()
    mutation(entry)

    with pytest.raises(IdentityMetadataError):
        parse_v3_index(v3_payload(entry))


def test_v3_requires_exactly_one_canonical_per_period() -> None:
    variant = v3_entry(identity_class="V3_VARIANT", artifact_digest=DIGEST_B)
    with pytest.raises(IdentityMetadataError, match="identity_canonical_missing"):
        parse_v3_index(v3_payload(variant))

    second = v3_entry(as_of="2026-06-21", artifact_digest=DIGEST_B)
    with pytest.raises(IdentityMetadataError, match="identity_canonical_conflict"):
        parse_v3_index(v3_payload(v3_entry(), second))


@pytest.mark.parametrize("name_field", ["json", "html", "md", "manifest"])
def test_each_public_basename_collision_fails_closed(name_field: str) -> None:
    first = v3_entry()
    first_variant = v3_entry(identity_class="V3_VARIANT", artifact_digest=DIGEST_B)
    second_variant = v3_entry(identity_class="V3_VARIANT", semantic_digest=DIGEST_C, artifact_digest=DIGEST_B)
    if name_field in {"json", "html"}:
        second_variant["md"] = None
        second_variant["manifest"] = None
        del second_variant["md"]
        del second_variant["manifest"]
    else:
        second_variant[name_field] = first_variant[name_field]
    entries = [first, first_variant, second_variant]

    with pytest.raises(IdentityMetadataError, match="identity_artifact_conflict|identity_content_conflict|identity_integrity_conflict"):
        parse_v3_index(v3_payload(*entries))


def test_dispatcher_preserves_v1_v2_types_and_dispatches_v3() -> None:
    v1 = {
        "schema_version": 1,
        "reports": [{
            "as_of": "2026-06-20", "cadence": "weekly",
            "json": "advisory_report_2026-06-20.json",
            "html": "2026-06-20-weekly-model-recommendations.html",
        }],
    }
    v2 = {
        "schema_version": 2,
        "reports": [{
            "period_key": "weekly:2026-06-15:2026-06-21", "as_of": "2026-06-20", "cadence": "weekly",
            "schema_version": "5", "fingerprint_version": FINGERPRINT_VERSION,
            "fingerprint_digest": DIGEST_A, "json": "advisory_report_2026-06-20.json",
            "html": "2026-06-20-weekly-model-recommendations.html", "canonical_identity": True,
            "display_primary": True, "display_order": 0,
        }],
    }

    assert isinstance(parse_identity_index(v1), V1ProvisionalIndex)
    assert isinstance(parse_identity_index(v2), V2IdentityIndex)
    assert isinstance(parse_identity_index(v3_payload(v3_entry())), V3IdentityIndex)


def test_dispatcher_accepts_mapping_snapshot_without_changing_v1_v2_parsers() -> None:
    payload = v3_payload(v3_entry())
    ordered = OrderedDict((key, payload[key]) for key in reversed(list(payload)))

    assert parse_identity_index(MappingProxyType(ordered)).bindings == parse_identity_index(payload).bindings


def test_dispatcher_unknown_version_and_mapping_shape_fail_closed() -> None:
    with pytest.raises(IdentityMetadataError, match="unsupported_index_version"):
        parse_identity_index({"schema_version": 4, "reports": []})

    with pytest.raises(IdentityMetadataError, match="invalid_reports_index"):
        parse_identity_index({"schema_version": "3", "reports": []})


def test_dispatcher_preserves_v1_v2_identity_error_codes() -> None:
    v1 = {
        "schema_version": 1,
        "reports": [{
            "as_of": "2026-06-20", "cadence": "weekly",
            "json": f"advisory_report_2026-06-20.variant-{DIGEST_A}.json",
            "html": "2026-06-20-weekly-model-recommendations.html",
        }],
    }
    with pytest.raises(IdentityMetadataError, match="v1_variant_unverified"):
        parse_identity_index(v1)

    v2 = {
        "schema_version": 2,
        "reports": [{
            "period_key": "weekly:2026-06-15:2026-06-21", "as_of": "2026-06-20", "cadence": "weekly",
            "schema_version": "5", "fingerprint_version": FINGERPRINT_VERSION,
            "fingerprint_digest": "short", "json": "advisory_report_2026-06-20.json",
            "html": "2026-06-20-weekly-model-recommendations.html", "canonical_identity": True,
            "display_primary": True, "display_order": 0,
        }],
    }
    with pytest.raises(IdentityMetadataError, match="invalid_fingerprint_digest"):
        parse_identity_index(v2)


class ExplodingMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("raw untrusted mapping marker")

    def __iter__(self):
        raise RuntimeError("raw untrusted mapping marker")

    def __len__(self) -> int:
        return 1


def test_dispatcher_mapping_errors_are_sanitized() -> None:
    with pytest.raises(IdentityMetadataError, match="invalid_reports_index") as error:
        parse_identity_index(ExplodingMapping())

    assert "raw untrusted mapping marker" not in repr(error.value)


@pytest.mark.parametrize("bad_value", [Path("x"), {"nested": [Path("x")]}])
def test_dispatcher_rejects_non_wire_nested_values(bad_value: object) -> None:
    payload = v3_payload(v3_entry())
    payload["reports"][0]["debug"] = bad_value

    with pytest.raises(IdentityMetadataError, match="invalid_reports_index"):
        parse_identity_index(payload)

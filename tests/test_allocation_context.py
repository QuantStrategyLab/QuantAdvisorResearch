from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.allocation_context import (
    AllocationContext,
    DisplayPlacement,
    RequestedArtifactSet,
    V3AllocationPlan,
    allocate_v3_identity,
    make_complete_source_inventory,
)
from quant_advisor_research.artifact_integrity import artifact_integrity_digest
from quant_advisor_research.identity_lifecycle import FINGERPRINT_VERSION, IdentityMetadataError
from quant_advisor_research.identity_v3 import V3IdentityIndex, parse_v3_index
from quant_advisor_research.period_contract import canonical_period_identity
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.time_contract import contract_version_for_schema


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_VERSION = "validated_report.v1.canonical-json.sha256"
DIGEST_A = "a" * 64


def build_report(*, as_of: str = "2026-06-20", generated_at: str | None = None) -> dict:
    report = build_advisory_report(
        as_of=as_of,
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if generated_at is not None:
        report["generated_at"] = generated_at
    return report


def metadata(report: dict) -> tuple[str, str, str, str]:
    schema = report["schema_version"]
    return (
        canonical_period_identity(report["cadence"], report["as_of"]).key,
        hashlib.sha256(report_content_fingerprint(report).encode("utf-8")).hexdigest(),
        artifact_integrity_digest(report),
        contract_version_for_schema(schema),
    )


def binding_for(
    report: dict,
    *,
    canonical: bool = True,
    artifact_digest: str | None = None,
    semantic_digest: str | None = None,
    display_primary: bool = False,
    display_order: int = 0,
    include_md: bool = False,
    include_manifest: bool = False,
    identity_class: str | None = None,
):
    period_key, semantic, artifact, contract = metadata(report)
    artifact_digest = artifact_digest or artifact
    semantic_digest = semantic_digest or semantic
    as_of = report["as_of"]
    cadence = report["cadence"]
    identity_class = identity_class or ("V3_CANONICAL" if canonical else "V3_VARIANT")
    suffix = "" if canonical else f".variant-{semantic_digest if identity_class == 'LEGACY_V2' else artifact_digest}"
    entry = {
        "period_key": period_key,
        "as_of": as_of,
        "cadence": cadence,
        "report_schema_version": report["schema_version"],
        "contract_version": contract,
        "semantic_fingerprint_version": FINGERPRINT_VERSION,
        "semantic_digest": semantic_digest,
        "artifact_integrity_version": ARTIFACT_VERSION,
        "artifact_integrity_digest": artifact_digest,
        "json": f"advisory_report_{as_of}{suffix}.json",
        "html": f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        "identity_class": identity_class,
        "canonical_identity": canonical,
        "display_primary": display_primary,
        "display_order": display_order,
    }
    if include_md:
        entry["md"] = f"advisory_report_{as_of}{suffix}.md"
    if include_manifest:
        entry["manifest"] = f"advisory_report_{as_of}{suffix}.json.manifest.json"
    return parse_v3_index({"schema_version": 3, "reports": [entry]}).bindings[0]


def inventory_for(*pairs: tuple[object, dict]):
    bindings = tuple(binding for binding, _report in pairs)
    reports = {binding.json_name: report for binding, report in pairs}
    return make_complete_source_inventory(V3IdentityIndex(3, bindings), reports)


def empty_inventory():
    return make_complete_source_inventory(V3IdentityIndex(3, ()), {})


REQUESTED = RequestedArtifactSet(include_markdown=False, include_manifest=False)
DISPLAY = DisplayPlacement(display_primary=False, display_order=7)


def test_current_mandatory_without_canonical_bootstraps_canonical() -> None:
    report = build_report()
    period_key, _semantic, _artifact, _contract = metadata(report)

    result = allocate_v3_identity(
        report,
        inventory=empty_inventory(),
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=REQUESTED,
        display_placement=DISPLAY,
    )

    assert isinstance(result, V3AllocationPlan)
    assert result.binding.identity_class == "V3_CANONICAL"
    assert result.binding.canonical_identity is True
    assert ".variant-" not in result.binding.json_name


def test_current_mandatory_with_canonical_allocates_artifact_variant() -> None:
    old_report = build_report()
    new_report = dict(old_report)
    new_report["generated_at"] = "2026-07-15T00:00:00Z"
    old_binding = binding_for(old_report)
    inventory = inventory_for((old_binding, old_report))
    period_key, _semantic, new_artifact, _contract = metadata(new_report)

    result = allocate_v3_identity(
        new_report,
        inventory=inventory,
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=RequestedArtifactSet(True, True),
        display_placement=DisplayPlacement(True, 1),
    )

    assert result.binding.identity_class == "V3_VARIANT"
    assert result.binding.canonical_identity is False
    assert f".variant-{new_artifact}" in result.binding.json_name
    assert result.binding.markdown_name is not None
    assert result.binding.manifest_name is not None


def test_historical_recovery_requires_existing_canonical() -> None:
    report = build_report()

    with pytest.raises(IdentityMetadataError, match="canonical_bootstrap_required"):
        allocate_v3_identity(
            report,
            inventory=empty_inventory(),
            context=AllocationContext.historical_recovery(),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


def test_historical_recovery_with_canonical_allocates_variant() -> None:
    report = build_report()
    changed = dict(report)
    changed["generated_at"] = "2026-07-15T00:00:00Z"
    inventory = inventory_for((binding_for(report), report))

    result = allocate_v3_identity(
        changed,
        inventory=inventory,
        context=AllocationContext.historical_recovery(),
        requested_artifacts=REQUESTED,
        display_placement=DISPLAY,
    )

    assert result.reused_existing is False
    assert result.binding.identity_class == "V3_VARIANT"
    assert result.binding.canonical_identity is False


def test_exact_artifact_reuse_is_immutable_and_requires_full_match() -> None:
    report = build_report()
    binding = binding_for(report, display_primary=True, display_order=2)
    inventory = inventory_for((binding, report))

    result = allocate_v3_identity(
        MappingProxyType(report),
        inventory=inventory,
        context=AllocationContext.exact_artifact_reuse(),
        requested_artifacts=RequestedArtifactSet(False, False),
        display_placement=DisplayPlacement(True, 2),
    )

    assert result.reused_existing is True
    assert result.binding == binding
    assert result.binding.display_primary is True
    assert result.binding.display_order == 2

    changed = dict(report)
    changed["generated_at"] = "2026-07-15T00:00:00Z"
    with pytest.raises(IdentityMetadataError, match="exact_artifact_not_found"):
        allocate_v3_identity(
            changed,
            inventory=inventory,
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


@pytest.mark.parametrize(
    ("requested", "display"),
    [
        (RequestedArtifactSet(True, False), DisplayPlacement(True, 2)),
        (RequestedArtifactSet(False, True), DisplayPlacement(True, 2)),
        (RequestedArtifactSet(False, False), DisplayPlacement(False, 2)),
        (RequestedArtifactSet(False, False), DisplayPlacement(True, 3)),
    ],
)
def test_exact_reuse_rejects_publication_policy_mismatch(
    requested: RequestedArtifactSet, display: DisplayPlacement
) -> None:
    report = build_report()
    binding = binding_for(report, display_primary=True, display_order=2)

    with pytest.raises(IdentityMetadataError, match="identity_reuse_mismatch"):
        allocate_v3_identity(
            report,
            inventory=inventory_for((binding, report)),
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=requested,
            display_placement=display,
        )


@pytest.mark.parametrize(
    "display",
    [None, DisplayPlacement(True, True), DisplayPlacement(True, -1)],
)
def test_exact_reuse_requires_valid_matching_display_placement(display: object) -> None:
    report = build_report()
    binding = binding_for(report, display_primary=True, display_order=2)

    with pytest.raises(IdentityMetadataError, match="display_placement"):
        allocate_v3_identity(
            report,
            inventory=inventory_for((binding, report)),
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
            display_placement=display,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("schema_version", [2, 4, True, "3"])
def test_inventory_rejects_declared_schema_version_other_than_v3(schema_version: object) -> None:
    report = build_report()
    binding = binding_for(report)

    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_source_inventory(
            V3IdentityIndex(schema_version, (binding,)),  # type: ignore[arg-type]
            {binding.json_name: report},
        )


def test_inventory_accepts_declared_v3_schema_version() -> None:
    report = build_report()
    binding = binding_for(report)

    inventory = make_complete_source_inventory(
        V3IdentityIndex(3, (binding,)),
        {binding.json_name: report},
    )

    assert inventory.index.schema_version == 3


def test_legacy_exact_match_is_not_reused_or_migrated() -> None:
    report = build_report()
    legacy = binding_for(report, identity_class="LEGACY_V2")

    with pytest.raises(IdentityMetadataError, match="exact_artifact_not_found"):
        allocate_v3_identity(
            report,
            inventory=inventory_for((legacy, report)),
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


def test_legacy_only_current_bootstraps_v3_canonical() -> None:
    report = build_report()
    legacy = binding_for(report, identity_class="LEGACY_V2")
    period_key = metadata(report)[0]

    result = allocate_v3_identity(
        report,
        inventory=inventory_for((legacy, report)),
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=REQUESTED,
        display_placement=DISPLAY,
    )

    assert result.reused_existing is False
    assert result.binding.identity_class == "V3_CANONICAL"
    assert result.binding.canonical_identity is True


def test_legacy_only_historical_recovery_requires_v3_canonical() -> None:
    report = build_report()
    legacy = binding_for(report, identity_class="LEGACY_V2")

    with pytest.raises(IdentityMetadataError, match="canonical_bootstrap_required"):
        allocate_v3_identity(
            report,
            inventory=inventory_for((legacy, report)),
            context=AllocationContext.historical_recovery(),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


def test_mixed_legacy_and_v3_uses_v3_canonical_for_variant_allocation() -> None:
    legacy_report = build_report()
    current_report = dict(legacy_report)
    current_report["generated_at"] = "2026-07-15T00:00:00Z"
    candidate_report = dict(current_report)
    candidate_report["generated_at"] = "2026-07-16T00:00:00Z"
    legacy_canonical = binding_for(legacy_report, identity_class="LEGACY_V2")
    legacy = replace(
        legacy_canonical,
        canonical_identity=False,
        json_name=f"advisory_report_{legacy_report['as_of']}.variant-{metadata(legacy_report)[1]}.json",
        html_name=(
            f"{legacy_report['as_of']}-{legacy_report['cadence']}-model-recommendations"
            f".variant-{metadata(legacy_report)[1]}.html"
        ),
    )
    canonical = binding_for(current_report)
    period_key = metadata(candidate_report)[0]

    result = allocate_v3_identity(
        candidate_report,
        inventory=inventory_for((legacy, legacy_report), (canonical, current_report)),
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=REQUESTED,
        display_placement=DISPLAY,
    )

    assert result.binding.identity_class == "V3_VARIANT"
    assert result.reused_existing is False


def test_semantic_same_artifact_different_is_not_reused() -> None:
    report = build_report()
    changed = dict(report)
    changed["generated_at"] = "2026-07-15T00:00:00Z"
    inventory = inventory_for((binding_for(report), report))
    period_key, semantic, artifact, _contract = metadata(changed)

    assert semantic == metadata(report)[1]
    with pytest.raises(IdentityMetadataError, match="exact_artifact_not_found"):
        allocate_v3_identity(
            changed,
            inventory=inventory,
            context=AllocationContext.exact_artifact_reuse(),
            requested_artifacts=REQUESTED,
        )
    result = allocate_v3_identity(
        changed,
        inventory=inventory,
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=REQUESTED,
        display_placement=DISPLAY,
    )
    assert result.binding.artifact_integrity_digest == artifact
    assert result.binding.semantic_digest == semantic


def test_context_is_explicit_and_target_must_match_report_period() -> None:
    report = build_report()

    with pytest.raises(IdentityMetadataError, match="allocation_context_required"):
        allocate_v3_identity(
            report,
            inventory=empty_inventory(),
            context=AllocationContext("CURRENT_MANDATORY", None),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )
    with pytest.raises(IdentityMetadataError, match="allocation_context_mismatch"):
        allocate_v3_identity(
            report,
            inventory=empty_inventory(),
            context=AllocationContext.current_mandatory("weekly:wrong:period"),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


def test_inventory_requires_exact_source_mapping_and_revalidation() -> None:
    report = build_report()
    binding = binding_for(report)

    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_source_inventory(V3IdentityIndex(3, (binding,)), {})
    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_source_inventory(V3IdentityIndex(3, (binding,)), {"extra.json": report})

    changed = dict(report)
    changed["source_artifacts"] = {"different": "source"}
    with pytest.raises(IdentityMetadataError, match="identity_inventory_invalid"):
        make_complete_source_inventory(V3IdentityIndex(3, (binding,)), {binding.json_name: changed})


def test_display_and_identity_ownership_are_independent() -> None:
    report = build_report()
    binding = binding_for(report, display_primary=False)
    inventory = inventory_for((binding, report))

    result = allocate_v3_identity(
        report,
        inventory=inventory,
        context=AllocationContext.exact_artifact_reuse(),
        requested_artifacts=REQUESTED,
        display_placement=DisplayPlacement(False, 0),
    )

    assert result.binding.canonical_identity is True
    assert result.binding.display_primary is False


@pytest.mark.parametrize("bad", [None, True, 1, "not-a-report", Path("report.json")])
def test_current_report_must_be_raw_mapping(bad: object) -> None:
    with pytest.raises(IdentityMetadataError, match="report_invalid"):
        allocate_v3_identity(
            bad,  # type: ignore[arg-type]
            inventory=empty_inventory(),
            context=AllocationContext.current_mandatory("weekly:2026-06-15:2026-06-21"),
            requested_artifacts=REQUESTED,
            display_placement=DISPLAY,
        )


def test_input_order_does_not_change_new_identity_plan() -> None:
    report = build_report()
    ordered = OrderedDict(reversed(list(report.items())))
    period_key = metadata(report)[0]
    first = allocate_v3_identity(
        report,
        inventory=empty_inventory(),
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=RequestedArtifactSet(True, False),
        display_placement=DisplayPlacement(False, 4),
    )
    second = allocate_v3_identity(
        ordered,
        inventory=empty_inventory(),
        context=AllocationContext.current_mandatory(period_key),
        requested_artifacts=RequestedArtifactSet(True, False),
        display_placement=DisplayPlacement(False, 4),
    )

    assert first == second

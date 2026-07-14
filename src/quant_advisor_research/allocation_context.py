"""Pure, report-backed v3 identity allocation and whole-index simulation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from collections.abc import Mapping
from typing import Any

from .artifact_integrity import (
    ARTIFACT_INTEGRITY_VERSION,
    ArtifactIntegrityError,
    artifact_integrity_digest,
    snapshot_json_wire,
)
from .contracts import validate_advisory_report
from .identity_lifecycle import FINGERPRINT_VERSION, IdentityMetadataError
from .identity_v3 import (
    PENDING_ARTIFACT_VALIDATION,
    V3_CANONICAL,
    V3_VARIANT,
    V3IdentityBinding,
    V3IdentityIndex,
    parse_v3_index,
)
from .period_contract import canonical_period_identity
from .publisher import report_content_fingerprint
from .time_contract import contract_version_for_schema


class AllocationMode(Enum):
    EXACT_ARTIFACT_REUSE = "EXACT_ARTIFACT_REUSE"
    CURRENT_MANDATORY = "CURRENT_MANDATORY"
    HISTORICAL_RECOVERY = "HISTORICAL_RECOVERY"


@dataclass(frozen=True, slots=True)
class AllocationContext:
    """Description value; operation boundaries revalidate all fields."""

    mode: AllocationMode
    target_period_key: str | None

    @classmethod
    def exact_artifact_reuse(cls) -> AllocationContext:
        return cls(AllocationMode.EXACT_ARTIFACT_REUSE, None)

    @classmethod
    def current_mandatory(cls, target_period_key: str) -> AllocationContext:
        return cls(AllocationMode.CURRENT_MANDATORY, target_period_key)

    @classmethod
    def historical_recovery(cls) -> AllocationContext:
        return cls(AllocationMode.HISTORICAL_RECOVERY, None)


@dataclass(frozen=True, slots=True)
class RequestedArtifactSet:
    """Explicit optional public artifact policy; no attachment defaults are guessed."""

    include_markdown: bool
    include_manifest: bool


@dataclass(frozen=True, slots=True)
class DisplayPlacement:
    """Explicit display evidence used only to make a complete simulation entry."""

    display_primary: bool
    display_order: int


@dataclass(frozen=True, slots=True)
class CompleteSourceInventory:
    """Full v3 identity index plus exact JSON-name keyed report snapshots."""

    index: V3IdentityIndex
    source_reports: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class V3AllocationPlan:
    """Descriptive allocation result; it carries no trust or publication authority."""

    binding: V3IdentityBinding
    mode: AllocationMode
    reused_existing: bool


def _error(code: str) -> IdentityMetadataError:
    return IdentityMetadataError(code)


def _snapshot_mapping(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _error(code)
    try:
        return snapshot_json_wire(value)
    except ArtifactIntegrityError:
        raise _error(code) from None


def _binding_payload(binding: V3IdentityBinding) -> dict[str, object]:
    payload: dict[str, object] = {
        "period_key": binding.period_key,
        "as_of": binding.as_of,
        "cadence": binding.cadence,
        "report_schema_version": binding.report_schema_version,
        "contract_version": binding.contract_version,
        "semantic_fingerprint_version": binding.semantic_fingerprint_version,
        "semantic_digest": binding.semantic_digest,
        "artifact_integrity_version": binding.artifact_integrity_version,
        "artifact_integrity_digest": binding.artifact_integrity_digest,
        "json": binding.json_name,
        "html": binding.html_name,
        "identity_class": binding.identity_class,
        "canonical_identity": binding.canonical_identity,
        "display_primary": binding.display_primary,
        "display_order": binding.display_order,
    }
    if binding.markdown_name is not None:
        payload["md"] = binding.markdown_name
    if binding.manifest_name is not None:
        payload["manifest"] = binding.manifest_name
    return payload


def _validated_index(index: object) -> V3IdentityIndex:
    if not isinstance(index, V3IdentityIndex) or type(index.schema_version) is not int:
        raise _error("identity_inventory_invalid")
    try:
        if type(index.bindings) is not tuple:
            raise _error("identity_inventory_invalid")
        payload = {"schema_version": 3, "reports": [_binding_payload(binding) for binding in index.bindings]}
        validated = parse_v3_index(payload)
        if len(validated.bindings) != len(index.bindings):
            raise _error("identity_inventory_invalid")
        return validated
    except IdentityMetadataError:
        raise _error("identity_inventory_invalid") from None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("identity_inventory_invalid") from None


def _report_metadata(report: object) -> tuple[dict[str, object], str, str, str, str, str, str, str]:
    snapshot = _snapshot_mapping(report, "report_invalid")
    try:
        validate_advisory_report(snapshot)
        schema_version = snapshot["schema_version"]
        as_of = snapshot["as_of"]
        cadence = snapshot["cadence"]
        if not all(type(value) is str for value in (schema_version, as_of, cadence)):
            raise _error("report_invalid")
        period_key = canonical_period_identity(cadence, as_of).key
        expected_contract = contract_version_for_schema(schema_version)
        contract_version = snapshot.get("contract_version") or expected_contract
        if type(contract_version) is not str or contract_version != expected_contract:
            raise _error("identity_metadata_mismatch")
        artifact_digest = artifact_integrity_digest(snapshot)
        semantic_digest = hashlib.sha256(report_content_fingerprint(snapshot).encode("utf-8")).hexdigest()
    except IdentityMetadataError:
        raise
    except ArtifactIntegrityError as exc:
        raise _error(exc.code) from None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("report_invalid") from None
    return (
        snapshot, period_key, as_of, cadence, schema_version, contract_version,
        semantic_digest, artifact_digest,
    )


def _compare_report_binding(report: object, binding: V3IdentityBinding) -> None:
    (
        _snapshot, period_key, as_of, cadence, schema_version, contract_version,
        semantic_digest, artifact_digest,
    ) = _report_metadata(report)
    if (
        period_key != binding.period_key
        or as_of != binding.as_of
        or cadence != binding.cadence
        or schema_version != binding.report_schema_version
        or contract_version != binding.contract_version
        or binding.semantic_fingerprint_version != FINGERPRINT_VERSION
        or semantic_digest != binding.semantic_digest
        or binding.artifact_integrity_version != ARTIFACT_INTEGRITY_VERSION
        or artifact_digest != binding.artifact_integrity_digest
    ):
        raise _error("identity_metadata_mismatch")


def make_complete_source_inventory(index: V3IdentityIndex, source_reports: Mapping[str, object]) -> CompleteSourceInventory:
    validated_index = _validated_index(index)
    reports = _snapshot_mapping(source_reports, "identity_inventory_invalid")
    expected_names = {binding.json_name for binding in validated_index.bindings}
    if set(reports) != expected_names:
        raise _error("identity_inventory_invalid")
    try:
        for binding in validated_index.bindings:
            _compare_report_binding(reports[binding.json_name], binding)
    except IdentityMetadataError:
        raise _error("identity_inventory_invalid") from None
    return CompleteSourceInventory(
        validated_index,
        tuple((name, reports[name]) for name in sorted(reports)),
    )


def _revalidate_inventory(inventory: object) -> CompleteSourceInventory:
    if not isinstance(inventory, CompleteSourceInventory):
        raise _error("identity_inventory_invalid")
    if type(inventory.index) is not V3IdentityIndex or type(inventory.source_reports) is not tuple:
        raise _error("identity_inventory_invalid")
    if any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        for item in inventory.source_reports
    ):
        raise _error("identity_inventory_invalid")
    names = [item[0] for item in inventory.source_reports]
    if len(names) != len(set(names)):
        raise _error("identity_inventory_invalid")
    try:
        reports = dict(inventory.source_reports)
    except (TypeError, ValueError):
        raise _error("identity_inventory_invalid") from None
    return make_complete_source_inventory(inventory.index, reports)


def _validate_context(context: object) -> AllocationContext:
    if not isinstance(context, AllocationContext) or type(context.mode) is not AllocationMode:
        raise _error("allocation_context_required")
    if context.mode is AllocationMode.CURRENT_MANDATORY:
        if type(context.target_period_key) is not str:
            raise _error("allocation_context_required")
    elif context.target_period_key is not None:
        raise _error("allocation_context_required")
    return context


def _validate_requested_artifacts(requested: object) -> RequestedArtifactSet:
    if not isinstance(requested, RequestedArtifactSet):
        raise _error("identity_metadata_mismatch")
    if type(requested.include_markdown) is not bool or type(requested.include_manifest) is not bool:
        raise _error("identity_metadata_mismatch")
    return requested


def _validate_display(display: object) -> DisplayPlacement:
    if not isinstance(display, DisplayPlacement):
        raise _error("display_placement_required")
    if type(display.display_primary) is not bool or type(display.display_order) is not int:
        raise _error("display_placement_invalid")
    if display.display_order < 0:
        raise _error("display_placement_invalid")
    return display


def _exact_key(binding: V3IdentityBinding) -> tuple[str, ...]:
    return (
        binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
        binding.contract_version, binding.semantic_fingerprint_version, binding.semantic_digest,
        binding.artifact_integrity_version, binding.artifact_integrity_digest,
    )


def _new_binding(
    metadata: tuple[dict[str, object], str, str, str, str, str, str, str],
    *,
    canonical: bool,
    requested: RequestedArtifactSet,
    display: DisplayPlacement,
) -> V3IdentityBinding:
    _snapshot, period_key, as_of, cadence, schema_version, contract_version, semantic_digest, artifact_digest = metadata
    suffix = "" if canonical else f".variant-{artifact_digest}"
    return V3IdentityBinding(
        period_key, as_of, cadence, schema_version, contract_version,
        FINGERPRINT_VERSION, semantic_digest, ARTIFACT_INTEGRITY_VERSION, artifact_digest,
        f"advisory_report_{as_of}{suffix}.json",
        f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        f"advisory_report_{as_of}{suffix}.md" if requested.include_markdown else None,
        f"advisory_report_{as_of}{suffix}.json.manifest.json" if requested.include_manifest else None,
        V3_CANONICAL if canonical else V3_VARIANT,
        canonical, display.display_primary, display.display_order,
        PENDING_ARTIFACT_VALIDATION,
    )


def allocate_v3_identity(
    current_report: Mapping[str, Any],
    *,
    inventory: CompleteSourceInventory,
    context: AllocationContext,
    requested_artifacts: RequestedArtifactSet,
    display_placement: DisplayPlacement | None = None,
) -> V3AllocationPlan:
    """Revalidate report/inventory, allocate by explicit mode, then simulate full v3 index."""

    context = _validate_context(context)
    requested = _validate_requested_artifacts(requested_artifacts)
    metadata = _report_metadata(current_report)
    _snapshot, period_key, _as_of, _cadence, _schema, _contract, _semantic, artifact_digest = metadata
    if context.mode is AllocationMode.CURRENT_MANDATORY and context.target_period_key != period_key:
        raise _error("allocation_context_mismatch")
    verified_inventory = _revalidate_inventory(inventory)
    bindings = verified_inventory.index.bindings
    exact_matches = [binding for binding in bindings if _exact_key(binding) == _exact_key_from_metadata(metadata)]
    same_artifact = [
        binding for binding in bindings
        if binding.period_key == period_key
        and binding.artifact_integrity_version == ARTIFACT_INTEGRITY_VERSION
        and binding.artifact_integrity_digest == artifact_digest
    ]
    if len(exact_matches) > 1 or len(same_artifact) > 1:
        raise _error("identity_integrity_conflict")
    if exact_matches:
        binding = exact_matches[0]
        return V3AllocationPlan(binding, context.mode, True)
    if context.mode is AllocationMode.EXACT_ARTIFACT_REUSE:
        raise _error("identity_reuse_mismatch" if same_artifact else "identity_reuse_not_found")
    if same_artifact:
        raise _error("identity_reuse_mismatch")
    period_bindings = [binding for binding in bindings if binding.period_key == period_key]
    canonical_exists = any(binding.canonical_identity for binding in period_bindings)
    if context.mode is AllocationMode.HISTORICAL_RECOVERY and not canonical_exists:
        raise _error("canonical_bootstrap_required")
    display = _validate_display(display_placement)
    candidate = _new_binding(
        metadata,
        canonical=context.mode is AllocationMode.CURRENT_MANDATORY and not canonical_exists,
        requested=requested,
        display=display,
    )
    _simulate(verified_inventory.index, candidate)
    return V3AllocationPlan(candidate, context.mode, False)


def _exact_key_from_metadata(metadata: tuple[dict[str, object], str, str, str, str, str, str, str]) -> tuple[str, ...]:
    _snapshot, period_key, as_of, cadence, schema_version, contract_version, semantic_digest, artifact_digest = metadata
    return (
        period_key, as_of, cadence, schema_version, contract_version,
        FINGERPRINT_VERSION, semantic_digest, ARTIFACT_INTEGRITY_VERSION, artifact_digest,
    )


def _simulate(index: V3IdentityIndex, candidate: V3IdentityBinding) -> None:
    try:
        parse_v3_index({
            "schema_version": 3,
            "reports": [_binding_payload(binding) for binding in (*index.bindings, candidate)],
        })
    except IdentityMetadataError as exc:
        raise _error(exc.code) from None

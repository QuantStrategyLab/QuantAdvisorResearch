"""Clean-slate QAR vNext identity wire codec and pure allocation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .artifact_integrity import (
    ArtifactIntegrityError,
    snapshot_json_wire,
)
from .identity_v3 import (
    PENDING_ARTIFACT_VALIDATION,
    V3_CANONICAL,
    V3_VARIANT,
    V3IdentityBinding,
)
from .publication_plan import (
    PublicationEntry,
    PublicationPlan,
    PublicationPlanError,
    PublicationRole,
    SelectedCandidate,
)
from .vnext_binding import VNextBindingError, binding_payload, validate_vnext_binding


VNEXT_INDEX_SCHEMA = "qar_vnext.identity_index.v1"


class VNextIdentityError(ValueError):
    """Stable, sanitized vNext identity error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AllocationMode(Enum):
    EXACT_ARTIFACT_REUSE = "EXACT_ARTIFACT_REUSE"
    CURRENT_MANDATORY = "CURRENT_MANDATORY"
    HISTORICAL_RECOVERY = "HISTORICAL_RECOVERY"


@dataclass(frozen=True, slots=True)
class AllocationContext:
    mode: AllocationMode
    target_period_key: str | None = None

    @classmethod
    def exact_artifact_reuse(cls) -> AllocationContext:
        return cls(AllocationMode.EXACT_ARTIFACT_REUSE)

    @classmethod
    def current_mandatory(cls, target_period_key: str) -> AllocationContext:
        return cls(AllocationMode.CURRENT_MANDATORY, target_period_key)

    @classmethod
    def historical_recovery(cls) -> AllocationContext:
        return cls(AllocationMode.HISTORICAL_RECOVERY)


@dataclass(frozen=True, slots=True)
class DisplayPlacement:
    display_primary: bool
    display_order: int


@dataclass(frozen=True, slots=True)
class RequestedArtifactSet:
    include_markdown: bool
    include_manifest: bool

@dataclass(frozen=True, slots=True)
class VNextIdentityIndex:
    schema_version: str
    bindings: tuple[V3IdentityBinding, ...]


@dataclass(frozen=True, slots=True)
class AllocationResult:
    binding: V3IdentityBinding
    reused_existing: bool
    publication_entry: PublicationEntry | None
    publication_plan: PublicationPlan | None


def _error(code: str) -> VNextIdentityError:
    return VNextIdentityError(code)




def _validate_binding(binding: object) -> V3IdentityBinding:
    if not isinstance(binding, V3IdentityBinding):
        raise _error("identity_binding_invalid")
    if binding.status != PENDING_ARTIFACT_VALIDATION:
        raise _error("identity_binding_invalid")
    try:
        validated = validate_vnext_binding(binding)
    except VNextBindingError as exc:
        raise _error(exc.code) from None
    if validated != binding:
        raise _error("identity_binding_invalid")
    return binding


def _validate_index(index: object) -> VNextIdentityIndex:
    if (
        not isinstance(index, VNextIdentityIndex)
        or type(index.schema_version) is not str
        or index.schema_version != VNEXT_INDEX_SCHEMA
    ):
        raise _error("identity_index_invalid")
    if type(index.bindings) is not tuple:
        raise _error("identity_index_invalid")
    bindings = tuple(_validate_binding(binding) for binding in index.bindings)
    names: dict[str, tuple[object, ...]] = {}
    identities: set[tuple[str, tuple[object, ...]]] = set()
    integrity: dict[tuple[str, str], tuple[object, ...]] = {}
    canonical_periods: set[str] = set()
    for binding in bindings:
        identity = (binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name)
        identity_key = (binding.period_key, identity)
        if identity_key in identities:
            raise _error("identity_content_conflict")
        identities.add(identity_key)
        for name in identity:
            if name is None:
                continue
            if name in names:
                raise _error("identity_target_collision")
            names[name] = identity_key
        if binding.identity_class == V3_CANONICAL:
            if binding.period_key in canonical_periods:
                raise _error("identity_canonical_conflict")
            canonical_periods.add(binding.period_key)
        integrity_key = (binding.artifact_integrity_version, binding.artifact_integrity_digest)
        metadata = (binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version, binding.contract_version, binding.semantic_fingerprint_version, binding.semantic_digest, identity)
        if integrity_key in integrity and integrity[integrity_key] != metadata:
            raise _error("identity_integrity_conflict")
        integrity[integrity_key] = metadata
    if {binding.period_key for binding in bindings} - canonical_periods:
        raise _error("canonical_missing")
    ordered = tuple(sorted(bindings, key=lambda item: (
        item.period_key, item.as_of, item.identity_class, item.json_name, item.html_name,
        item.artifact_integrity_digest,
    )))
    return VNextIdentityIndex(VNEXT_INDEX_SCHEMA, ordered)


def empty_vnext_index() -> VNextIdentityIndex:
    return VNextIdentityIndex(VNEXT_INDEX_SCHEMA, ())


def _wire_payload(index: VNextIdentityIndex) -> dict[str, object]:
    return {
        "schema_version": VNEXT_INDEX_SCHEMA,
        "entries": [binding_payload(binding) for binding in index.bindings],
    }


def parse_vnext_index(payload: Mapping[str, Any]) -> VNextIdentityIndex:
    try:
        snapshot = snapshot_json_wire(payload)
        if set(snapshot) != {"schema_version", "entries"}:
            raise _error("identity_index_invalid")
        if snapshot["schema_version"] != VNEXT_INDEX_SCHEMA or type(snapshot["schema_version"]) is not str:
            raise _error("unsupported_vnext_schema")
        entries = snapshot["entries"]
        if type(entries) is not list:
            raise _error("identity_index_invalid")
        bindings = tuple(validate_vnext_binding(entry) for entry in entries)
        return _validate_index(VNextIdentityIndex(VNEXT_INDEX_SCHEMA, bindings))
    except VNextIdentityError:
        raise
    except VNextBindingError as exc:
        raise _error(exc.code) from None
    except (ArtifactIntegrityError, AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("identity_index_invalid") from None


def serialize_vnext_index(index: VNextIdentityIndex) -> str:
    validated = _validate_index(index)
    try:
        return json.dumps(_wire_payload(validated), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("identity_index_invalid") from None


def _report_metadata(report: Mapping[str, Any], source_identity: str) -> tuple[SelectedCandidate, str]:
    try:
        selected = SelectedCandidate.from_report(report, source_identity=source_identity)
        return selected, selected.period_key
    except PublicationPlanError as exc:
        if exc.code == "candidate_source_identity_invalid":
            raise _error(exc.code) from None
        raise _error("report_invalid") from None
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("report_invalid") from None


def _validate_context(context: object, period_key: str) -> AllocationContext:
    if type(context) is not AllocationContext or type(context.mode) is not AllocationMode:
        raise _error("allocation_context_required")
    if context.mode is AllocationMode.CURRENT_MANDATORY:
        if type(context.target_period_key) is not str:
            raise _error("allocation_context_required")
        if context.target_period_key != period_key:
            raise _error("allocation_context_mismatch")
    elif context.target_period_key is not None:
        raise _error("allocation_context_required")
    return context


def _validate_requested(value: object) -> RequestedArtifactSet:
    if type(value) is not RequestedArtifactSet or type(value.include_markdown) is not bool or type(value.include_manifest) is not bool:
        raise _error("publication_policy_invalid")
    return value


def _validate_display(value: object) -> DisplayPlacement:
    if type(value) is not DisplayPlacement:
        raise _error("display_evidence_required")
    if type(value.display_primary) is not bool or type(value.display_order) is not int or value.display_order < 0:
        raise _error("display_evidence_invalid")
    return value


def _metadata_key(candidate: SelectedCandidate) -> tuple[str, ...]:
    return (
        candidate.period_key, candidate.as_of, candidate.cadence, candidate.report_schema_version,
        candidate.contract_version, candidate.semantic_fingerprint_version, candidate.semantic_digest,
        candidate.artifact_integrity_version, candidate.artifact_integrity_digest,
    )


def _binding_key(binding: V3IdentityBinding) -> tuple[str, ...]:
    return (
        binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
        binding.contract_version, binding.semantic_fingerprint_version, binding.semantic_digest,
        binding.artifact_integrity_version, binding.artifact_integrity_digest,
    )


def _new_binding(candidate: SelectedCandidate, requested: RequestedArtifactSet, display: DisplayPlacement, canonical: bool) -> V3IdentityBinding:
    suffix = "" if canonical else f".variant-{candidate.artifact_integrity_digest}"
    stem = f"advisory_report_{candidate.as_of}-{candidate.cadence}"
    return V3IdentityBinding(
        candidate.period_key, candidate.as_of, candidate.cadence, candidate.report_schema_version,
        candidate.contract_version, candidate.semantic_fingerprint_version, candidate.semantic_digest,
        candidate.artifact_integrity_version, candidate.artifact_integrity_digest,
        f"{stem}{suffix}.json",
        f"{candidate.as_of}-{candidate.cadence}-model-recommendations{suffix}.html",
        f"{stem}{suffix}.md" if requested.include_markdown else None,
        f"{stem}{suffix}.json.manifest.json" if requested.include_manifest else None,
        V3_CANONICAL if canonical else V3_VARIANT, canonical,
        display.display_primary, display.display_order, PENDING_ARTIFACT_VALIDATION,
    )


def _check_policy(
    binding: V3IdentityBinding,
    requested: RequestedArtifactSet,
    display: DisplayPlacement,
    *,
    require_stored_display: bool,
) -> None:
    attachment_mismatch = (
        (binding.markdown_name is not None) != requested.include_markdown
        or (binding.manifest_name is not None) != requested.include_manifest
    )
    display_mismatch = require_stored_display and (
        binding.display_primary != display.display_primary or binding.display_order != display.display_order
    )
    if attachment_mismatch or display_mismatch:
        raise _error("identity_reuse_mismatch")


def _simulate(index: VNextIdentityIndex, candidate: V3IdentityBinding) -> None:
    _validate_index(VNextIdentityIndex(VNEXT_INDEX_SCHEMA, (*index.bindings, candidate)))


def allocate_vnext_identity(
    report: Mapping[str, Any],
    *,
    index: VNextIdentityIndex,
    context: AllocationContext,
    requested_artifacts: RequestedArtifactSet,
    display_placement: DisplayPlacement,
    source_identity: str,
) -> AllocationResult:
    """Validate every input, allocate clean identity, and simulate the full index."""

    requested = _validate_requested(requested_artifacts)
    display = _validate_display(display_placement)
    candidate, period_key = _report_metadata(report, source_identity)
    _validate_context(context, period_key)
    validated_index = _validate_index(index)
    exact = [binding for binding in validated_index.bindings if _binding_key(binding) == _metadata_key(candidate)]
    if len(exact) > 1:
        raise _error("identity_integrity_conflict")
    if exact:
        binding = exact[0]
        _check_policy(
            binding,
            requested,
            display,
            require_stored_display=context.mode is AllocationMode.EXACT_ARTIFACT_REUSE,
        )
        publication_entry = None
        publication_plan = None
        if context.mode is AllocationMode.CURRENT_MANDATORY:
            publication_entry = PublicationEntry(candidate, binding, PublicationRole.MANDATORY_CURRENT, display.display_primary, display.display_order, "vnext")
            publication_plan = PublicationPlan((publication_entry,))
        return AllocationResult(binding, True, publication_entry, publication_plan)
    if context.mode is AllocationMode.EXACT_ARTIFACT_REUSE:
        raise _error("exact_artifact_not_found")
    period_bindings = [binding for binding in validated_index.bindings if binding.period_key == period_key]
    canonical_exists = any(binding.identity_class == V3_CANONICAL for binding in period_bindings)
    if context.mode is AllocationMode.HISTORICAL_RECOVERY and not canonical_exists:
        raise _error("canonical_bootstrap_required")
    binding = _new_binding(candidate, requested, display, canonical=context.mode is AllocationMode.CURRENT_MANDATORY and not canonical_exists)
    _simulate(validated_index, binding)
    publication_entry = None
    publication_plan = None
    if context.mode is AllocationMode.CURRENT_MANDATORY:
        publication_entry = PublicationEntry(candidate, binding, PublicationRole.MANDATORY_CURRENT, display.display_primary, display.display_order, "vnext")
        publication_plan = PublicationPlan((publication_entry,))
    return AllocationResult(binding, False, publication_entry, publication_plan)


__all__ = [
    "AllocationContext", "AllocationMode", "AllocationResult", "DisplayPlacement",
    "RequestedArtifactSet", "VNEXT_INDEX_SCHEMA", "VNextIdentityError", "VNextIdentityIndex",
    "allocate_vnext_identity", "empty_vnext_index", "parse_vnext_index", "serialize_vnext_index",
]

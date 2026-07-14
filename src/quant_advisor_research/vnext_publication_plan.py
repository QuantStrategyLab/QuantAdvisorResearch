"""Pure clean-slate vNext allocation and publication-plan contract.

No filesystem, network, publisher, or legacy compatibility is involved.  A
source report is evidence; its basename never chooses a public target.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from enum import Enum
from typing import Any

from .vnext_identity_v1 import (
    MAX_SAFE_JSON_INTEGER,
    SEMANTIC_FINGERPRINT_VERSION,
    ARTIFACT_ALGORITHM_VERSION,
    V3_CANONICAL,
    V3_VARIANT,
    VNEXT_STATUS,
    VNextIdentityBinding,
    VNextIdentityError,
    VNextIdentityIndex,
    report_identity_evidence,
)


class VNextPublicationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AllocationMode(Enum):
    EXACT_ARTIFACT_REUSE = "EXACT_ARTIFACT_REUSE"
    CURRENT_MANDATORY = "CURRENT_MANDATORY"
    HISTORICAL_RECOVERY = "HISTORICAL_RECOVERY"


class PublicationRole(Enum):
    MANDATORY_CURRENT = "MANDATORY_CURRENT"
    RECOVERED_HISTORY = "RECOVERED_HISTORY"


def _error(code: str) -> VNextPublicationError:
    return VNextPublicationError(code)


def _source(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value or "/" in value or "\\" in value or value in {".", ".."}:
        raise _error("source_identity_invalid")
    return value


def _display(primary: object, order: object) -> tuple[bool, int]:
    if type(primary) is not bool or type(order) is not int or type(order) is bool or not 0 <= order <= MAX_SAFE_JSON_INTEGER:
        raise _error("display_invalid")
    return primary, order


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class RequestedArtifacts:
    markdown: bool = False
    manifest: bool = False

    def __post_init__(self) -> None:
        if type(self.markdown) is not bool or type(self.manifest) is not bool:
            raise _error("attachment_policy_invalid")


@dataclass(frozen=True, slots=True)
class DisplayPlacement:
    primary: bool
    order: int

    def __post_init__(self) -> None:
        _display(self.primary, self.order)


@dataclass(frozen=True, slots=True)
class AllocationContext:
    mode: AllocationMode
    requested_artifacts: RequestedArtifacts
    display: DisplayPlacement
    target_period_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.mode) is not AllocationMode:
            raise _error("allocation_context_invalid")
        if not isinstance(self.requested_artifacts, RequestedArtifacts) or not isinstance(self.display, DisplayPlacement):
            raise _error("allocation_context_invalid")
        if self.target_period_key is not None and type(self.target_period_key) is not str:
            raise _error("allocation_context_invalid")
        if self.mode is AllocationMode.CURRENT_MANDATORY and not self.target_period_key:
            raise _error("allocation_context_required")
        if self.mode is not AllocationMode.CURRENT_MANDATORY and self.target_period_key is not None:
            raise _error("allocation_context_invalid")


@dataclass(frozen=True, slots=True)
class SelectedCandidate:
    report_snapshot: Mapping[str, object]
    source_identity: str
    period_key: str
    as_of: str
    cadence: str
    report_schema_version: str
    contract_version: str
    semantic_digest: str
    artifact_integrity_digest: str

    @classmethod
    def from_report(cls, report: Mapping[str, Any], *, source_identity: str) -> "SelectedCandidate":
        _source(source_identity)
        try:
            snapshot, period, as_of, cadence, schema, contract, semantic, artifact = report_identity_evidence(report)
            return cls(MappingProxyType({key: _freeze(value) for key, value in snapshot.items()}), source_identity,
                       period, as_of, cadence, schema, contract, semantic, artifact)
        except VNextPublicationError:
            raise
        except (VNextIdentityError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
            raise _error("candidate_invalid") from None


@dataclass(frozen=True, slots=True)
class PublicationEntry:
    candidate: SelectedCandidate
    binding: VNextIdentityBinding
    role: PublicationRole
    display_primary: bool
    display_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SelectedCandidate) or not isinstance(self.binding, VNextIdentityBinding):
            raise _error("publication_entry_invalid")
        if type(self.role) is not PublicationRole:
            raise _error("publication_role_invalid")
        _display(self.display_primary, self.display_order)
        _validate_candidate_binding(self.candidate, self.binding)


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    entries: tuple[PublicationEntry, ...]

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or not self.entries:
            raise _error("publication_plan_invalid")
        _validate_plan(self.entries)


@dataclass(frozen=True, slots=True)
class AllocationResult:
    binding: VNextIdentityBinding
    reused_existing: bool


def _validate_candidate_binding(candidate: SelectedCandidate, binding: VNextIdentityBinding) -> None:
    if (candidate.period_key, candidate.as_of, candidate.cadence, candidate.report_schema_version, candidate.contract_version,
        candidate.semantic_digest, candidate.artifact_integrity_digest) != (
        binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version, binding.contract_version,
        binding.semantic_digest, binding.artifact_integrity_digest):
        raise _error("candidate_binding_mismatch")


def _names(as_of: str, cadence: str, *, variant_digest: str | None, artifacts: RequestedArtifacts) -> tuple[str, str, str | None, str | None]:
    suffix = "" if variant_digest is None else f".variant-{variant_digest}"
    stem = f"advisory_report_{as_of}-{cadence}{suffix}"
    return (
        f"{stem}.json",
        f"{as_of}-{cadence}-model-recommendations{suffix}.html",
        f"{stem}.md" if artifacts.markdown else None,
        f"{stem}.json.manifest.json" if artifacts.manifest else None,
    )


def _new_binding(candidate: SelectedCandidate, identity_class: str, artifacts: RequestedArtifacts, display: DisplayPlacement) -> VNextIdentityBinding:
    if identity_class not in {V3_CANONICAL, V3_VARIANT}:
        raise _error("unsupported_identity_class")
    json_name, html_name, markdown_name, manifest_name = _names(
        candidate.as_of, candidate.cadence,
        variant_digest=None if identity_class == V3_CANONICAL else candidate.artifact_integrity_digest,
        artifacts=artifacts,
    )
    return VNextIdentityBinding(
        candidate.period_key, candidate.as_of, candidate.cadence, candidate.report_schema_version,
        candidate.contract_version, SEMANTIC_FINGERPRINT_VERSION, candidate.semantic_digest,
        ARTIFACT_ALGORITHM_VERSION, candidate.artifact_integrity_digest, json_name, html_name,
        markdown_name, manifest_name, identity_class, identity_class == V3_CANONICAL,
        display.primary, display.order, VNEXT_STATUS,
    )


def _policy_matches(binding: VNextIdentityBinding, artifacts: RequestedArtifacts) -> bool:
    return (binding.markdown_name is not None) == artifacts.markdown and (binding.manifest_name is not None) == artifacts.manifest


def _candidate_key(candidate: SelectedCandidate) -> tuple[object, ...]:
    return (candidate.period_key, candidate.as_of, candidate.cadence, candidate.report_schema_version,
            candidate.contract_version, candidate.semantic_digest, candidate.artifact_integrity_digest)


def _same_artifact(a: SelectedCandidate, b: VNextIdentityBinding) -> bool:
    return _candidate_key(a) == (b.period_key, b.as_of, b.cadence, b.report_schema_version, b.contract_version,
                                 b.semantic_digest, b.artifact_integrity_digest)


def _simulate(index: VNextIdentityIndex, candidate: SelectedCandidate, binding: VNextIdentityBinding) -> None:
    try:
        _validate_candidate_binding(candidate, binding)
        VNextIdentityIndex(index.bindings + (binding,))
    except VNextPublicationError:
        raise
    except VNextIdentityError as exc:
        raise _error(exc.code) from None
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("identity_simulation_invalid") from None


def allocate_identity(index: VNextIdentityIndex, candidate: SelectedCandidate, context: AllocationContext) -> AllocationResult:
    if not isinstance(index, VNextIdentityIndex) or not isinstance(candidate, SelectedCandidate) or not isinstance(context, AllocationContext):
        raise _error("allocation_input_invalid")
    try:
        VNextIdentityIndex(index.bindings)
    except VNextIdentityError as exc:
        raise _error(exc.code) from None
    if context.mode is AllocationMode.CURRENT_MANDATORY and context.target_period_key != candidate.period_key:
        raise _error("allocation_context_mismatch")
    same = [binding for binding in index.bindings if _same_artifact(candidate, binding)]
    if len(same) > 1:
        raise _error("identity_conflict")
    if same:
        binding = same[0]
        if not _policy_matches(binding, context.requested_artifacts):
            raise _error("identity_reuse_mismatch")
        if context.mode is AllocationMode.EXACT_ARTIFACT_REUSE and (
            binding.display_primary != context.display.primary or binding.display_order != context.display.order
        ):
            raise _error("identity_reuse_mismatch")
        if context.mode is AllocationMode.EXACT_ARTIFACT_REUSE:
            return AllocationResult(binding, True)
        return AllocationResult(binding, True)
    if context.mode is AllocationMode.EXACT_ARTIFACT_REUSE:
        raise _error("identity_reuse_not_found")
    canonical = [binding for binding in index.bindings if binding.period_key == candidate.period_key and binding.canonical_identity]
    if context.mode is AllocationMode.HISTORICAL_RECOVERY and not canonical:
        raise _error("canonical_bootstrap_required")
    identity_class = V3_VARIANT if canonical else V3_CANONICAL
    next_order = max((item.display_order for item in index.bindings if item.period_key == candidate.period_key), default=-1) + 1
    binding = _new_binding(
        candidate,
        identity_class,
        context.requested_artifacts,
        DisplayPlacement(False, next_order),
    )
    _simulate(index, candidate, binding)
    return AllocationResult(binding, False)


def _entry_key(entry: PublicationEntry) -> tuple[object, ...]:
    return (entry.candidate.period_key, entry.display_order, not entry.display_primary, entry.role.value, entry.binding.json_name)


def _validate_plan(entries: tuple[PublicationEntry, ...]) -> None:
    if sum(entry.role is PublicationRole.MANDATORY_CURRENT for entry in entries) != 1:
        raise _error("mandatory_current_invalid")
    target_seen: set[str] = set()
    display: dict[str, tuple[bool, set[int]]] = {}
    for entry in entries:
        if entry.role is PublicationRole.MANDATORY_CURRENT and entry.binding.period_key != entry.candidate.period_key:
            raise _error("mandatory_current_invalid")
        for name in (entry.binding.json_name, entry.binding.html_name, entry.binding.markdown_name, entry.binding.manifest_name):
            if name is not None and name in target_seen:
                raise _error("publication_target_collision")
            if name is not None:
                target_seen.add(name)
        primary, orders = display.setdefault(entry.binding.period_key, (False, set()))
        if entry.display_primary and primary:
            raise _error("display_primary_conflict")
        if entry.display_order in orders:
            raise _error("display_order_conflict")
        display[entry.binding.period_key] = (primary or entry.display_primary, orders | {entry.display_order})


def build_publication_plan(entries: list[PublicationEntry] | tuple[PublicationEntry, ...]) -> PublicationPlan:
    if type(entries) not in {list, tuple}:
        raise _error("publication_plan_invalid")
    for entry in entries:
        if not isinstance(entry, PublicationEntry):
            raise _error("publication_entry_invalid")
    return PublicationPlan(tuple(sorted(entries, key=_entry_key)))


__all__ = [
    "AllocationContext", "AllocationMode", "AllocationResult", "DisplayPlacement", "PublicationEntry", "PublicationPlan",
    "PublicationRole", "RequestedArtifacts", "SelectedCandidate", "VNextPublicationError", "allocate_identity",
    "build_publication_plan",
]

"""Pure publication-plan contract separating source, identity, and display."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from .artifact_integrity import (
    ArtifactIntegrityError,
    make_artifact_integrity_evidence,
    snapshot_json_wire,
)
from .contracts import AdvisoryValidationError, validate_advisory_report
from .identity_lifecycle import FINGERPRINT_VERSION, IdentityMetadataError
from .identity_v3 import (
    LEGACY_V2,
    PENDING_ARTIFACT_VALIDATION,
    V3_CANONICAL,
    V3_VARIANT,
    V3IdentityBinding,
    _validate_v3_entry,
)
from .period_contract import PeriodContractError, canonical_period_identity
from .publisher import report_content_fingerprint
from .time_contract import TimeContractError, contract_version_for_schema
from .vnext_binding import VNextBindingError, VNextIdentityBinding, validate_vnext_binding


class PublicationPlanError(ValueError):
    """Stable, sanitized pure publication-plan error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublicationRole(Enum):
    MANDATORY_CURRENT = "MANDATORY_CURRENT"
    RECOVERED_HISTORY = "RECOVERED_HISTORY"


def _error(code: str) -> PublicationPlanError:
    return PublicationPlanError(code)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _semantic_digest(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(report_content_fingerprint(dict(snapshot)).encode("utf-8")).hexdigest()


def _validate_source_identity(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise _error("candidate_source_identity_invalid")
    return value


@dataclass(frozen=True, slots=True)
class SelectedCandidate:
    """Validated report snapshot; its source identity is not a public basename."""

    report_snapshot: Mapping[str, object]
    source_identity: str
    period_key: str
    as_of: str
    cadence: str
    report_schema_version: str
    contract_version: str
    semantic_fingerprint_version: str
    semantic_digest: str
    artifact_integrity_version: str
    artifact_integrity_digest: str

    @classmethod
    def from_report(cls, report: Mapping[str, Any], *, source_identity: str) -> SelectedCandidate:
        source_identity = _validate_source_identity(source_identity)
        try:
            snapshot = snapshot_json_wire(report)
            validate_advisory_report(snapshot)
            schema_version = snapshot["schema_version"]
            as_of = snapshot["as_of"]
            cadence = snapshot["cadence"]
            if not all(type(value) is str for value in (schema_version, as_of, cadence)):
                raise _error("candidate_metadata_mismatch")
            period_key = canonical_period_identity(cadence, as_of).key
            contract_version = snapshot.get("contract_version") or contract_version_for_schema(schema_version)
            if type(contract_version) is not str:
                raise _error("candidate_metadata_mismatch")
            evidence = make_artifact_integrity_evidence(snapshot)
            snapshot_view = MappingProxyType({key: _freeze(value) for key, value in snapshot.items()})
            return cls(
                snapshot_view,
                source_identity,
                period_key,
                as_of,
                cadence,
                schema_version,
                contract_version,
                FINGERPRINT_VERSION,
                _semantic_digest(snapshot),
                evidence.version,
                evidence.digest,
            )
        except PublicationPlanError:
            raise
        except (
            AdvisoryValidationError,
            ArtifactIntegrityError,
            IdentityMetadataError,
            PeriodContractError,
            TimeContractError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeError,
            RecursionError,
        ):
            raise _error("candidate_invalid") from None


@dataclass(frozen=True, slots=True)
class PublicationTargetEvidence:
    json_name: str
    html_name: str
    markdown_name: str | None
    manifest_name: str | None


@dataclass(frozen=True, slots=True)
class QuarantineEvidence:
    source_identity: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        _validate_source_identity(self.source_identity)
        if type(self.status) is not str or not self.status or type(self.reason) is not str or not self.reason:
            raise _error("quarantine_invalid")


@dataclass(frozen=True, slots=True)
class PublicationEntry:
    """One selected source bound to one verified v3 public identity."""

    candidate: SelectedCandidate
    binding: V3IdentityBinding | VNextIdentityBinding
    role: PublicationRole
    display_primary: bool
    display_order: int

    def __post_init__(self) -> None:
        _validate_entry(self)

    @property
    def targets(self) -> PublicationTargetEvidence:
        return PublicationTargetEvidence(
            self.binding.json_name,
            self.binding.html_name,
            self.binding.markdown_name,
            self.binding.manifest_name,
        )


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    """Deterministic, I/O-free plan consumed by future publication integration."""

    entries: tuple[PublicationEntry, ...]
    quarantine: tuple[QuarantineEvidence, ...] = ()
    preflight_targets: tuple[PublicationTargetEvidence, ...] = ()

    def __post_init__(self) -> None:
        normalized = build_publication_plan(self.entries, quarantine=self.quarantine)
        object.__setattr__(self, "entries", normalized.entries)
        object.__setattr__(self, "quarantine", normalized.quarantine)
        object.__setattr__(self, "preflight_targets", normalized.preflight_targets)


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


def _validate_binding(binding: object) -> V3IdentityBinding | VNextIdentityBinding:
    if type(binding) is VNextIdentityBinding:
        try:
            return validate_vnext_binding(binding)
        except VNextBindingError as exc:
            raise _error(exc.code) from None
    if type(binding) is not V3IdentityBinding:
        raise _error("identity_binding_invalid")
    if binding.status != PENDING_ARTIFACT_VALIDATION:
        raise _error("identity_binding_invalid")
    if binding.identity_class == LEGACY_V2:
        raise _error("legacy_binding_not_migrated")
    if binding.identity_class not in {V3_CANONICAL, V3_VARIANT}:
        raise _error("identity_binding_invalid")
    try:
        validated = _validate_v3_entry(_binding_payload(binding))
    except (IdentityMetadataError, AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError):
        raise _error("identity_binding_invalid") from None
    if validated != binding:
        raise _error("identity_binding_invalid")
    return binding


def _validate_entry(entry: PublicationEntry) -> None:
    if not isinstance(entry, PublicationEntry):
        raise _error("publication_entry_invalid")
    if not isinstance(entry.candidate, SelectedCandidate):
        raise _error("candidate_invalid")
    if type(entry.role) is not PublicationRole:
        raise _error("publication_role_invalid")
    if type(entry.display_primary) is not bool or type(entry.display_order) is not int or entry.display_order < 0:
        raise _error("display_evidence_invalid")
    binding = _validate_binding(entry.binding)
    candidate = entry.candidate
    try:
        rebuilt = SelectedCandidate.from_report(
            _thaw(candidate.report_snapshot), source_identity=candidate.source_identity
        )
    except PublicationPlanError:
        raise
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("candidate_invalid") from None
    if rebuilt != candidate:
        raise _error("candidate_invalid")
    if (
        candidate.period_key != binding.period_key
        or candidate.as_of != binding.as_of
        or candidate.cadence != binding.cadence
        or candidate.report_schema_version != binding.report_schema_version
        or candidate.contract_version != binding.contract_version
        or candidate.semantic_fingerprint_version != binding.semantic_fingerprint_version
        or candidate.semantic_digest != binding.semantic_digest
        or candidate.artifact_integrity_version != binding.artifact_integrity_version
        or candidate.artifact_integrity_digest != binding.artifact_integrity_digest
    ):
        raise _error("candidate_binding_mismatch")


def _entry_sort_key(entry: PublicationEntry) -> tuple[object, ...]:
    return (
        entry.candidate.period_key,
        entry.display_order,
        not entry.display_primary,
        entry.role.value,
        entry.binding.identity_class,
        entry.binding.json_name,
        entry.binding.html_name,
        entry.candidate.source_identity,
    )


def build_publication_plan(
    entries: tuple[PublicationEntry, ...] | list[PublicationEntry],
    *,
    quarantine: tuple[QuarantineEvidence, ...] | list[QuarantineEvidence] = (),
) -> PublicationPlan:
    if type(entries) not in {tuple, list} or type(quarantine) not in {tuple, list}:
        raise _error("publication_plan_invalid")
    normalized_entries = tuple(sorted(entries, key=_entry_sort_key))
    if sum(entry.role is PublicationRole.MANDATORY_CURRENT for entry in normalized_entries) != 1:
        raise _error("mandatory_current_invalid")
    target_seen: dict[str, str] = {}
    targets: list[PublicationTargetEvidence] = []
    for entry in normalized_entries:
        _validate_entry(entry)
        target = entry.targets
        targets.append(target)
        for name in (target.json_name, target.html_name, target.markdown_name, target.manifest_name):
            if name is None:
                continue
            previous = target_seen.get(name)
            if previous is not None:
                raise _error("publication_target_collision")
            target_seen[name] = entry.candidate.source_identity
    normalized_quarantine = tuple(sorted(quarantine, key=lambda item: (item.source_identity, item.status, item.reason)))
    return _make_plan(normalized_entries, normalized_quarantine, tuple(targets))


def _make_plan(
    entries: tuple[PublicationEntry, ...],
    quarantine: tuple[QuarantineEvidence, ...],
    targets: tuple[PublicationTargetEvidence, ...],
) -> PublicationPlan:
    plan = object.__new__(PublicationPlan)
    object.__setattr__(plan, "entries", entries)
    object.__setattr__(plan, "quarantine", quarantine)
    object.__setattr__(plan, "preflight_targets", targets)
    return plan


__all__ = [
    "PublicationEntry",
    "PublicationPlan",
    "PublicationPlanError",
    "PublicationRole",
    "PublicationTargetEvidence",
    "QuarantineEvidence",
    "SelectedCandidate",
    "build_publication_plan",
]

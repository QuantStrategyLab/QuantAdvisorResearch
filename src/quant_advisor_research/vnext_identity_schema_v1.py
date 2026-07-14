"""Pure clean-slate QAR vNext identity/index schema v1.

This module deliberately stops at structural identity evidence. It has no
report verification, allocation, publication plan, legacy fallback, or I/O.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .artifact_integrity import ArtifactIntegrityError, snapshot_json_wire
from .period_contract import PeriodContractError, canonical_period_identity
from .time_contract import TimeContractError, contract_version_for_schema

VNEXT_SCHEMA_VERSION = 1
VNEXT_NAMESPACE = "qar_vnext_identity.v1"
VNEXT_BINDING_NAMESPACE = "qar_vnext_binding.v1"
VNEXT_STATUS = "PENDING_ARTIFACT_VALIDATION"
SEMANTIC_ALGORITHM_VERSION = "semantic_fingerprint.v1.sha256"
ARTIFACT_ALGORITHM_VERSION = "validated_report.v1.canonical-json.sha256"
MAX_SAFE_JSON_INTEGER = 2**53 - 1
V3_CANONICAL = "V3_CANONICAL"
V3_VARIANT = "V3_VARIANT"

_DATE = r"(?P<as_of>\d{4}-\d{2}-\d{2})"
_DIGEST = r"(?P<digest>[0-9a-f]{64})"
_PATTERNS = {
    "json": re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.json$"),
    "html": re.compile(rf"^{_DATE}-(?P<cadence>daily|weekly|monthly)-model-recommendations(?:\.variant-{_DIGEST})?\.html$"),
    "md": re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.md$"),
    "manifest": re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.json\.manifest\.json$"),
}


class VNextIdentityError(ValueError):
    """Stable, sanitized schema-v1 identity error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _error(code: str) -> VNextIdentityError:
    return VNextIdentityError(code)


def _exact(value: object, typ: type, code: str) -> Any:
    if type(value) is not typ:
        raise _error(code)
    return value


def _digest(value: object, code: str) -> str:
    value = _exact(value, str, code)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise _error(code)
    return value


def _period_key(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError):
        raise _error("period_mismatch") from None


def _check_target(value: object, kind: str, *, as_of: str, cadence: str, suffix: str | None) -> str:
    value = _exact(value, str, "target_invalid")
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise _error("target_invalid")
    match = _PATTERNS[kind].fullmatch(value)
    if match is None or match.group("as_of") != as_of or match.group("cadence") != cadence:
        raise _error("target_mismatch")
    if match.groupdict().get("digest") != suffix:
        raise _error("target_digest_mismatch")
    return value


@dataclass(frozen=True, slots=True)
class VNextIdentityBinding:
    period_key: str
    as_of: str
    cadence: str
    report_schema_version: str
    contract_version: str
    semantic_fingerprint_version: str
    semantic_digest: str
    artifact_integrity_version: str
    artifact_integrity_digest: str
    json_name: str
    html_name: str
    markdown_name: str | None
    manifest_name: str | None
    identity_class: str
    canonical_identity: bool
    display_primary: bool
    display_order: int
    status: str = VNEXT_STATUS

    def __post_init__(self) -> None:
        _validate_binding(self)


@dataclass(frozen=True, slots=True)
class VNextIdentityIndex:
    bindings: tuple[VNextIdentityBinding, ...]
    schema_version: int = VNEXT_SCHEMA_VERSION
    namespace: str = VNEXT_NAMESPACE

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != VNEXT_SCHEMA_VERSION:
            raise _error("unsupported_schema")
        if type(self.namespace) is not str or self.namespace != VNEXT_NAMESPACE:
            raise _error("unsupported_namespace")
        if type(self.bindings) is not tuple or not all(isinstance(item, VNextIdentityBinding) for item in self.bindings):
            raise _error("index_invalid")
        _validate_index(self.bindings)
        object.__setattr__(self, "bindings", tuple(sorted(self.bindings, key=_binding_sort_key)))


def _validate_binding(binding: VNextIdentityBinding) -> None:
    if not isinstance(binding, VNextIdentityBinding):
        raise _error("binding_invalid")
    text_fields = (
        binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
        binding.contract_version, binding.semantic_fingerprint_version, binding.semantic_digest,
        binding.artifact_integrity_version, binding.artifact_integrity_digest, binding.json_name,
        binding.html_name, binding.identity_class, binding.status,
    )
    if any(type(value) is not str or not value for value in text_fields):
        raise _error("binding_invalid")
    if binding.period_key != _period_key(binding.as_of, binding.cadence):
        raise _error("period_mismatch")
    if binding.report_schema_version not in {"5", "6"}:
        raise _error("report_schema_unsupported")
    try:
        expected = contract_version_for_schema(binding.report_schema_version)
    except (TimeContractError, TypeError, ValueError):
        raise _error("report_schema_unsupported") from None
    if binding.contract_version != expected:
        raise _error("contract_mismatch")
    if binding.semantic_fingerprint_version != SEMANTIC_ALGORITHM_VERSION:
        raise _error("semantic_algorithm_unsupported")
    if binding.artifact_integrity_version != ARTIFACT_ALGORITHM_VERSION:
        raise _error("artifact_algorithm_unsupported")
    _digest(binding.semantic_digest, "semantic_digest_invalid")
    _digest(binding.artifact_integrity_digest, "artifact_digest_invalid")
    if binding.identity_class not in {V3_CANONICAL, V3_VARIANT}:
        raise _error("identity_class_unsupported")
    if type(binding.canonical_identity) is not bool or type(binding.display_primary) is not bool:
        raise _error("boolean_invalid")
    if binding.canonical_identity != (binding.identity_class == V3_CANONICAL):
        raise _error("identity_class_mismatch")
    if type(binding.display_order) is not int or type(binding.display_order) is bool or not 0 <= binding.display_order <= MAX_SAFE_JSON_INTEGER:
        raise _error("display_order_invalid")
    if binding.status != VNEXT_STATUS:
        raise _error("status_invalid")
    suffix = None if binding.identity_class == V3_CANONICAL else binding.artifact_integrity_digest
    _check_target(binding.json_name, "json", as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    _check_target(binding.html_name, "html", as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    if binding.markdown_name is not None:
        _check_target(binding.markdown_name, "md", as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    if binding.manifest_name is not None:
        _check_target(binding.manifest_name, "manifest", as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)


def _validate_index(bindings: tuple[VNextIdentityBinding, ...]) -> None:
    canonical_periods: set[str] = set()
    names: set[str] = set()
    artifact_identities: set[tuple[str, str, str, str, str, str, str]] = set()
    artifact_digests: set[str] = set()
    display: dict[str, tuple[bool, set[int]]] = {}
    for binding in bindings:
        _validate_binding(binding)
        exact = (
            binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
            binding.contract_version, binding.semantic_digest, binding.artifact_integrity_digest,
        )
        if exact in artifact_identities:
            raise _error("identity_duplicate")
        artifact_identities.add(exact)
        if binding.canonical_identity:
            if binding.period_key in canonical_periods:
                raise _error("canonical_conflict")
            canonical_periods.add(binding.period_key)
        primary, orders = display.setdefault(binding.period_key, (False, set()))
        if binding.display_primary and primary:
            raise _error("display_primary_conflict")
        if binding.display_order in orders:
            raise _error("display_order_conflict")
        display[binding.period_key] = (primary or binding.display_primary, orders | {binding.display_order})
        for name in (binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name):
            if name is not None:
                if name in names:
                    raise _error("target_collision")
                names.add(name)
        if binding.artifact_integrity_digest in artifact_digests:
            raise _error("artifact_digest_conflict")
        artifact_digests.add(binding.artifact_integrity_digest)
    if {item.period_key for item in bindings} - canonical_periods:
        raise _error("canonical_missing")


def _snapshot(payload: Mapping[str, Any]) -> dict[str, object]:
    try:
        return snapshot_json_wire(payload)
    except (ArtifactIntegrityError, TypeError, ValueError, UnicodeError, RecursionError):
        raise _error("wire_invalid") from None


def _binding_sort_key(binding: VNextIdentityBinding) -> tuple[object, ...]:
    return (
        binding.period_key, not binding.canonical_identity, binding.artifact_integrity_digest,
        binding.semantic_digest, binding.json_name, binding.html_name,
        binding.markdown_name or "", binding.manifest_name or "",
    )


def _from_entry(entry: object) -> VNextIdentityBinding:
    required = {
        "binding_namespace", "period_key", "as_of", "cadence", "report_schema_version", "contract_version",
        "semantic_fingerprint_version", "semantic_digest", "artifact_integrity_version", "artifact_integrity_digest",
        "json", "html", "identity_class", "canonical_identity", "display_primary", "display_order", "status",
    }
    optional = {"md", "manifest"}
    if type(entry) is not dict or not required.issubset(entry) or set(entry) - required - optional:
        raise _error("entry_invalid")
    if entry["binding_namespace"] != VNEXT_BINDING_NAMESPACE:
        raise _error("binding_namespace_unsupported")
    if "md" in entry and type(entry["md"]) is not str:
        raise _error("target_invalid")
    if "manifest" in entry and type(entry["manifest"]) is not str:
        raise _error("target_invalid")
    try:
        return VNextIdentityBinding(
            period_key=entry["period_key"], as_of=entry["as_of"], cadence=entry["cadence"],
            report_schema_version=entry["report_schema_version"], contract_version=entry["contract_version"],
            semantic_fingerprint_version=entry["semantic_fingerprint_version"], semantic_digest=entry["semantic_digest"],
            artifact_integrity_version=entry["artifact_integrity_version"], artifact_integrity_digest=entry["artifact_integrity_digest"],
            json_name=entry["json"], html_name=entry["html"], markdown_name=entry.get("md"), manifest_name=entry.get("manifest"),
            identity_class=entry["identity_class"], canonical_identity=entry["canonical_identity"],
            display_primary=entry["display_primary"], display_order=entry["display_order"], status=entry["status"],
        )
    except VNextIdentityError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("entry_invalid") from None


def parse_vnext_identity_index(payload: Mapping[str, Any]) -> VNextIdentityIndex:
    snapshot = _snapshot(payload)
    if set(snapshot) != {"schema_version", "namespace", "reports"}:
        raise _error("wire_invalid")
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != VNEXT_SCHEMA_VERSION:
        raise _error("unsupported_schema")
    if type(snapshot["namespace"]) is not str or snapshot["namespace"] != VNEXT_NAMESPACE:
        raise _error("unsupported_namespace")
    if type(snapshot["reports"]) is not list:
        raise _error("wire_invalid")
    try:
        bindings = tuple(sorted((_from_entry(item) for item in snapshot["reports"]), key=_binding_sort_key))
        return VNextIdentityIndex(bindings)
    except VNextIdentityError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("wire_invalid") from None


def _to_entry(binding: VNextIdentityBinding) -> dict[str, object]:
    _validate_binding(binding)
    entry: dict[str, object] = {
        "binding_namespace": VNEXT_BINDING_NAMESPACE, "period_key": binding.period_key, "as_of": binding.as_of,
        "cadence": binding.cadence, "report_schema_version": binding.report_schema_version,
        "contract_version": binding.contract_version, "semantic_fingerprint_version": binding.semantic_fingerprint_version,
        "semantic_digest": binding.semantic_digest, "artifact_integrity_version": binding.artifact_integrity_version,
        "artifact_integrity_digest": binding.artifact_integrity_digest, "json": binding.json_name,
        "html": binding.html_name, "identity_class": binding.identity_class, "canonical_identity": binding.canonical_identity,
        "display_primary": binding.display_primary, "display_order": binding.display_order, "status": binding.status,
    }
    if binding.markdown_name is not None:
        entry["md"] = binding.markdown_name
    if binding.manifest_name is not None:
        entry["manifest"] = binding.manifest_name
    return entry


def serialize_vnext_identity_index(index: VNextIdentityIndex) -> dict[str, object]:
    if not isinstance(index, VNextIdentityIndex):
        raise _error("index_invalid")
    _validate_index(index.bindings)
    payload = {
        "schema_version": VNEXT_SCHEMA_VERSION, "namespace": VNEXT_NAMESPACE,
        "reports": [_to_entry(binding) for binding in sorted(index.bindings, key=_binding_sort_key)],
    }
    parse_vnext_identity_index(payload)
    return payload


__all__ = [
    "ARTIFACT_ALGORITHM_VERSION", "MAX_SAFE_JSON_INTEGER", "SEMANTIC_ALGORITHM_VERSION",
    "V3_CANONICAL", "V3_VARIANT", "VNEXT_BINDING_NAMESPACE", "VNEXT_NAMESPACE", "VNEXT_SCHEMA_VERSION",
    "VNEXT_STATUS", "VNextIdentityBinding", "VNextIdentityError", "VNextIdentityIndex",
    "parse_vnext_identity_index", "serialize_vnext_identity_index",
]

"""Clean-slate QAR vNext identity-index schema v1.

This namespace is intentionally independent from legacy identity codecs.  It
accepts exactly one immutable algorithm pair; future algorithm changes require
another schema/namespace rather than read compatibility or fallback.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .artifact_integrity import ArtifactIntegrityError, ARTIFACT_INTEGRITY_VERSION, make_artifact_integrity_evidence, snapshot_json_wire
from .contracts import AdvisoryValidationError, validate_advisory_report
from .period_contract import PeriodContractError, canonical_period_identity
from .time_contract import TimeContractError, contract_version_for_schema

VNEXT_SCHEMA_VERSION = 1
VNEXT_WIRE_NAMESPACE = "qar_vnext_identity.v1"
VNEXT_BINDING_NAMESPACE = "qar_vnext_binding.v1"
VNEXT_STATUS = "PENDING_ARTIFACT_VALIDATION"
SEMANTIC_FINGERPRINT_VERSION = "semantic_fingerprint.v1.sha256"
ARTIFACT_ALGORITHM_VERSION = ARTIFACT_INTEGRITY_VERSION
MAX_SAFE_JSON_INTEGER = 2**53 - 1
V3_CANONICAL = "V3_CANONICAL"
V3_VARIANT = "V3_VARIANT"

_DATE = r"(?P<as_of>\d{4}-\d{2}-\d{2})"
_DIGEST = r"(?P<digest>[0-9a-f]{64})"
_JSON = re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.json$")
_HTML = re.compile(rf"^{_DATE}-(?P<cadence>daily|weekly|monthly)-model-recommendations(?:\.variant-{_DIGEST})?\.html$")
_MD = re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.md$")
_MANIFEST = re.compile(rf"^advisory_report_{_DATE}-(?P<cadence>daily|weekly|monthly)(?:\.variant-{_DIGEST})?\.json\.manifest\.json$")


class VNextIdentityError(ValueError):
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


def _period(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError):
        raise _error("period_mismatch") from None


def _name(value: object, pattern: re.Pattern[str], *, as_of: str, cadence: str, suffix: str | None) -> str:
    value = _exact(value, str, "invalid_target_name")
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise _error("invalid_target_name")
    match = pattern.fullmatch(value)
    if match is None or match.group("as_of") != as_of or match.group("cadence") != cadence:
        raise _error("target_name_mismatch")
    if match.groupdict().get("digest") != suffix:
        raise _error("target_digest_mismatch")
    return value


def _semantic_digest(snapshot: Mapping[str, Any]) -> str:
    ignored = {"as_of", "generated_at", "reference_time", "expires_at", "schema_version", "contract_version", "source_artifacts"}
    normalized = {key: value for key, value in snapshot.items() if key not in ignored}
    freshness = normalized.get("freshness")
    if isinstance(freshness, dict):
        normalized["freshness"] = {
            name: {key: entry[key] for key in ("present", "valid", "reason") if key in entry}
            for name, entry in freshness.items() if isinstance(entry, dict)
        }
    elif "freshness" not in normalized:
        normalized["freshness"] = {
            "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
            "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
        }
    summary = normalized.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("data_quality_warnings"), list):
        summary = dict(summary)
        summary["data_quality_warnings"] = [
            item for item in summary["data_quality_warnings"]
            if not (isinstance(item, str) and item.startswith(("compatibility:", "compatibility_", "schema_compatibility:", "schema_compatibility_")))
        ]
        normalized["summary"] = summary
    try:
        return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("report_invalid") from None


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
    namespace: str = VNEXT_WIRE_NAMESPACE

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != VNEXT_SCHEMA_VERSION or self.namespace != VNEXT_WIRE_NAMESPACE:
            raise _error("unsupported_index_version")
        if type(self.bindings) is not tuple or not all(isinstance(item, VNextIdentityBinding) for item in self.bindings):
            raise _error("identity_index_invalid")
        _validate_index(self.bindings)


def _validate_binding(binding: VNextIdentityBinding) -> None:
    if not isinstance(binding, VNextIdentityBinding):
        raise _error("identity_binding_invalid")
    for value in (binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version, binding.contract_version,
                  binding.semantic_fingerprint_version, binding.semantic_digest, binding.artifact_integrity_version,
                  binding.artifact_integrity_digest, binding.json_name, binding.html_name, binding.identity_class, binding.status):
        if type(value) is not str or not value:
            raise _error("identity_binding_invalid")
    expected_period = _period(binding.as_of, binding.cadence)
    if binding.period_key != expected_period:
        raise _error("period_mismatch")
    if binding.report_schema_version not in {"5", "6"}:
        raise _error("unsupported_report_schema")
    try:
        expected_contract = contract_version_for_schema(binding.report_schema_version)
    except (TimeContractError, TypeError, ValueError):
        raise _error("unsupported_report_schema") from None
    if binding.contract_version != expected_contract:
        raise _error("contract_version_mismatch")
    if binding.semantic_fingerprint_version != SEMANTIC_FINGERPRINT_VERSION:
        raise _error("unsupported_semantic_algorithm")
    if binding.artifact_integrity_version != ARTIFACT_ALGORITHM_VERSION:
        raise _error("unsupported_artifact_algorithm")
    _digest(binding.semantic_digest, "invalid_semantic_digest")
    _digest(binding.artifact_integrity_digest, "invalid_artifact_digest")
    if binding.identity_class not in {V3_CANONICAL, V3_VARIANT}:
        raise _error("unsupported_identity_class")
    if type(binding.canonical_identity) is not bool or type(binding.display_primary) is not bool:
        raise _error("identity_boolean_invalid")
    if (binding.identity_class == V3_CANONICAL) != binding.canonical_identity:
        raise _error("identity_class_mismatch")
    if type(binding.display_order) is not int or type(binding.display_order) is bool or not 0 <= binding.display_order <= MAX_SAFE_JSON_INTEGER:
        raise _error("display_order_invalid")
    if binding.status != VNEXT_STATUS:
        raise _error("identity_status_invalid")
    suffix = None if binding.identity_class == V3_CANONICAL else binding.artifact_integrity_digest
    _name(binding.json_name, _JSON, as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    _name(binding.html_name, _HTML, as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    if binding.markdown_name is not None:
        _name(binding.markdown_name, _MD, as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)
    if binding.manifest_name is not None:
        _name(binding.manifest_name, _MANIFEST, as_of=binding.as_of, cadence=binding.cadence, suffix=suffix)


def _validate_index(bindings: tuple[VNextIdentityBinding, ...]) -> None:
    seen_names: dict[str, tuple[str, str]] = {}
    seen_identities: set[tuple[str, str, str, str | None, str | None]] = set()
    canonical_by_period: set[str] = set()
    display_by_period: dict[str, tuple[bool, set[int]]] = {}
    artifact_digests: dict[str, tuple[str, str, str]] = {}
    artifact_identities: set[tuple[str, str, str, str, str, str, str]] = set()
    for binding in bindings:
        _validate_binding(binding)
        artifact_identity = (
            binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
            binding.contract_version, binding.semantic_digest, binding.artifact_integrity_digest,
        )
        if artifact_identity in artifact_identities:
            raise _error("identity_duplicate")
        artifact_identities.add(artifact_identity)
        identity = (binding.period_key, binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name)
        if binding.canonical_identity:
            if binding.period_key in canonical_by_period:
                raise _error("canonical_conflict")
            canonical_by_period.add(binding.period_key)
        if identity in seen_identities:
            raise _error("identity_duplicate")
        seen_identities.add(identity)
        primary, orders = display_by_period.setdefault(binding.period_key, (False, set()))
        if binding.display_primary and primary:
            raise _error("display_primary_conflict")
        if binding.display_order in orders:
            raise _error("display_order_conflict")
        display_by_period[binding.period_key] = (primary or binding.display_primary, orders | {binding.display_order})
        for name in (binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name):
            if name is None:
                continue
            owner = (binding.period_key, binding.artifact_integrity_digest)
            if name in seen_names and seen_names[name] != owner:
                raise _error("target_collision")
            seen_names[name] = owner
        previous = artifact_digests.get(binding.artifact_integrity_digest)
        current = (binding.period_key, binding.as_of, binding.cadence)
        if previous is not None and previous != current:
            raise _error("artifact_digest_conflict")
        artifact_digests[binding.artifact_integrity_digest] = current
    periods = {binding.period_key for binding in bindings}
    if periods - canonical_by_period:
        raise _error("canonical_missing")


def _snapshot(payload: Mapping[str, Any]) -> dict[str, object]:
    try:
        return snapshot_json_wire(payload)
    except (ArtifactIntegrityError, TypeError, ValueError, UnicodeError, RecursionError):
        raise _error("invalid_wire") from None


def _entry_from_wire(entry: object) -> VNextIdentityBinding:
    required = {"binding_namespace", "period_key", "as_of", "cadence", "report_schema_version", "contract_version",
                "semantic_fingerprint_version", "semantic_digest", "artifact_integrity_version", "artifact_integrity_digest",
                "json", "html", "identity_class", "canonical_identity", "display_primary", "display_order", "status"}
    optional = {"md", "manifest"}
    if type(entry) is not dict or not required.issubset(entry) or set(entry) - required - optional:
        raise _error("invalid_entry")
    if entry.get("binding_namespace") != VNEXT_BINDING_NAMESPACE:
        raise _error("unsupported_binding_namespace")
    try:
        if "md" in entry and type(entry["md"]) is not str:
            raise _error("invalid_target_name")
        if "manifest" in entry and type(entry["manifest"]) is not str:
            raise _error("invalid_target_name")
        return VNextIdentityBinding(
            entry["period_key"], entry["as_of"], entry["cadence"], entry["report_schema_version"], entry["contract_version"],
            entry["semantic_fingerprint_version"], entry["semantic_digest"], entry["artifact_integrity_version"],
            entry["artifact_integrity_digest"], entry["json"], entry["html"], entry.get("md"), entry.get("manifest"),
            entry["identity_class"], entry["canonical_identity"], entry["display_primary"], entry["display_order"], entry["status"],
        )
    except VNextIdentityError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("invalid_entry") from None


def parse_vnext_index(payload: Mapping[str, Any]) -> VNextIdentityIndex:
    snapshot = _snapshot(payload)
    if set(snapshot) != {"schema_version", "namespace", "reports"}:
        raise _error("invalid_wire")
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != VNEXT_SCHEMA_VERSION:
        raise _error("unsupported_index_version")
    if type(snapshot["namespace"]) is not str or snapshot["namespace"] != VNEXT_WIRE_NAMESPACE:
        raise _error("unsupported_namespace")
    if type(snapshot["reports"]) is not list:
        raise _error("invalid_wire")
    try:
        bindings = tuple(sorted((_entry_from_wire(item) for item in snapshot["reports"]), key=_binding_sort_key))
        return VNextIdentityIndex(bindings)
    except VNextIdentityError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("invalid_wire") from None


def _binding_sort_key(binding: VNextIdentityBinding) -> tuple[object, ...]:
    return (
        binding.period_key,
        not binding.canonical_identity,
        binding.artifact_integrity_digest,
        binding.semantic_digest,
        binding.as_of,
        binding.cadence,
        binding.json_name,
        binding.html_name,
        binding.markdown_name or "",
        binding.manifest_name or "",
    )


def _binding_wire(binding: VNextIdentityBinding) -> dict[str, object]:
    _validate_binding(binding)
    result = {
        "binding_namespace": VNEXT_BINDING_NAMESPACE, "period_key": binding.period_key, "as_of": binding.as_of,
        "cadence": binding.cadence, "report_schema_version": binding.report_schema_version,
        "contract_version": binding.contract_version, "semantic_fingerprint_version": binding.semantic_fingerprint_version,
        "semantic_digest": binding.semantic_digest, "artifact_integrity_version": binding.artifact_integrity_version,
        "artifact_integrity_digest": binding.artifact_integrity_digest, "json": binding.json_name, "html": binding.html_name,
        "identity_class": binding.identity_class, "canonical_identity": binding.canonical_identity,
        "display_primary": binding.display_primary, "display_order": binding.display_order, "status": binding.status,
    }
    if binding.markdown_name is not None:
        result["md"] = binding.markdown_name
    if binding.manifest_name is not None:
        result["manifest"] = binding.manifest_name
    return result


def serialize_vnext_index(index: VNextIdentityIndex) -> dict[str, object]:
    if not isinstance(index, VNextIdentityIndex):
        raise _error("identity_index_invalid")
    _validate_index(index.bindings)
    bindings = tuple(sorted(index.bindings, key=_binding_sort_key))
    payload = {"schema_version": VNEXT_SCHEMA_VERSION, "namespace": VNEXT_WIRE_NAMESPACE,
               "reports": [_binding_wire(binding) for binding in bindings]}
    parse_vnext_index(payload)
    return payload


def report_identity_evidence(report: Mapping[str, Any]) -> tuple[dict[str, object], str, str, str, str, str, str, str]:
    try:
        snapshot = snapshot_json_wire(report)
        validate_advisory_report(snapshot)
        schema = snapshot["schema_version"]
        as_of = snapshot["as_of"]
        cadence = snapshot["cadence"]
        if not all(type(value) is str for value in (schema, as_of, cadence)):
            raise _error("report_invalid")
        contract = contract_version_for_schema(schema)
        period = _period(as_of, cadence)
        semantic = _semantic_digest(snapshot)
        artifact = make_artifact_integrity_evidence(snapshot)
        return snapshot, period, as_of, cadence, schema, contract, semantic, artifact.digest
    except VNextIdentityError:
        raise
    except (AdvisoryValidationError, ArtifactIntegrityError, PeriodContractError, TimeContractError,
            AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("report_invalid") from None


__all__ = [
    "ARTIFACT_ALGORITHM_VERSION", "MAX_SAFE_JSON_INTEGER", "SEMANTIC_FINGERPRINT_VERSION", "V3_CANONICAL", "V3_VARIANT",
    "VNEXT_BINDING_NAMESPACE", "VNEXT_SCHEMA_VERSION", "VNEXT_STATUS", "VNEXT_WIRE_NAMESPACE", "VNextIdentityBinding",
    "VNextIdentityError", "VNextIdentityIndex", "parse_vnext_index", "report_identity_evidence", "serialize_vnext_index",
]

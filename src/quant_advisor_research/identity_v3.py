"""Pure v3 persistent identity-ledger contract.

This module does not select candidates or compute a display/latest view. A v3
index preserves immutable identities; same-period semantic reruns may coexist
when their artifact identities and public names are internally coherent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from .artifact_integrity import (
    ARTIFACT_INTEGRITY_VERSION,
    ArtifactIntegrityError,
    snapshot_json_wire,
)
from .identity_lifecycle import (
    FINGERPRINT_VERSION,
    IdentityMetadataError,
    V1ProvisionalIndex,
    V2IdentityIndex,
    parse_v1_index,
    parse_v2_index,
)
from .period_contract import PeriodContractError, canonical_period_identity
from .time_contract import TimeContractError, contract_version_for_schema


V3_SCHEMA_VERSION = 3
PENDING_ARTIFACT_VALIDATION = "PENDING_ARTIFACT_VALIDATION"
V3_CANONICAL = "V3_CANONICAL"
V3_VARIANT = "V3_VARIANT"
LEGACY_V2 = "LEGACY_V2"
_IDENTITY_CLASSES = frozenset({V3_CANONICAL, V3_VARIANT, LEGACY_V2})
_DATE = r"(?P<as_of>\d{4}-\d{2}-\d{2})"
_DIGEST = r"(?P<digest>[0-9a-f]{64})"
_JSON_PATTERN = re.compile(rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.json$")
_HTML_PATTERN = re.compile(
    rf"^{_DATE}-(?P<cadence>daily|weekly|monthly)-model-recommendations"
    rf"(?:\.variant-{_DIGEST})?\.html$"
)
_MD_PATTERN = re.compile(rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.md$")
_MANIFEST_PATTERN = re.compile(
    rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.json\.manifest\.json$"
)


@dataclass(frozen=True, slots=True)
class V3IdentityBinding:
    """One pending, structurally validated persistent identity ledger entry."""

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
    status: str = PENDING_ARTIFACT_VALIDATION


@dataclass(frozen=True, slots=True)
class V3IdentityIndex:
    """Persistent immutable identity ledger, not a selected-candidate group."""

    schema_version: int
    bindings: tuple[V3IdentityBinding, ...]


def _error(code: str) -> IdentityMetadataError:
    return IdentityMetadataError(code)


def _require_exact(value: object, expected: type, code: str) -> Any:
    if type(value) is not expected:
        raise _error(code)
    return value


def _period_key(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError):
        raise _error("period_mismatch") from None


def _basename_digest(name: object, pattern: re.Pattern[str], *, as_of: str, cadence: str | None = None) -> str | None:
    if type(name) is not str or not name or "/" in name or "\\" in name:
        raise _error("invalid_identity_name")
    match = pattern.fullmatch(name)
    if match is None or match.group("as_of") != as_of:
        raise _error("identity_name_mismatch")
    if cadence is not None and match.groupdict().get("cadence") != cadence:
        raise _error("identity_name_mismatch")
    return match.groupdict().get("digest")


def _validate_digest(value: object, code: str) -> str:
    value = _require_exact(value, str, code)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise _error(code)
    return value


def _validate_v3_entry(entry: object) -> V3IdentityBinding:
    required = {
        "period_key", "as_of", "cadence", "report_schema_version", "contract_version",
        "semantic_fingerprint_version", "semantic_digest", "artifact_integrity_version",
        "artifact_integrity_digest", "json", "html", "identity_class", "canonical_identity",
        "display_primary", "display_order",
    }
    optional = {"md", "manifest"}
    if type(entry) is not dict or not required.issubset(entry) or set(entry) - required - optional:
        raise _error("invalid_v3_entry")

    as_of = _require_exact(entry["as_of"], str, "invalid_as_of")
    cadence = _require_exact(entry["cadence"], str, "invalid_cadence")
    period_key = _period_key(as_of, cadence)
    if _require_exact(entry["period_key"], str, "period_mismatch") != period_key:
        raise _error("period_mismatch")
    report_schema_version = _require_exact(entry["report_schema_version"], str, "invalid_schema_version")
    if report_schema_version not in {"5", "6"}:
        raise _error("invalid_schema_version")
    contract_version = _require_exact(entry["contract_version"], str, "invalid_contract_version")
    try:
        expected_contract = contract_version_for_schema(report_schema_version)
    except (TimeContractError, TypeError, ValueError):
        raise _error("invalid_schema_version") from None
    if contract_version != expected_contract:
        raise _error("contract_version_mismatch")
    semantic_fingerprint_version = _require_exact(
        entry["semantic_fingerprint_version"], str, "invalid_fingerprint_version"
    )
    if semantic_fingerprint_version != FINGERPRINT_VERSION:
        raise _error("invalid_fingerprint_version")
    semantic_digest = _validate_digest(entry["semantic_digest"], "invalid_semantic_digest")
    artifact_integrity_version = _require_exact(
        entry["artifact_integrity_version"], str, "invalid_artifact_integrity_version"
    )
    if artifact_integrity_version != ARTIFACT_INTEGRITY_VERSION:
        raise _error("invalid_artifact_integrity_version")
    artifact_integrity_digest = _validate_digest(
        entry["artifact_integrity_digest"], "invalid_artifact_integrity_digest"
    )
    identity_class = _require_exact(entry["identity_class"], str, "invalid_identity_class")
    if identity_class not in _IDENTITY_CLASSES:
        raise _error("invalid_identity_class")
    canonical_identity = _require_exact(entry["canonical_identity"], bool, "invalid_boolean")
    display_primary = _require_exact(entry["display_primary"], bool, "invalid_boolean")
    display_order = _require_exact(entry["display_order"], int, "invalid_display_order")
    if display_order < 0:
        raise _error("invalid_display_order")
    if identity_class == V3_CANONICAL and canonical_identity is not True:
        raise _error("identity_metadata_mismatch")
    if identity_class == V3_VARIANT and canonical_identity is not False:
        raise _error("identity_metadata_mismatch")
    if identity_class == LEGACY_V2 and canonical_identity not in {True, False}:
        raise _error("identity_metadata_mismatch")

    json_name = _require_exact(entry["json"], str, "invalid_identity_name")
    html_name = _require_exact(entry["html"], str, "invalid_identity_name")
    md_name = None if "md" not in entry else _require_exact(entry["md"], str, "invalid_identity_name")
    manifest_name = None if "manifest" not in entry else _require_exact(
        entry["manifest"], str, "invalid_identity_name"
    )
    names = [
        (_basename_digest(json_name, _JSON_PATTERN, as_of=as_of), json_name),
        (_basename_digest(html_name, _HTML_PATTERN, as_of=as_of, cadence=cadence), html_name),
    ]
    if md_name is not None:
        names.append((_basename_digest(md_name, _MD_PATTERN, as_of=as_of), md_name))
    if manifest_name is not None:
        names.append((_basename_digest(manifest_name, _MANIFEST_PATTERN, as_of=as_of), manifest_name))
    expected_html = f"{as_of}-{cadence}-model-recommendations.html"
    if html_name != expected_html and names[1][0] is None:
        raise _error("identity_name_mismatch")

    if identity_class == V3_CANONICAL or (identity_class == LEGACY_V2 and canonical_identity):
        expected_suffix = None
    elif identity_class == V3_VARIANT:
        expected_suffix = artifact_integrity_digest
    else:
        expected_suffix = semantic_digest
    if any(name_digest != expected_suffix for name_digest, _name in names):
        raise _error("identity_digest_mismatch")

    return V3IdentityBinding(
        period_key, as_of, cadence, report_schema_version, contract_version,
        semantic_fingerprint_version, semantic_digest, artifact_integrity_version,
        artifact_integrity_digest, json_name, html_name, md_name, manifest_name,
        identity_class, canonical_identity, display_primary, display_order,
    )


def _validate_v3_index(bindings: tuple[V3IdentityBinding, ...]) -> None:
    identity_map: set[tuple[str, tuple[str, str, str | None, str | None]]] = set()
    artifact_names: dict[str, tuple[str, tuple[str, str, str | None, str | None]]] = {}
    integrity_map: dict[tuple[str, str], tuple[object, ...]] = {}
    canonical_periods: set[str] = set()
    for binding in bindings:
        identity = (binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name)
        identity_key = (binding.period_key, identity)
        if identity_key in identity_map:
            raise _error("identity_content_conflict")
        identity_map.add(identity_key)
        if binding.canonical_identity:
            if binding.period_key in canonical_periods:
                raise _error("identity_canonical_conflict")
            canonical_periods.add(binding.period_key)
        logical = (binding.period_key, identity)
        for name in identity:
            if name is None:
                continue
            previous = artifact_names.get(name)
            if previous is not None and previous != logical:
                raise _error("identity_artifact_conflict")
            artifact_names[name] = logical
        integrity_key = (binding.artifact_integrity_version, binding.artifact_integrity_digest)
        integrity_metadata = (
            binding.period_key, binding.as_of, binding.cadence, binding.report_schema_version,
            binding.contract_version, binding.semantic_fingerprint_version, binding.semantic_digest, identity,
        )
        previous_integrity = integrity_map.get(integrity_key)
        if previous_integrity is not None and previous_integrity != integrity_metadata:
            raise _error("identity_integrity_conflict")
        integrity_map[integrity_key] = integrity_metadata
    periods = {binding.period_key for binding in bindings}
    if periods - canonical_periods:
        raise _error("identity_canonical_missing")


def _snapshot_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise _error("invalid_reports_index")
    try:
        return snapshot_json_wire(payload)
    except ArtifactIntegrityError:
        raise _error("invalid_reports_index") from None


def _parse_v3_snapshot(payload: dict[str, object]) -> V3IdentityIndex:
    if set(payload) != {"schema_version", "reports"}:
        raise _error("invalid_reports_index")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != V3_SCHEMA_VERSION:
        raise _error("unsupported_index_version")
    reports = payload["reports"]
    if type(reports) is not list:
        raise _error("invalid_reports_index")
    try:
        bindings = tuple(_validate_v3_entry(entry) for entry in reports)
        _validate_v3_index(bindings)
    except IdentityMetadataError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("invalid_v3_entry") from None
    return V3IdentityIndex(V3_SCHEMA_VERSION, bindings)


def parse_v3_index(payload: Mapping[str, Any]) -> V3IdentityIndex:
    """Parse a complete v3 ledger without applying selection or display policy."""

    return _parse_v3_snapshot(_snapshot_payload(payload))


def parse_identity_index(payload: Mapping[str, Any]) -> V1ProvisionalIndex | V2IdentityIndex | V3IdentityIndex:
    snapshot = _snapshot_payload(payload)
    schema_version = snapshot.get("schema_version")
    if type(schema_version) is not int:
        raise _error("invalid_reports_index")
    if schema_version == 1:
        try:
            return parse_v1_index(snapshot)
        except IdentityMetadataError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
            raise _error("invalid_reports_index") from None
    if schema_version == 2:
        try:
            return parse_v2_index(snapshot)
        except IdentityMetadataError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
            raise _error("invalid_reports_index") from None
    if schema_version == V3_SCHEMA_VERSION:
        return _parse_v3_snapshot(snapshot)
    raise _error("unsupported_index_version")

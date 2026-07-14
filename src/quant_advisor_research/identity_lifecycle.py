from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .period_contract import PeriodContractError, canonical_period_identity


FINGERPRINT_VERSION = "semantic_fingerprint.v1.sha256"

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


class IdentityMetadataError(ValueError):
    """Stable, sanitized identity lifecycle error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class V1ProvisionalBinding:
    period_key: str
    as_of: str
    cadence: str
    json_name: str
    html_name: str
    status: str = "PROVISIONAL"


@dataclass(frozen=True, slots=True)
class VerifiedReportEvidence:
    period_key: str
    as_of: str
    cadence: str
    schema_version: str
    fingerprint_version: str
    fingerprint_digest: str
    status: str = "VERIFIED_REPORT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class V2IdentityBinding:
    period_key: str
    as_of: str
    cadence: str
    schema_version: str
    fingerprint_version: str
    fingerprint_digest: str
    json_name: str
    html_name: str
    markdown_name: str | None
    manifest_name: str | None
    canonical_identity: bool
    display_primary: bool
    display_order: int
    status: str = "PENDING_IDENTITY_VALIDATION"


@dataclass(frozen=True, slots=True)
class V1ProvisionalIndex:
    schema_version: int
    bindings: tuple[V1ProvisionalBinding, ...]


@dataclass(frozen=True, slots=True)
class V2IdentityIndex:
    schema_version: int
    bindings: tuple[V2IdentityBinding, ...]


def _error(code: str) -> IdentityMetadataError:
    return IdentityMetadataError(code)


def _require_exact_type(value: object, expected: type, code: str) -> Any:
    if type(value) is not expected:
        raise _error(code)
    return value


def _period_key(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError) as exc:
        raise _error("period_mismatch") from exc


def _is_basename(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "/" not in value and "\\" not in value


def _name_digest(name: str, pattern: re.Pattern[str], *, as_of: str, cadence: str | None = None) -> str | None:
    if not _is_basename(name):
        raise _error("invalid_identity_name")
    match = pattern.fullmatch(name)
    if match is None or match.group("as_of") != as_of:
        raise _error("identity_name_mismatch")
    if cadence is not None and match.groupdict().get("cadence") != cadence:
        raise _error("identity_name_mismatch")
    return match.groupdict().get("digest")


def _validate_v1_entry(entry: object) -> V1ProvisionalBinding:
    if type(entry) is not dict or set(entry) != {"as_of", "cadence", "json", "html"}:
        raise _error("invalid_v1_entry")
    as_of = _require_exact_type(entry["as_of"], str, "invalid_as_of")
    cadence = _require_exact_type(entry["cadence"], str, "invalid_cadence")
    period_key = _period_key(as_of, cadence)
    json_name = _require_exact_type(entry["json"], str, "invalid_identity_name")
    html_name = _require_exact_type(entry["html"], str, "invalid_identity_name")
    if _name_digest(json_name, _JSON_PATTERN, as_of=as_of) is not None:
        raise _error("v1_variant_unverified")
    if _name_digest(html_name, _HTML_PATTERN, as_of=as_of, cadence=cadence) is not None:
        raise _error("v1_variant_unverified")
    if html_name != f"{as_of}-{cadence}-model-recommendations.html":
        raise _error("identity_name_mismatch")
    return V1ProvisionalBinding(period_key, as_of, cadence, json_name, html_name)


def _validate_v2_entry(entry: object) -> V2IdentityBinding:
    required = {
        "period_key", "as_of", "cadence", "schema_version", "fingerprint_version",
        "fingerprint_digest", "json", "html", "canonical_identity", "display_primary", "display_order",
    }
    optional = {"md", "manifest"}
    if type(entry) is not dict or not required.issubset(entry) or set(entry) - required - optional:
        raise _error("invalid_v2_entry")
    as_of = _require_exact_type(entry["as_of"], str, "invalid_as_of")
    cadence = _require_exact_type(entry["cadence"], str, "invalid_cadence")
    period_key = _period_key(as_of, cadence)
    if entry["period_key"] != period_key:
        raise _error("period_mismatch")
    schema_version = _require_exact_type(entry["schema_version"], str, "invalid_schema_version")
    if schema_version not in {"5", "6"}:
        raise _error("invalid_schema_version")
    fingerprint_version = _require_exact_type(entry["fingerprint_version"], str, "invalid_fingerprint_version")
    if fingerprint_version != FINGERPRINT_VERSION:
        raise _error("invalid_fingerprint_version")
    fingerprint_digest = _require_exact_type(entry["fingerprint_digest"], str, "invalid_fingerprint_digest")
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint_digest) is None:
        raise _error("invalid_fingerprint_digest")
    canonical_identity = _require_exact_type(entry["canonical_identity"], bool, "invalid_boolean")
    display_primary = _require_exact_type(entry["display_primary"], bool, "invalid_boolean")
    display_order = _require_exact_type(entry["display_order"], int, "invalid_display_order")
    if display_order < 0:
        raise _error("invalid_display_order")
    json_name = _require_exact_type(entry["json"], str, "invalid_identity_name")
    html_name = _require_exact_type(entry["html"], str, "invalid_identity_name")
    md_name = entry.get("md")
    manifest_name = entry.get("manifest")
    if "md" in entry:
        md_name = _require_exact_type(md_name, str, "invalid_identity_name")
    if "manifest" in entry:
        manifest_name = _require_exact_type(manifest_name, str, "invalid_identity_name")
    json_digest = _name_digest(json_name, _JSON_PATTERN, as_of=as_of)
    html_digest = _name_digest(html_name, _HTML_PATTERN, as_of=as_of, cadence=cadence)
    md_digest = None if md_name is None else _name_digest(md_name, _MD_PATTERN, as_of=as_of)
    manifest_digest = None if manifest_name is None else _name_digest(
        manifest_name, _MANIFEST_PATTERN, as_of=as_of
    )
    expected_html = f"{as_of}-{cadence}-model-recommendations.html"
    if html_name != expected_html and html_digest is None:
        raise _error("identity_name_mismatch")
    if any(digest != json_digest for digest in (html_digest, md_digest, manifest_digest) if digest is not None):
        raise _error("identity_name_mismatch")
    if json_digest is None:
        if canonical_identity is not True:
            raise _error("identity_metadata_mismatch")
    elif json_digest != fingerprint_digest or canonical_identity is not False:
        raise _error("identity_digest_mismatch" if json_digest != fingerprint_digest else "identity_metadata_mismatch")
    return V2IdentityBinding(
        period_key, as_of, cadence, schema_version, fingerprint_version, fingerprint_digest,
        json_name, html_name, md_name, manifest_name, canonical_identity, display_primary, display_order,
    )


def _validate_v1_index(bindings: tuple[V1ProvisionalBinding, ...]) -> None:
    artifact_map: dict[str, tuple[str, str, str, str]] = {}
    identity_map: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        logical = (binding.period_key, binding.json_name, binding.html_name, "v1")
        if logical in identity_map:
            raise _error("identity_artifact_conflict")
        identity_map.add(logical)
        for name in (binding.json_name, binding.html_name):
            previous = artifact_map.get(name)
            if previous is not None and previous != logical:
                raise _error("identity_artifact_conflict")
            artifact_map[name] = logical


def _validate_v2_index(bindings: tuple[V2IdentityBinding, ...]) -> None:
    identity_map: set[tuple[str, tuple[str, str, str | None, str | None]]] = set()
    digest_map: dict[tuple[str, str, str], tuple[str, str, str | None, str | None]] = {}
    artifact_map: dict[str, tuple[str, tuple[str, str, str | None, str | None]]] = {}
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
            previous = artifact_map.get(name)
            if previous is not None and previous != logical:
                raise _error("identity_artifact_conflict")
            artifact_map[name] = logical
        digest_key = (binding.period_key, binding.fingerprint_version, binding.fingerprint_digest)
        previous = digest_map.get(digest_key)
        if previous is not None and previous != identity:
            raise _error("identity_digest_conflict")
        digest_map[digest_key] = identity
    periods = {binding.period_key for binding in bindings}
    if periods - canonical_periods:
        raise _error("identity_canonical_missing")


def parse_v1_index(payload: object) -> V1ProvisionalIndex:
    if type(payload) is not dict or set(payload) != {"schema_version", "reports"}:
        raise _error("invalid_reports_index")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise _error("unsupported_index_version")
    reports = payload["reports"]
    if type(reports) is not list:
        raise _error("invalid_reports_index")
    bindings = tuple(_validate_v1_entry(entry) for entry in reports)
    _validate_v1_index(bindings)
    return V1ProvisionalIndex(1, bindings)


def parse_v2_index(payload: object) -> V2IdentityIndex:
    if type(payload) is not dict or set(payload) != {"schema_version", "reports"}:
        raise _error("invalid_reports_index")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise _error("unsupported_index_version")
    reports = payload["reports"]
    if type(reports) is not list:
        raise _error("invalid_reports_index")
    bindings = tuple(_validate_v2_entry(entry) for entry in reports)
    _validate_v2_index(bindings)
    return V2IdentityIndex(2, bindings)


def make_verified_report_evidence(
    *, as_of: str, cadence: str, schema_version: str, fingerprint_digest: str,
) -> VerifiedReportEvidence:
    period_key = _period_key(as_of, cadence)
    if type(schema_version) is not str or schema_version not in {"5", "6"}:
        raise _error("invalid_schema_version")
    if type(fingerprint_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", fingerprint_digest) is None:
        raise _error("invalid_fingerprint_digest")
    return VerifiedReportEvidence(period_key, as_of, cadence, schema_version, FINGERPRINT_VERSION, fingerprint_digest)

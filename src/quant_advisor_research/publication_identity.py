from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .contracts import AdvisoryValidationError, validate_advisory_report
from .period_contract import PeriodContractError, canonical_period_identity


FINGERPRINT_VERSION = "semantic_fingerprint.v1.sha256"
PENDING_REPORT_VALIDATION = "PENDING_REPORT_VALIDATION"
VERIFIED = "VERIFIED"

_DATE = r"(?P<as_of>\d{4}-\d{2}-\d{2})"
_DIGEST = r"(?P<digest>[0-9a-f]{64})"
_JSON_PATTERN = re.compile(rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.json$")
_HTML_PATTERN = re.compile(
    rf"^{_DATE}-(?P<cadence>daily|weekly|monthly)-model-recommendations"
    rf"(?:\.variant-{_DIGEST})?\.html$"
)
_MD_PATTERN = re.compile(rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.md$")
_MANIFEST_PATTERN = re.compile(rf"^advisory_report_{_DATE}(?:\.variant-{_DIGEST})?\.json\.manifest\.json$")


class IdentityMetadataError(ValueError):
    """Stable, sanitized publication identity metadata error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class IdentityBinding:
    period_key: str
    as_of: str
    cadence: str
    schema_version: str | None
    fingerprint_version: str | None
    fingerprint_digest: str | None
    json_name: str
    html_name: str
    markdown_name: str | None
    manifest_name: str | None
    canonical_identity: bool
    display_primary: bool
    display_order: int | None
    verification_status: str


@dataclass(frozen=True, slots=True)
class RecoveredPublication:
    binding: IdentityBinding
    local_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ReportsIndex:
    schema_version: int
    bindings: tuple[IdentityBinding, ...]


def _error(code: str) -> IdentityMetadataError:
    return IdentityMetadataError(code)


def _is_basename(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "/" not in value and "\\" not in value and Path(value).name == value


def _require_exact_type(value: object, expected: type, code: str) -> Any:
    if type(value) is not expected:
        raise _error(code)
    return value


def _period_key(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError) as exc:
        raise _error("period_mismatch") from exc


def _variant_suffix(names: tuple[str, ...], *, as_of: str) -> str | None:
    suffixes: list[str | None] = []
    for name, pattern in zip(names, (_JSON_PATTERN, _HTML_PATTERN, _MD_PATTERN, _MANIFEST_PATTERN), strict=False):
        if not _is_basename(name):
            raise _error("invalid_identity_name")
        match = pattern.fullmatch(name)
        if match is None or match.group("as_of") != as_of:
            raise _error("identity_name_mismatch")
        suffixes.append(match.groupdict().get("digest"))
    if any(suffix != suffixes[0] for suffix in suffixes[1:]):
        raise _error("identity_name_mismatch")
    return suffixes[0]


def _validated_name_digest(name: str, pattern: re.Pattern[str], *, as_of: str) -> str | None:
    if not _is_basename(name):
        raise _error("invalid_identity_name")
    match = pattern.fullmatch(name)
    if match is None or match.group("as_of") != as_of:
        raise _error("identity_name_mismatch")
    return match.groupdict().get("digest")


def _validate_v1_entry(entry: object) -> IdentityBinding:
    if type(entry) is not dict or set(entry) != {"as_of", "cadence", "json", "html"}:
        raise _error("invalid_v1_entry")
    as_of = _require_exact_type(entry["as_of"], str, "invalid_as_of")
    cadence = _require_exact_type(entry["cadence"], str, "invalid_cadence")
    period_key = _period_key(as_of, cadence)
    json_name = _require_exact_type(entry["json"], str, "invalid_identity_name")
    html_name = _require_exact_type(entry["html"], str, "invalid_identity_name")
    suffix = _variant_suffix((json_name, html_name), as_of=as_of)
    if suffix is not None:
        raise _error("v1_variant_unverified")
    expected_html = f"{as_of}-{cadence}-model-recommendations.html"
    if html_name != expected_html:
        raise _error("identity_name_mismatch")
    return IdentityBinding(
        period_key=period_key,
        as_of=as_of,
        cadence=cadence,
        schema_version=None,
        fingerprint_version=None,
        fingerprint_digest=None,
        json_name=json_name,
        html_name=html_name,
        markdown_name=None,
        manifest_name=None,
        canonical_identity=True,
        display_primary=False,
        display_order=None,
        verification_status=PENDING_REPORT_VALIDATION,
    )


def _validate_v2_entry(entry: object) -> IdentityBinding:
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
    if md_name is not None:
        md_name = _require_exact_type(md_name, str, "invalid_identity_name")
    if manifest_name is not None:
        manifest_name = _require_exact_type(manifest_name, str, "invalid_identity_name")
    suffix = _variant_suffix((json_name, html_name), as_of=as_of)
    if md_name is not None:
        if _validated_name_digest(md_name, _MD_PATTERN, as_of=as_of) != suffix:
            raise _error("identity_name_mismatch")
    if manifest_name is not None:
        if _validated_name_digest(manifest_name, _MANIFEST_PATTERN, as_of=as_of) != suffix:
            raise _error("identity_name_mismatch")
    expected_html = f"{as_of}-{cadence}-model-recommendations.html"
    expected_html = expected_html if suffix is None else expected_html.replace(".html", f".variant-{suffix}.html")
    if html_name != expected_html:
        raise _error("identity_name_mismatch")
    if suffix is None and canonical_identity is not True:
        raise _error("identity_metadata_mismatch")
    if suffix is not None and canonical_identity is not False:
        raise _error("identity_metadata_mismatch")
    return IdentityBinding(
        period_key=period_key,
        as_of=as_of,
        cadence=cadence,
        schema_version=schema_version,
        fingerprint_version=fingerprint_version,
        fingerprint_digest=fingerprint_digest,
        json_name=json_name,
        html_name=html_name,
        markdown_name=md_name,
        manifest_name=manifest_name,
        canonical_identity=canonical_identity,
        display_primary=display_primary,
        display_order=display_order,
        verification_status=PENDING_REPORT_VALIDATION,
    )


def parse_reports_index(payload: object) -> ReportsIndex:
    if type(payload) is not dict or set(payload) != {"schema_version", "reports"}:
        raise _error("invalid_reports_index")
    schema_version = _require_exact_type(payload["schema_version"], int, "invalid_index_version")
    reports = payload["reports"]
    if type(reports) is not list:
        raise _error("invalid_reports_index")
    if schema_version == 1:
        bindings = tuple(_validate_v1_entry(entry) for entry in reports)
    elif schema_version == 2:
        bindings = tuple(_validate_v2_entry(entry) for entry in reports)
    else:
        raise _error("unsupported_index_version")
    identity_map: dict[tuple[str, tuple[str, str, str | None, str | None]], str | None] = {}
    digest_map: dict[tuple[str, str, str], tuple[str, str, str | None, str | None]] = {}
    for binding in bindings:
        identity = (binding.json_name, binding.html_name, binding.markdown_name, binding.manifest_name)
        identity_key = (binding.period_key, identity)
        if identity_key in identity_map and identity_map[identity_key] != binding.fingerprint_digest:
            raise _error("identity_content_conflict")
        identity_map[identity_key] = binding.fingerprint_digest
        if binding.fingerprint_digest is not None:
            digest_key = (binding.period_key, binding.fingerprint_version or "", binding.fingerprint_digest)
            previous = digest_map.get(digest_key)
            if previous is not None and previous != identity:
                raise _error("identity_digest_conflict")
            digest_map[digest_key] = identity
    return ReportsIndex(schema_version=schema_version, bindings=bindings)


def verify_identity_binding(binding: IdentityBinding, report: object) -> IdentityBinding:
    if type(report) is not dict:
        raise _error("report_invalid")
    try:
        validate_advisory_report(report)
    except (AdvisoryValidationError, AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _error("report_invalid") from exc
    if report.get("as_of") != binding.as_of or report.get("cadence") != binding.cadence:
        raise _error("identity_metadata_mismatch")
    if binding.schema_version is not None and report.get("schema_version") != binding.schema_version:
        raise _error("identity_metadata_mismatch")
    if _period_key(binding.as_of, binding.cadence) != binding.period_key:
        raise _error("period_mismatch")
    from .publisher import report_content_fingerprint

    digest = hashlib.sha256(report_content_fingerprint(report).encode("utf-8")).hexdigest()
    if binding.fingerprint_digest is not None and digest != binding.fingerprint_digest:
        raise _error("identity_content_conflict")
    return replace(
        binding,
        schema_version=str(report.get("schema_version")),
        fingerprint_version=FINGERPRINT_VERSION,
        fingerprint_digest=digest,
        verification_status=VERIFIED,
    )


def serialize_reports_index_v2(index: ReportsIndex) -> str:
    if index.schema_version != 2 or any(
        binding.fingerprint_digest is None or binding.verification_status != VERIFIED
        for binding in index.bindings
    ):
        raise _error("v2_serialization_requires_verified_binding")
    reports: list[dict[str, Any]] = []
    ordered = sorted(
        index.bindings,
        key=lambda binding: (
            binding.display_order if binding.display_order is not None else 2**31,
            binding.period_key,
            binding.fingerprint_digest or "",
            binding.json_name,
        ),
    )
    for binding in ordered:
        if (
            binding.schema_version not in {"5", "6"}
            or binding.fingerprint_version != FINGERPRINT_VERSION
            or binding.fingerprint_digest is None
            or type(binding.display_order) is not int
            or type(binding.canonical_identity) is not bool
            or type(binding.display_primary) is not bool
        ):
            raise _error("v2_serialization_invalid_binding")
        item: dict[str, Any] = {
            "period_key": binding.period_key,
            "as_of": binding.as_of,
            "cadence": binding.cadence,
            "schema_version": binding.schema_version,
            "fingerprint_version": binding.fingerprint_version,
            "fingerprint_digest": binding.fingerprint_digest,
            "json": binding.json_name,
            "html": binding.html_name,
            "canonical_identity": binding.canonical_identity,
            "display_primary": binding.display_primary,
            "display_order": binding.display_order,
        }
        if binding.markdown_name is not None:
            item["md"] = binding.markdown_name
        if binding.manifest_name is not None:
            item["manifest"] = binding.manifest_name
        try:
            _validate_v2_entry(item)
        except IdentityMetadataError as exc:
            raise _error("v2_serialization_invalid_binding") from exc
        reports.append(item)
    return json.dumps({"schema_version": 2, "reports": reports}, ensure_ascii=False, indent=2) + "\n"

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import AdvisoryValidationError, validate_advisory_report
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


@dataclass(frozen=True, slots=True)
class VerifiedIdentityEvidence:
    binding: V2IdentityBinding
    report_digest: str


@dataclass(frozen=True, slots=True)
class AllocatedIdentity:
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
    allocation_source: str


@dataclass(frozen=True, slots=True)
class CompleteVerifiedIdentityInventory:
    identities: tuple[VerifiedIdentityEvidence, ...]
    reports: tuple[tuple[str, object], ...]


def _error(code: str) -> IdentityMetadataError:
    return IdentityMetadataError(code)


def _require_exact_type(value: object, expected: type, code: str) -> Any:
    if type(value) is not expected:
        raise _error(code)
    return value


def _period_key(as_of: str, cadence: str) -> str:
    try:
        return canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError):
        raise _error("period_mismatch") from None


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
    declared_digests = [html_digest]
    if md_name is not None:
        declared_digests.append(md_digest)
    if manifest_name is not None:
        declared_digests.append(manifest_digest)
    if any(digest != json_digest for digest in declared_digests):
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
    return VerifiedReportEvidence(
        period_key, as_of, cadence, schema_version, FINGERPRINT_VERSION, fingerprint_digest,
        status="UNTRUSTED_REPORT_EVIDENCE_CANDIDATE",
    )


def _v1_binding_payload(binding: V1ProvisionalBinding) -> dict[str, object]:
    return {
        "as_of": binding.as_of,
        "cadence": binding.cadence,
        "json": binding.json_name,
        "html": binding.html_name,
    }


def _v2_binding_payload(binding: V2IdentityBinding) -> dict[str, object]:
    payload: dict[str, object] = {
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
        payload["md"] = binding.markdown_name
    if binding.manifest_name is not None:
        payload["manifest"] = binding.manifest_name
    return payload


def _compute_report_evidence(report: object, provisional: V1ProvisionalBinding | None = None) -> tuple[str, str, str, str, str]:
    if type(report) is not dict:
        raise _error("report_invalid")
    try:
        validate_advisory_report(report)
        as_of = _require_exact_type(report["as_of"], str, "report_invalid")
        cadence = _require_exact_type(report["cadence"], str, "report_invalid")
        schema_version = _require_exact_type(report["schema_version"], str, "report_invalid")
        if schema_version not in {"5", "6"}:
            raise _error("report_invalid")
        period_key = _period_key(as_of, cadence)
        if provisional is not None:
            if not isinstance(provisional, V1ProvisionalBinding):
                raise _error("identity_metadata_mismatch")
            parsed = _validate_v1_entry(_v1_binding_payload(provisional))
            if parsed != provisional or (parsed.as_of, parsed.cadence) != (as_of, cadence):
                raise _error("identity_metadata_mismatch")
        from .publisher import report_content_fingerprint

        fingerprint = report_content_fingerprint(report)
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    except IdentityMetadataError:
        raise
    except (
        AdvisoryValidationError, AttributeError, KeyError, TypeError, ValueError, OverflowError,
        UnicodeError, RecursionError,
    ):
        raise _error("report_invalid") from None
    return period_key, as_of, cadence, schema_version, digest


def verify_report_evidence(
    report: object,
    *,
    provisional: V1ProvisionalBinding | None = None,
    expected: VerifiedReportEvidence | None = None,
) -> VerifiedReportEvidence:
    period_key, as_of, cadence, schema_version, digest = _compute_report_evidence(report, provisional)
    if expected is not None:
        if not isinstance(expected, VerifiedReportEvidence):
            raise _error("report_evidence_untrusted")
        if (period_key, as_of, cadence, schema_version, digest) != (
            expected.period_key, expected.as_of, expected.cadence, expected.schema_version, expected.fingerprint_digest
        ):
            raise _error("identity_content_conflict")
    return VerifiedReportEvidence(period_key, as_of, cadence, schema_version, FINGERPRINT_VERSION, digest)


def verify_existing_identity(report: object, binding: V2IdentityBinding) -> VerifiedIdentityEvidence:
    if not isinstance(binding, V2IdentityBinding):
        raise _error("identity_evidence_untrusted")
    try:
        validated = _validate_v2_entry(_v2_binding_payload(binding))
    except IdentityMetadataError:
        raise _error("identity_evidence_invalid") from None
    period_key, as_of, cadence, schema_version, digest = _compute_report_evidence(report)
    if (period_key, as_of, cadence, schema_version) != (
        validated.period_key, validated.as_of, validated.cadence, validated.schema_version
    ):
        raise _error("identity_metadata_mismatch")
    if digest != validated.fingerprint_digest:
        raise _error("identity_content_conflict")
    return VerifiedIdentityEvidence(validated, digest)


def make_complete_identity_inventory(
    index: V2IdentityIndex,
    reports: Mapping[str, object],
) -> CompleteVerifiedIdentityInventory:
    if (
        not isinstance(index, V2IdentityIndex)
        or index.schema_version != 2
        or type(index.bindings) is not tuple
        or type(reports) is not dict
    ):
        raise _error("identity_inventory_invalid")
    try:
        bindings = tuple(index.bindings)
        validated_bindings_list: list[V2IdentityBinding] = []
        for binding in bindings:
            if not isinstance(binding, V2IdentityBinding):
                raise _error("identity_inventory_invalid")
            validated_bindings_list.append(_validate_v2_entry(_v2_binding_payload(binding)))
        validated_bindings = tuple(validated_bindings_list)
        if validated_bindings != bindings:
            raise _error("identity_inventory_invalid")
        _validate_v2_index(validated_bindings)
        if any(type(name) is not str for name in reports):
            raise _error("identity_inventory_invalid")
        expected_names = {binding.json_name for binding in validated_bindings}
        if set(reports) != expected_names:
            raise _error("identity_inventory_incomplete")
        identities = tuple(
            verify_existing_identity(reports[binding.json_name], binding)
            for binding in validated_bindings
        )
    except IdentityMetadataError as exc:
        if exc.code == "identity_inventory_incomplete":
            raise
        raise _error("identity_inventory_invalid") from None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise _error("identity_inventory_invalid") from None
    ordered = tuple(sorted(identities, key=lambda item: (
        item.binding.period_key, item.binding.json_name, item.binding.html_name
    )))
    ordered_reports = tuple((name, reports[name]) for name in sorted(reports))
    return CompleteVerifiedIdentityInventory(ordered, ordered_reports)


def _revalidate_inventory(inventory: CompleteVerifiedIdentityInventory) -> tuple[VerifiedIdentityEvidence, ...]:
    if not isinstance(inventory, CompleteVerifiedIdentityInventory):
        raise _error("identity_inventory_required")
    try:
        if type(inventory.identities) is not tuple or type(inventory.reports) is not tuple:
            raise _error("identity_inventory_invalid")
        identities = inventory.identities
        if any(not isinstance(item, VerifiedIdentityEvidence) for item in identities):
            raise _error("identity_inventory_invalid")
        if any(
            type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
            for item in inventory.reports
        ):
            raise _error("identity_inventory_invalid")
        if len({item[0] for item in inventory.reports}) != len(inventory.reports):
            raise _error("identity_inventory_invalid")
        reports = dict(inventory.reports)
        bindings = tuple(item.binding for item in identities)
        validated_bindings = tuple(_validate_v2_entry(_v2_binding_payload(binding)) for binding in bindings)
        if validated_bindings != bindings or set(reports) != {binding.json_name for binding in bindings}:
            raise _error("identity_inventory_invalid")
        _validate_v2_index(validated_bindings)
        revalidated = tuple(
            verify_existing_identity(reports[binding.json_name], binding)
            for binding in validated_bindings
        )
        if revalidated != identities:
            raise _error("identity_inventory_invalid")
        return revalidated
    except (IdentityMetadataError, AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise _error("identity_inventory_invalid") from None


def _new_allocated_identity(evidence: VerifiedReportEvidence, *, canonical: bool, source: str) -> AllocatedIdentity:
    suffix = "" if canonical else f".variant-{evidence.fingerprint_digest}"
    return AllocatedIdentity(
        evidence.period_key, evidence.as_of, evidence.cadence, evidence.schema_version,
        FINGERPRINT_VERSION, evidence.fingerprint_digest,
        f"advisory_report_{evidence.as_of}{suffix}.json",
        f"{evidence.as_of}-{evidence.cadence}-model-recommendations{suffix}.html",
        None, None, canonical, source,
    )


def allocate_identity(
    report: object,
    *,
    inventory: CompleteVerifiedIdentityInventory | None = None,
    existing_identities: object = None,
    current_period_key: str | None = None,
) -> AllocatedIdentity:
    if existing_identities is not None:
        raise _error("identity_inventory_required")
    if inventory is None:
        raise _error("identity_inventory_required")
    if current_period_key is not None and not isinstance(current_period_key, str):
        raise _error("period_mismatch")
    evidence = verify_report_evidence(report)
    identities = _revalidate_inventory(inventory)
    bindings = tuple(item.binding for item in identities)
    try:
        _validate_v2_index(bindings)
    except IdentityMetadataError:
        raise
    same_period_digest = [
        item for item in identities
        if item.binding.period_key == evidence.period_key and item.report_digest == evidence.fingerprint_digest
    ]
    if len(same_period_digest) > 1:
        raise _error("identity_digest_conflict")
    if same_period_digest:
        item = same_period_digest[0]
        binding = item.binding
        exact_key = (evidence.period_key, evidence.as_of, evidence.cadence, evidence.schema_version,
                     evidence.fingerprint_version, evidence.fingerprint_digest)
        binding_key = (binding.period_key, binding.as_of, binding.cadence, binding.schema_version,
                       binding.fingerprint_version, binding.fingerprint_digest)
        if exact_key != binding_key:
            raise _error("identity_metadata_conflict")
        return AllocatedIdentity(
            binding.period_key, binding.as_of, binding.cadence, binding.schema_version,
            binding.fingerprint_version, binding.fingerprint_digest, binding.json_name, binding.html_name,
            binding.markdown_name, binding.manifest_name, binding.canonical_identity, "REUSED_VERIFIED_IDENTITY",
        )
    canonical_exists = any(item.binding.period_key == evidence.period_key and item.binding.canonical_identity for item in identities)
    canonical = current_period_key == evidence.period_key and not canonical_exists
    allocated = _new_allocated_identity(
        evidence, canonical=canonical, source="ALLOCATED_CANONICAL" if canonical else "ALLOCATED_VARIANT"
    )
    existing_names = {
        name
        for item in identities
        for name in (item.binding.json_name, item.binding.html_name, item.binding.markdown_name, item.binding.manifest_name)
        if name is not None
    }
    if any(name in existing_names for name in (allocated.json_name, allocated.html_name)):
        raise _error("identity_artifact_conflict")
    return allocated

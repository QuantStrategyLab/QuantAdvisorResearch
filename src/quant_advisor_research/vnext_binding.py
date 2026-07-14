"""Strict shared validator for the clean-slate vNext identity namespace."""

from __future__ import annotations

import re

from .artifact_integrity import ARTIFACT_INTEGRITY_VERSION
from .identity_lifecycle import FINGERPRINT_VERSION
from .identity_v3 import PENDING_ARTIFACT_VALIDATION, V3_CANONICAL, V3_VARIANT, V3IdentityBinding
from .period_contract import PeriodContractError, canonical_period_identity
from .time_contract import TimeContractError, contract_version_for_schema


class VNextBindingError(ValueError):
    """Stable, sanitized clean-slate binding error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_DATE = r"(?P<as_of>\d{4}-\d{2}-\d{2})"
_DIGEST = r"(?P<digest>[0-9a-f]{64})"
_CADENCE = r"(?P<cadence>daily|weekly|monthly)"
_JSON = re.compile(rf"^advisory_report_{_DATE}-{_CADENCE}(?:\.variant-{_DIGEST})?\.json$")
_HTML = re.compile(rf"^{_DATE}-{_CADENCE}-model-recommendations(?:\.variant-{_DIGEST})?\.html$")
_MD = re.compile(rf"^advisory_report_{_DATE}-{_CADENCE}(?:\.variant-{_DIGEST})?\.md$")
_MANIFEST = re.compile(
    rf"^advisory_report_{_DATE}-{_CADENCE}(?:\.variant-{_DIGEST})?\.json\.manifest\.json$"
)


def _error(code: str) -> VNextBindingError:
    return VNextBindingError(code)


def binding_payload(binding: V3IdentityBinding) -> dict[str, object]:
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


def _name_digest(name: object, pattern: re.Pattern[str], *, as_of: str, cadence: str) -> str | None:
    if type(name) is not str or not name or "/" in name or "\\" in name:
        raise _error("identity_name_invalid")
    match = pattern.fullmatch(name)
    if match is None or match.group("as_of") != as_of or match.group("cadence") != cadence:
        raise _error("identity_name_mismatch")
    return match.groupdict().get("digest")


def validate_vnext_binding(entry: object) -> V3IdentityBinding:
    """Validate a clean wire entry or binding; no legacy compatibility exists."""

    if isinstance(entry, V3IdentityBinding):
        if entry.status != PENDING_ARTIFACT_VALIDATION:
            raise _error("identity_binding_invalid")
        entry = binding_payload(entry)
    required = {
        "period_key", "as_of", "cadence", "report_schema_version", "contract_version",
        "semantic_fingerprint_version", "semantic_digest", "artifact_integrity_version",
        "artifact_integrity_digest", "json", "html", "identity_class", "canonical_identity",
        "display_primary", "display_order",
    }
    optional = {"md", "manifest"}
    if type(entry) is not dict or not required.issubset(entry) or set(entry) - required - optional:
        raise _error("identity_binding_invalid")
    as_of = entry["as_of"]
    cadence = entry["cadence"]
    if type(as_of) is not str or type(cadence) is not str:
        raise _error("identity_binding_invalid")
    try:
        period_key = canonical_period_identity(cadence, as_of).key
    except (PeriodContractError, TypeError, ValueError, OverflowError):
        raise _error("period_mismatch") from None
    if type(entry["period_key"]) is not str or entry["period_key"] != period_key:
        raise _error("period_mismatch")

    schema = entry["report_schema_version"]
    contract = entry["contract_version"]
    if type(schema) is not str:
        raise _error("invalid_schema_version")
    if type(contract) is not str:
        raise _error("invalid_contract_version")
    try:
        expected_contract = contract_version_for_schema(schema)
    except (TimeContractError, TypeError, ValueError):
        raise _error("invalid_schema_version") from None
    if contract != expected_contract:
        raise _error("contract_version_mismatch")

    if entry["semantic_fingerprint_version"] != FINGERPRINT_VERSION:
        raise _error("invalid_fingerprint_version")
    semantic_digest = entry["semantic_digest"]
    if type(semantic_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", semantic_digest) is None:
        raise _error("invalid_semantic_digest")
    if entry["artifact_integrity_version"] != ARTIFACT_INTEGRITY_VERSION:
        raise _error("invalid_artifact_integrity_version")
    artifact_digest = entry["artifact_integrity_digest"]
    if type(artifact_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", artifact_digest) is None:
        raise _error("invalid_artifact_integrity_digest")

    identity_class = entry["identity_class"]
    if type(identity_class) is not str or identity_class not in {V3_CANONICAL, V3_VARIANT}:
        raise _error("legacy_identity_rejected" if identity_class == "LEGACY_V2" else "invalid_identity_class")
    canonical = entry["canonical_identity"]
    primary = entry["display_primary"]
    order = entry["display_order"]
    if type(canonical) is not bool or type(primary) is not bool or type(order) is not int or order < 0:
        raise _error("identity_binding_invalid")
    if (identity_class == V3_CANONICAL) != canonical:
        raise _error("identity_metadata_mismatch")

    names = [
        (_name_digest(entry["json"], _JSON, as_of=as_of, cadence=cadence), entry["json"]),
        (_name_digest(entry["html"], _HTML, as_of=as_of, cadence=cadence), entry["html"]),
    ]
    if "md" in entry and type(entry["md"]) is not str:
        raise _error("identity_name_invalid")
    if "manifest" in entry and type(entry["manifest"]) is not str:
        raise _error("identity_name_invalid")
    markdown = entry["md"] if "md" in entry else None
    manifest = entry["manifest"] if "manifest" in entry else None
    if markdown is not None:
        names.append((_name_digest(markdown, _MD, as_of=as_of, cadence=cadence), markdown))
    if manifest is not None:
        names.append((_name_digest(manifest, _MANIFEST, as_of=as_of, cadence=cadence), manifest))
    expected_suffix = None if canonical else artifact_digest
    if any(name_digest != expected_suffix for name_digest, _name in names):
        raise _error("identity_digest_mismatch")
    return V3IdentityBinding(
        period_key, as_of, cadence, schema, contract, FINGERPRINT_VERSION, semantic_digest,
        ARTIFACT_INTEGRITY_VERSION, artifact_digest, entry["json"], entry["html"], markdown, manifest,
        identity_class, canonical, primary, order, PENDING_ARTIFACT_VALIDATION,
    )


__all__ = ["VNextBindingError", "binding_payload", "validate_vnext_binding"]

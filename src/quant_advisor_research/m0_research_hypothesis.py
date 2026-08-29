"""Closed M0 research-only hypotheses derived from advisory reports.

This module is deliberately a one-way adapter.  It accepts a validated public
advisory report and emits small, immutable research leads.  The output is not
an allocation, strategy-selection, platform-routing, or execution contract.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .artifact_integrity import artifact_integrity_digest, snapshot_json_wire
from .contracts import (
    ALLOWED_HORIZONS,
    ALLOWED_SOURCE_CONFIDENCE,
    ALLOWED_STRATEGY_STYLES,
    AdvisoryValidationError,
    SOURCE_PROJECT,
    validate_advisory_report,
)
from .time_contract import REPORT_EXPIRY_DAYS, TimeContractError, contract_version_for_schema, normalize_aware_datetime


M0_RESEARCH_HYPOTHESIS_SCHEMA_VERSION = "qsl.m0_research_hypothesis.v1"
M0_RESEARCH_HYPOTHESIS_ARTIFACT_TYPE = "research_hypothesis"
M0_RESEARCH_AUTHORITY = "research_only"
M0_RESEARCH_NEXT_STEP = "research_validation_only"

_HYPOTHESIS_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "authority",
        "no_order",
        "hypothesis_id",
        "as_of",
        "generated_at",
        "expires_at",
        "subject",
        "research_context",
        "evidence",
        "provenance",
        "permitted_next_step",
    }
)
_SUBJECT_KEYS = frozenset({"kind", "identifier"})
_RESEARCH_CONTEXT_KEYS = frozenset(
    {"state", "primary_horizon", "suitable_horizons", "source_confidence", "source_style", "theme_ids"}
)
_EVIDENCE_KEYS = frozenset({"source_entry_digest", "evidence_ref_count", "risk_note_count"})
_PROVENANCE_KEYS = frozenset(
    {
        "source_project",
        "source_schema_version",
        "source_contract_version",
        "source_report_digest",
        "source_input_digest",
    }
)
_ALLOWED_SUBJECT_KINDS = frozenset({"asset_idea", "theme_context", "strategy_hypothesis", "risk_context"})
_ALLOWED_RESEARCH_STATES = frozenset(
    {"candidate", "source_verification_required", "deferred", "context_only"}
)
_STATE_BY_SOURCE_RATING = {
    "recommend": "candidate",
    "watch": "candidate",
    "verify_source": "source_verification_required",
    "defer": "deferred",
    "monitor": "context_only",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")

# Reject semantic escape hatches at every output level.  This is intentionally
# broader than an allowlist alone: camelCase and punctuation variants are also
# rejected, so a future nested object cannot quietly introduce a routing field.
_FORBIDDEN_FIELD_FRAGMENTS = (
    "account",
    "allocation",
    "broker",
    "canary",
    "credential",
    "execution",
    "live",
    "order",
    "paper",
    "platform",
    "portfolio",
    "position",
    "quantity",
    "route",
    "runtime",
    "secret",
    "share",
    "switch",
    "target",
    "token",
    "trade",
    "weight",
)


class M0ResearchHypothesisValidationError(ValueError):
    """Raised when a M0 research-only hypothesis violates its closed contract."""


def _error(code: str) -> None:
    raise M0ResearchHypothesisValidationError(code)


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(code)
    return value


def _require_sequence(value: Any, code: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _error(code)
    return value


def _require_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(code)
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], code: str) -> None:
    if set(value) != expected:
        _error(code)


def _normalized_field_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _reject_forbidden_semantic_fields(value: Any, *, is_root: bool = True) -> None:
    """Fail closed on prohibited keys, including nested camelCase variants."""

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                _error("field_name_invalid")
            normalized = _normalized_field_name(key)
            is_explicit_no_order = is_root and key == "no_order"
            if not is_explicit_no_order and any(fragment in normalized for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
                _error("forbidden_semantic_field")
            _reject_forbidden_semantic_fields(nested_value, is_root=False)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_forbidden_semantic_fields(item, is_root=False)


def _canonical_json_digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8",
            errors="strict",
        )
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        _error("source_entry_not_canonicalizable")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_datetime(value: str, code: str) -> dt.datetime:
    try:
        return normalize_aware_datetime(value)
    except (TimeContractError, TypeError, ValueError) as exc:
        raise M0ResearchHypothesisValidationError(code) from exc


def _iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _validate_sha256(value: Any, code: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _error(code)


def validate_m0_research_hypothesis(payload: Mapping[str, Any]) -> None:
    """Validate one closed, non-executable M0 research hypothesis."""

    item = _require_mapping(payload, "hypothesis_not_object")
    _reject_forbidden_semantic_fields(item)
    _require_exact_keys(item, _HYPOTHESIS_KEYS, "hypothesis_keys_invalid")
    if item.get("schema_version") != M0_RESEARCH_HYPOTHESIS_SCHEMA_VERSION:
        _error("schema_version_invalid")
    if item.get("artifact_type") != M0_RESEARCH_HYPOTHESIS_ARTIFACT_TYPE:
        _error("artifact_type_invalid")
    if item.get("authority") != M0_RESEARCH_AUTHORITY:
        _error("authority_invalid")
    if item.get("no_order") is not True:
        _error("no_order_invalid")
    if item.get("permitted_next_step") != M0_RESEARCH_NEXT_STEP:
        _error("permitted_next_step_invalid")

    hypothesis_id = _require_string(item.get("hypothesis_id"), "hypothesis_id_invalid")
    if not _IDENTIFIER_RE.fullmatch(hypothesis_id):
        _error("hypothesis_id_invalid")
    as_of = _require_string(item.get("as_of"), "as_of_invalid")
    try:
        dt.date.fromisoformat(as_of)
    except ValueError as exc:
        raise M0ResearchHypothesisValidationError("as_of_invalid") from exc
    generated_at = _canonical_datetime(
        _require_string(item.get("generated_at"), "generated_at_invalid"),
        "generated_at_invalid",
    )
    expires_at = _canonical_datetime(
        _require_string(item.get("expires_at"), "expires_at_invalid"),
        "expires_at_invalid",
    )
    if expires_at != generated_at + dt.timedelta(days=REPORT_EXPIRY_DAYS):
        _error("expires_at_invalid")

    subject = _require_mapping(item.get("subject"), "subject_invalid")
    _require_exact_keys(subject, _SUBJECT_KEYS, "subject_keys_invalid")
    if subject.get("kind") not in _ALLOWED_SUBJECT_KINDS:
        _error("subject_kind_invalid")
    identifier = _require_string(subject.get("identifier"), "subject_identifier_invalid")
    if not _IDENTIFIER_RE.fullmatch(identifier):
        _error("subject_identifier_invalid")

    context = _require_mapping(item.get("research_context"), "research_context_invalid")
    _require_exact_keys(context, _RESEARCH_CONTEXT_KEYS, "research_context_keys_invalid")
    if context.get("state") not in _ALLOWED_RESEARCH_STATES:
        _error("research_state_invalid")
    primary_horizon = context.get("primary_horizon")
    if primary_horizon not in ALLOWED_HORIZONS:
        _error("primary_horizon_invalid")
    suitable_horizons = _require_sequence(context.get("suitable_horizons"), "suitable_horizons_invalid")
    if not suitable_horizons or len(suitable_horizons) > len(ALLOWED_HORIZONS):
        _error("suitable_horizons_invalid")
    if any(horizon not in ALLOWED_HORIZONS for horizon in suitable_horizons):
        _error("suitable_horizons_invalid")
    if len(set(suitable_horizons)) != len(suitable_horizons) or primary_horizon not in suitable_horizons:
        _error("suitable_horizons_invalid")
    if context.get("source_confidence") not in ALLOWED_SOURCE_CONFIDENCE:
        _error("source_confidence_invalid")
    if context.get("source_style") not in ALLOWED_STRATEGY_STYLES:
        _error("source_style_invalid")
    theme_ids = _require_sequence(context.get("theme_ids"), "theme_ids_invalid")
    if len(theme_ids) > 24:
        _error("theme_ids_invalid")
    for theme_id in theme_ids:
        if not isinstance(theme_id, str) or not _IDENTIFIER_RE.fullmatch(theme_id):
            _error("theme_ids_invalid")

    evidence = _require_mapping(item.get("evidence"), "evidence_invalid")
    _require_exact_keys(evidence, _EVIDENCE_KEYS, "evidence_keys_invalid")
    _validate_sha256(evidence.get("source_entry_digest"), "source_entry_digest_invalid")
    for key in ("evidence_ref_count", "risk_note_count"):
        value = evidence.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _error(f"{key}_invalid")

    provenance = _require_mapping(item.get("provenance"), "provenance_invalid")
    _require_exact_keys(provenance, _PROVENANCE_KEYS, "provenance_keys_invalid")
    if provenance.get("source_project") != SOURCE_PROJECT:
        _error("source_project_invalid")
    source_schema_version = provenance.get("source_schema_version")
    if source_schema_version not in {"5", "6"}:
        _error("source_schema_version_invalid")
    try:
        expected_contract = contract_version_for_schema(source_schema_version)
    except TimeContractError as exc:
        raise M0ResearchHypothesisValidationError("source_contract_version_invalid") from exc
    if provenance.get("source_contract_version") != expected_contract:
        _error("source_contract_version_invalid")
    _validate_sha256(provenance.get("source_report_digest"), "source_report_digest_invalid")
    _validate_sha256(
        provenance.get("source_input_digest"),
        "source_input_digest_invalid",
        allow_none=source_schema_version == "5",
    )
    if source_schema_version == "5" and provenance.get("source_input_digest") is not None:
        _error("source_input_digest_invalid")


def _source_theme_ids(recommendation: Mapping[str, Any]) -> list[str]:
    context = recommendation.get("ai_context")
    raw_theme_ids = context.get("theme_ids") if isinstance(context, Mapping) else []
    if not isinstance(raw_theme_ids, Sequence) or isinstance(raw_theme_ids, (str, bytes)):
        return []
    result: list[str] = []
    for theme_id in raw_theme_ids:
        if isinstance(theme_id, str) and _IDENTIFIER_RE.fullmatch(theme_id) and theme_id not in result:
            result.append(theme_id)
    return result[:24]


def _source_suitable_horizons(recommendation: Mapping[str, Any]) -> list[str]:
    primary_horizon = recommendation.get("primary_horizon")
    raw_horizons = recommendation.get("suitable_horizons")
    if primary_horizon not in ALLOWED_HORIZONS:
        _error("source_primary_horizon_invalid")
    if not isinstance(raw_horizons, Sequence) or isinstance(raw_horizons, (str, bytes)):
        _error("source_suitable_horizons_invalid")
    result: list[str] = []
    for horizon in raw_horizons:
        if horizon not in ALLOWED_HORIZONS:
            _error("source_suitable_horizons_invalid")
        if horizon not in result:
            result.append(horizon)
    if primary_horizon not in result:
        result.insert(0, primary_horizon)
    return result


def _source_entry_counts(recommendation: Mapping[str, Any]) -> tuple[int, int]:
    def count_list(name: str) -> int:
        value = recommendation.get(name)
        return len(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else 0

    return count_list("evidence_refs"), count_list("risk_notes")


def _hypothesis_id(report_digest: str, identifier: str, entry_digest: str) -> str:
    safe_identifier = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier).strip("-").lower() or "subject"
    return f"m0r-{report_digest[:16]}-{safe_identifier[:48]}-{entry_digest[:16]}"


def adapt_advisory_report_to_m0_hypotheses(report: Mapping[str, Any]) -> list[dict[str, object]]:
    """Return one research-only M0 hypothesis per unique advisory symbol.

    The adapter reads a snapshot so callers cannot modify a validated report
    during conversion.  It intentionally projects a small allowlisted subset;
    all public-report prose, scores, target semantics, and source paths stay
    in the advisory artifact rather than becoming control-plane input.
    """

    try:
        snapshot = snapshot_json_wire(report)
        validate_advisory_report(snapshot)
    except (AdvisoryValidationError, TypeError, ValueError, RecursionError) as exc:
        raise M0ResearchHypothesisValidationError("source_report_invalid") from exc

    source_schema_version = str(snapshot["schema_version"])
    source_contract_version = contract_version_for_schema(source_schema_version)
    source_report_digest = artifact_integrity_digest(snapshot)
    generated_at = _canonical_datetime(str(snapshot["generated_at"]), "source_generated_at_invalid")
    source_expiry = snapshot.get("expires_at") if source_schema_version == "6" else None
    if source_expiry is None:
        expires_at = generated_at + dt.timedelta(days=REPORT_EXPIRY_DAYS)
    else:
        expires_at = _canonical_datetime(str(source_expiry), "source_expires_at_invalid")
    if expires_at != generated_at + dt.timedelta(days=REPORT_EXPIRY_DAYS):
        _error("source_expires_at_invalid")

    source_input_digest = snapshot.get("input_digest") if source_schema_version == "6" else None
    recommendations = snapshot.get("recommendations")
    if not isinstance(recommendations, list):
        _error("source_recommendations_invalid")

    result: list[dict[str, object]] = []
    seen_symbols: set[str] = set()
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            _error("source_recommendation_invalid")
        symbol = recommendation.get("symbol")
        if not isinstance(symbol, str) or not _IDENTIFIER_RE.fullmatch(symbol):
            _error("source_symbol_invalid")
        if symbol in seen_symbols:
            _error("source_symbol_duplicate")
        seen_symbols.add(symbol)
        rating = recommendation.get("rating")
        if rating not in _STATE_BY_SOURCE_RATING:
            _error("source_rating_invalid")

        entry_digest = _canonical_json_digest(recommendation)
        evidence_ref_count, risk_note_count = _source_entry_counts(recommendation)
        hypothesis: dict[str, object] = {
            "schema_version": M0_RESEARCH_HYPOTHESIS_SCHEMA_VERSION,
            "artifact_type": M0_RESEARCH_HYPOTHESIS_ARTIFACT_TYPE,
            "authority": M0_RESEARCH_AUTHORITY,
            "no_order": True,
            "hypothesis_id": _hypothesis_id(source_report_digest, symbol, entry_digest),
            "as_of": snapshot["as_of"],
            "generated_at": _iso_utc(generated_at),
            "expires_at": _iso_utc(expires_at),
            "subject": {"kind": "asset_idea", "identifier": symbol},
            "research_context": {
                "state": _STATE_BY_SOURCE_RATING[rating],
                "primary_horizon": recommendation["primary_horizon"],
                "suitable_horizons": _source_suitable_horizons(recommendation),
                "source_confidence": recommendation["source_confidence"],
                "source_style": recommendation["strategy_style"],
                "theme_ids": _source_theme_ids(recommendation),
            },
            "evidence": {
                "source_entry_digest": entry_digest,
                "evidence_ref_count": evidence_ref_count,
                "risk_note_count": risk_note_count,
            },
            "provenance": {
                "source_project": SOURCE_PROJECT,
                "source_schema_version": source_schema_version,
                "source_contract_version": source_contract_version,
                "source_report_digest": source_report_digest,
                "source_input_digest": source_input_digest,
            },
            "permitted_next_step": M0_RESEARCH_NEXT_STEP,
        }
        validate_m0_research_hypothesis(hypothesis)
        result.append(hypothesis)
    return result

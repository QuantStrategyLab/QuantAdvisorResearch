from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .time_contract import (
    REPORT_EXPIRY_DAYS,
    TimeContractError,
    assess_context_freshness,
    canonical_reference_time,
    contract_version_for_schema,
    context_expiry_instant,
    normalize_aware_datetime,
)


class AdvisoryValidationError(ValueError):
    """Raised when an advisory artifact violates the stable contract."""


ALLOWED_CADENCES = frozenset({"daily", "weekly", "monthly"})
SOURCE_PROJECT = "QuantAdvisorResearch"
REPORT_CONTRACT_VERSION = "model_recommendations.v6"
ALLOWED_RECOMMENDATION_RATINGS = frozenset({"recommend", "watch", "verify_source", "defer", "monitor"})
ALLOWED_RECOMMENDATION_TIERS = frozenset({"tier_1", "tier_2", "watchlist", "source_check", "defer", "monitor"})
ALLOWED_HORIZONS = frozenset({"short", "medium", "long", "not_applicable"})
ALLOWED_FINAL_ACTIONS = frozenset({"recommend", "watch", "skip"})
ALLOWED_SOURCE_CONFIDENCE = frozenset({"high", "medium", "low", "mixed", "no_event", "unknown"})
ALLOWED_STRATEGY_STYLES = frozenset(
    {
        "event_driven",
        "long_horizon_growth",
        "value_quality",
        "macro_context",
        "mixed_research",
    }
)
DISALLOWED_ACCOUNT_ACTION_KEYS = frozenset(
    {
        "account_action",
        "account_actions",
        "account_id",
        "broker",
        "broker_account",
        "broker_id",
        "broker_order",
        "broker_orders",
        "order",
        "orders",
        "order_id",
        "order_intent",
        "order_intents",
        "order_type",
        "shares",
        "target_quantities",
        "target_quantity",
        "target_weight",
        "target_weights",
        "portfolio_weight",
        "entry_order",
        "exit_order",
    }
)


def _normalize_contract_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", snake_case.lower()).strip("_")


def _find_account_action_fields(value: Any, *, path: str = "$") -> tuple[str, ...]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_contract_key(key)
            child_path = f"{path}.{key}"
            if normalized in DISALLOWED_ACCOUNT_ACTION_KEYS:
                findings.append(child_path)
            findings.extend(_find_account_action_fields(item, path=child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            findings.extend(_find_account_action_fields(item, path=f"{path}[{index}]"))
    return tuple(findings)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdvisoryValidationError(f"{name} must be an object")
    return value


def _require_sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AdvisoryValidationError(f"{name} must be a list")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdvisoryValidationError(f"{name} must be a non-empty string")
    return value


def _require_iso_date(value: Any, name: str) -> None:
    text = _require_string(value, name)
    try:
        dt.date.fromisoformat(text)
    except ValueError as exc:
        raise AdvisoryValidationError(f"{name} must be an ISO date") from exc


def _require_iso_datetime(value: Any, name: str) -> None:
    text = _require_string(value, name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AdvisoryValidationError(f"{name} must be an ISO datetime") from exc


def _require_contract_datetime(value: Any, name: str) -> dt.datetime:
    try:
        return normalize_aware_datetime(_require_string(value, name))
    except (TimeContractError, ValueError) as exc:
        raise AdvisoryValidationError(f"{name}_invalid") from exc


def _require_sha256_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AdvisoryValidationError(f"{name}_invalid")
    return value


def _validate_v6_freshness(
    freshness: Any,
    *,
    report_as_of: dt.date,
    reference_time: dt.datetime,
    report_generated_at: dt.datetime,
    source_artifacts: Mapping[str, Any],
) -> None:
    if not isinstance(freshness, Mapping):
        raise AdvisoryValidationError("freshness_invalid")
    if not isinstance(source_artifacts, Mapping):
        raise AdvisoryValidationError("source_artifacts_invalid")
    if set(freshness) != {"ai_signal", "theme_momentum"}:
        raise AdvisoryValidationError("freshness_keys_invalid")
    for name in ("ai_signal", "theme_momentum"):
        item = freshness.get(name)
        if not isinstance(item, Mapping):
            raise AdvisoryValidationError("freshness_entry_invalid")
        base_keys = {"present", "valid", "reason", "as_of", "generated_at", "expires_at"}
        legacy_key = "compatibility_warning"
        if set(item) - base_keys - {legacy_key}:
            raise AdvisoryValidationError("freshness_keys_invalid")
        if type(item.get("present")) is not bool or type(item.get("valid")) is not bool:
            raise AdvisoryValidationError("freshness_status_invalid")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise AdvisoryValidationError("freshness_reason_invalid")
        legacy = reason == "legacy_expiry_compatibility" and item.get("compatibility_warning") == "missing_expires_at"
        if legacy_key in item and not legacy:
            raise AdvisoryValidationError("freshness_keys_invalid")
        declared_artifact = source_artifacts.get(name)
        if declared_artifact is not None and not isinstance(declared_artifact, str):
            raise AdvisoryValidationError("source_artifact_value_invalid")
        declared = isinstance(declared_artifact, str) and bool(declared_artifact.strip())
        if declared != item["present"]:
            raise AdvisoryValidationError("source_artifact_freshness_mismatch")
        if not item["present"]:
            if item["valid"] or any(key in item for key in ("as_of", "generated_at", "expires_at")):
                raise AdvisoryValidationError("freshness_state_incoherent")
            result = assess_context_freshness(
                None,
                report_as_of=report_as_of,
                reference_time=reference_time,
                report_generated_at=report_generated_at,
                max_age_days=REPORT_EXPIRY_DAYS,
            )
        else:
            required = ("as_of", "generated_at") + (() if legacy else ("expires_at",))
            if any(not item.get(key) for key in required):
                raise AdvisoryValidationError("freshness_timestamps_incomplete")
            for key in required:
                if not isinstance(item[key], str):
                    raise AdvisoryValidationError("freshness_timestamp_type_invalid")
            result = assess_context_freshness(
                item,
                report_as_of=report_as_of,
                reference_time=reference_time,
                report_generated_at=report_generated_at,
                max_age_days=REPORT_EXPIRY_DAYS,
                allow_legacy_expiry=True,
            )
        structural_reasons = {
            "missing_as_of", "missing_generated_at", "missing_expires_at",
            "invalid_as_of", "invalid_generated_at", "invalid_expires_at",
        }
        if result.reason in structural_reasons:
            raise AdvisoryValidationError("freshness_assessment_invalid")
        if item["present"] != result.present or item["valid"] != result.valid:
            raise AdvisoryValidationError("freshness_state_incoherent")
        if reason != result.reason:
            raise AdvisoryValidationError("freshness_reason_mismatch")
        if result.as_of is not None and dt.date.fromisoformat(item["as_of"]) != result.as_of:
            raise AdvisoryValidationError("freshness_timestamp_mismatch")
        if result.generated_at is not None and normalize_aware_datetime(item["generated_at"]) != result.generated_at:
            raise AdvisoryValidationError("freshness_timestamp_mismatch")
        if result.expires_at is not None:
            if "expires_at" not in item:
                raise AdvisoryValidationError("freshness_timestamp_mismatch")
            try:
                expires_at = context_expiry_instant(item["expires_at"], item["generated_at"])
            except (TimeContractError, TypeError, ValueError) as exc:
                raise AdvisoryValidationError("freshness_assessment_invalid") from exc
            if expires_at != result.expires_at:
                raise AdvisoryValidationError("freshness_timestamp_mismatch")


def _require_number_0_1(value: Any, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AdvisoryValidationError(f"{name} must be numeric")
    if value < 0 or value > 1:
        raise AdvisoryValidationError(f"{name} must be between 0 and 1")


def validate_advisory_report(payload: Mapping[str, Any]) -> None:
    account_action_fields = _find_account_action_fields(payload)
    if account_action_fields:
        raise AdvisoryValidationError(
            "account-action fields are forbidden: " + ", ".join(account_action_fields)
        )
    required = (
        "schema_version",
        "as_of",
        "generated_at",
        "mode",
        "cadence",
        "audience_scope",
        "source_artifacts",
        "summary",
        "recommendations",
        "policy",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AdvisoryValidationError(f"missing required keys: {', '.join(missing)}")

    schema_version = payload["schema_version"]
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise AdvisoryValidationError("schema_version_type_invalid")
    try:
        expected_contract = contract_version_for_schema(schema_version)
    except TimeContractError as exc:
        raise AdvisoryValidationError("schema_version_unsupported") from exc
    actual_contract = payload.get("contract_version")
    if actual_contract is not None and actual_contract != expected_contract:
        raise AdvisoryValidationError("contract_version_mismatch")
    if schema_version == "5":
        v6_only_keys = {"reference_time", "expires_at", "freshness", "input_digest"} & set(payload)
        if v6_only_keys:
            raise AdvisoryValidationError("v6_fields_on_v5")
    elif schema_version == "6":
        if actual_contract != "model_recommendations.v6":
            raise AdvisoryValidationError("v6_contract_version_required")
        for key in ("reference_time", "expires_at", "freshness", "input_digest"):
            if key not in payload:
                raise AdvisoryValidationError("v6_fields_incomplete")
    else:
        raise AdvisoryValidationError("schema_version_unsupported")
    _require_iso_date(payload["as_of"], "as_of")
    report_as_of = dt.date.fromisoformat(payload["as_of"])
    if schema_version == "5":
        _require_iso_datetime(payload["generated_at"], "generated_at")
    else:
        reference_time = _require_contract_datetime(payload["reference_time"], "reference_time")
        report_generated_at = _require_contract_datetime(payload["generated_at"], "generated_at")
        expires_at = _require_contract_datetime(payload["expires_at"], "expires_at")
        if reference_time != canonical_reference_time(report_as_of):
            raise AdvisoryValidationError("reference_time_mismatch")
        if report_generated_at < reference_time:
            raise AdvisoryValidationError("generated_at_before_reference")
        if expires_at != report_generated_at + dt.timedelta(days=REPORT_EXPIRY_DAYS):
            raise AdvisoryValidationError("expires_at_mismatch")
        _require_sha256_digest(payload["input_digest"], "input_digest")
        _validate_v6_freshness(
            payload["freshness"],
            report_as_of=report_as_of,
            reference_time=reference_time,
            report_generated_at=report_generated_at,
            source_artifacts=payload["source_artifacts"],
        )
    if payload["mode"] != "model_recommendations":
        raise AdvisoryValidationError("mode must be model_recommendations")
    if payload["cadence"] not in ALLOWED_CADENCES:
        raise AdvisoryValidationError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    if payload["audience_scope"] != "non_personalized_model_research":
        raise AdvisoryValidationError("audience_scope must be non_personalized_model_research")

    _require_mapping(payload["source_artifacts"], "source_artifacts")
    _require_mapping(payload["summary"], "summary")

    recommendations = _require_sequence(payload["recommendations"], "recommendations")
    for index, recommendation in enumerate(recommendations):
        rec = _require_mapping(recommendation, f"recommendations[{index}]")
        account_keys = sorted(DISALLOWED_ACCOUNT_ACTION_KEYS & set(rec))
        if account_keys:
            raise AdvisoryValidationError(
                f"recommendations[{index}] contains account-action fields: {', '.join(account_keys)}"
            )
        for key in (
            "symbol",
            "rating",
            "rating_label",
            "recommendation_tier",
            "recommendation_tier_label",
            "primary_horizon",
            "primary_horizon_label",
            "primary_horizon_window",
            "horizon_note",
            "suitable_horizons",
            "suitable_horizon_windows",
            "strategy_style",
            "score",
            "evidence_score",
            "risk_score",
            "source_confidence",
            "source_confidence_label",
            "reasons",
            "risk_notes",
            "evidence_refs",
            "review_checklist",
        ):
            if key not in rec:
                raise AdvisoryValidationError(f"recommendations[{index}] missing {key}")
        _require_string(rec["symbol"], f"recommendations[{index}].symbol")
        if rec["rating"] not in ALLOWED_RECOMMENDATION_RATINGS:
            raise AdvisoryValidationError(f"recommendations[{index}].rating is not allowed")
        _require_string(rec["rating_label"], f"recommendations[{index}].rating_label")
        if rec["recommendation_tier"] not in ALLOWED_RECOMMENDATION_TIERS:
            raise AdvisoryValidationError(f"recommendations[{index}].recommendation_tier is not allowed")
        _require_string(rec["recommendation_tier_label"], f"recommendations[{index}].recommendation_tier_label")
        if rec["primary_horizon"] not in ALLOWED_HORIZONS:
            raise AdvisoryValidationError(f"recommendations[{index}].primary_horizon is not allowed")
        _require_string(rec["primary_horizon_label"], f"recommendations[{index}].primary_horizon_label")
        _require_string(rec["primary_horizon_window"], f"recommendations[{index}].primary_horizon_window")
        _require_string(rec["horizon_note"], f"recommendations[{index}].horizon_note")
        horizons = _require_sequence(rec["suitable_horizons"], f"recommendations[{index}].suitable_horizons")
        if any(horizon not in ALLOWED_HORIZONS for horizon in horizons):
            raise AdvisoryValidationError(f"recommendations[{index}].suitable_horizons contains an unsupported horizon")
        horizon_windows = _require_mapping(
            rec["suitable_horizon_windows"], f"recommendations[{index}].suitable_horizon_windows"
        )
        for horizon in horizons:
            _require_string(
                horizon_windows.get(horizon), f"recommendations[{index}].suitable_horizon_windows.{horizon}"
            )
        if rec["strategy_style"] not in ALLOWED_STRATEGY_STYLES:
            raise AdvisoryValidationError(f"recommendations[{index}].strategy_style is not allowed")
        _require_number_0_1(rec["score"], f"recommendations[{index}].score")
        if rec["source_confidence"] not in ALLOWED_SOURCE_CONFIDENCE:
            raise AdvisoryValidationError(f"recommendations[{index}].source_confidence is not allowed")
        _require_string(rec["source_confidence_label"], f"recommendations[{index}].source_confidence_label")
        if not isinstance(rec["evidence_score"], int):
            raise AdvisoryValidationError(f"recommendations[{index}].evidence_score must be an integer")
        if not isinstance(rec["risk_score"], int):
            raise AdvisoryValidationError(f"recommendations[{index}].risk_score must be an integer")
        _require_sequence(rec["reasons"], f"recommendations[{index}].reasons")
        _require_sequence(rec["risk_notes"], f"recommendations[{index}].risk_notes")
        _require_sequence(rec["evidence_refs"], f"recommendations[{index}].evidence_refs")
        _require_sequence(rec["review_checklist"], f"recommendations[{index}].review_checklist")

    if "theme_first_candidates" in payload:
        theme_candidates = _require_sequence(payload["theme_first_candidates"], "theme_first_candidates")
        for index, candidate in enumerate(theme_candidates):
            item = _require_mapping(candidate, f"theme_first_candidates[{index}]")
            account_keys = sorted(DISALLOWED_ACCOUNT_ACTION_KEYS & set(item))
            if account_keys:
                raise AdvisoryValidationError(
                    f"theme_first_candidates[{index}] contains account-action fields: {', '.join(account_keys)}"
                )
            _require_string(item.get("symbol"), f"theme_first_candidates[{index}].symbol")
            _require_string(item.get("candidate_type"), f"theme_first_candidates[{index}].candidate_type")

    if "final_decisions" in payload:
        final_decisions = _require_mapping(payload["final_decisions"], "final_decisions")
        section_actions = {
            "recommendations": "recommend",
            "watchlist": "watch",
            "overflow_recommendations": "recommend",
        }
        for section, expected_action in section_actions.items():
            for index, pick in enumerate(_require_sequence(final_decisions.get(section, []), f"final_decisions.{section}")):
                item = _require_mapping(pick, f"final_decisions.{section}[{index}]")
                account_keys = sorted(DISALLOWED_ACCOUNT_ACTION_KEYS & set(item))
                if account_keys:
                    raise AdvisoryValidationError(
                        f"final_decisions.{section}[{index}] contains account-action fields: {', '.join(account_keys)}"
                    )
                _require_string(item.get("symbol"), f"final_decisions.{section}[{index}].symbol")
                if item.get("action") != expected_action:
                    raise AdvisoryValidationError(
                        f"final_decisions.{section}[{index}].action must be {expected_action}"
                    )
                if "horizon_scores" in item:
                    horizon_scores = _require_mapping(
                        item["horizon_scores"], f"final_decisions.{section}[{index}].horizon_scores"
                    )
                    for horizon in ("short", "medium", "long"):
                        score_item = _require_mapping(
                            horizon_scores.get(horizon),
                            f"final_decisions.{section}[{index}].horizon_scores.{horizon}",
                        )
                        _require_number_0_1(score_item.get("score"), f"final_decisions.{section}[{index}].{horizon}.score")
                if "selection_trace" in item:
                    _require_sequence(item["selection_trace"], f"final_decisions.{section}[{index}].selection_trace")
                if "horizon_actions" in item:
                    horizon_actions = _require_mapping(
                        item["horizon_actions"], f"final_decisions.{section}[{index}].horizon_actions"
                    )
                    for horizon in ("short", "medium", "long"):
                        action = horizon_actions.get(horizon)
                        if action not in ALLOWED_FINAL_ACTIONS:
                            raise AdvisoryValidationError(
                                f"final_decisions.{section}[{index}].horizon_actions.{horizon} is not allowed"
                            )

    policy = _require_mapping(payload["policy"], "policy")
    if policy.get("execution_allowed") is not False:
        raise AdvisoryValidationError("policy.execution_allowed must be false")
    if policy.get("portfolio_allocation_allowed") is not False:
        raise AdvisoryValidationError("policy.portfolio_allocation_allowed must be false")
    if policy.get("personalized_advice_allowed") is not False:
        raise AdvisoryValidationError("policy.personalized_advice_allowed must be false")
    if policy.get("non_personalized_recommendations_allowed") is not True:
        raise AdvisoryValidationError("policy.non_personalized_recommendations_allowed must be true")
    if policy.get("account_specific_advice_allowed") is not False:
        raise AdvisoryValidationError("policy.account_specific_advice_allowed must be false")
    _require_string(policy.get("downstream_use"), "policy.downstream_use")

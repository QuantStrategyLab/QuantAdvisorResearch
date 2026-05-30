from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any


class AdvisoryValidationError(ValueError):
    """Raised when an advisory artifact violates the stable contract."""


ALLOWED_CADENCES = frozenset({"daily", "weekly", "monthly"})
ALLOWED_RECOMMENDATION_RATINGS = frozenset({"recommend", "watch", "verify_source", "defer", "monitor"})
ALLOWED_RECOMMENDATION_TIERS = frozenset({"tier_1", "tier_2", "watchlist", "source_check", "defer", "monitor"})
ALLOWED_HORIZONS = frozenset({"short", "medium", "long", "not_applicable"})
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
        "account_id",
        "broker",
        "order_type",
        "shares",
        "target_quantity",
        "target_weight",
        "portfolio_weight",
        "entry_order",
        "exit_order",
    }
)


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


def _require_number_0_1(value: Any, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AdvisoryValidationError(f"{name} must be numeric")
    if value < 0 or value > 1:
        raise AdvisoryValidationError(f"{name} must be between 0 and 1")


def validate_advisory_report(payload: Mapping[str, Any]) -> None:
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

    if payload["schema_version"] != "4":
        raise AdvisoryValidationError("schema_version must be '4'")
    _require_iso_date(payload["as_of"], "as_of")
    _require_iso_datetime(payload["generated_at"], "generated_at")
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
            "horizon_note",
            "suitable_horizons",
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
        _require_string(rec["horizon_note"], f"recommendations[{index}].horizon_note")
        horizons = _require_sequence(rec["suitable_horizons"], f"recommendations[{index}].suitable_horizons")
        if any(horizon not in ALLOWED_HORIZONS for horizon in horizons):
            raise AdvisoryValidationError(f"recommendations[{index}].suitable_horizons contains an unsupported horizon")
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

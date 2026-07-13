from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any


class AdvisoryValidationError(ValueError):
    """Raised when an advisory artifact violates the stable contract."""


ALLOWED_CADENCES = frozenset({"daily", "weekly", "monthly"})
SOURCE_PROJECT = "QuantAdvisorResearch"
REPORT_CONTRACT_VERSION = "model_recommendations.v6"
V5_REPORT_CONTRACT_VERSION = "model_recommendations.v5"
REPORT_EXPIRY_DAYS = 7
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


def _require_timezone_aware_iso_datetime(value: Any, name: str) -> None:
    text = _require_string(value, name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AdvisoryValidationError(f"{name} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdvisoryValidationError(f"{name} must be timezone-aware")


def _parse_timezone_aware_iso_datetime(value: Any, name: str) -> dt.datetime:
    _require_timezone_aware_iso_datetime(value, name)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return dt.datetime.fromisoformat(text)


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

    schema_version = payload["schema_version"]
    if schema_version not in {"5", "6"}:
        raise AdvisoryValidationError("schema_version must be '5' or '6'")
    if schema_version == "6":
        for key in ("contract_version", "reference_time", "expires_at", "freshness"):
            if key not in payload:
                raise AdvisoryValidationError(f"missing required keys: {key}")
        if payload["contract_version"] != REPORT_CONTRACT_VERSION:
            raise AdvisoryValidationError("v6 reports must use model_recommendations.v6")
    else:
        if "contract_version" in payload and payload["contract_version"] != V5_REPORT_CONTRACT_VERSION:
            raise AdvisoryValidationError("schema 5 contract_version must be model_recommendations.v5")
        v6_only_keys = {"reference_time", "expires_at", "freshness"} & set(payload)
        if v6_only_keys:
            raise AdvisoryValidationError(f"schema 5 must not contain v6-only keys: {', '.join(sorted(v6_only_keys))}")
    _require_iso_date(payload["as_of"], "as_of")
    if schema_version == "6":
        _require_timezone_aware_iso_datetime(payload["generated_at"], "generated_at")
        _require_timezone_aware_iso_datetime(payload["reference_time"], "reference_time")
        _require_timezone_aware_iso_datetime(payload["expires_at"], "expires_at")
        generated_at = _parse_timezone_aware_iso_datetime(payload["generated_at"], "generated_at")
        reference_time = _parse_timezone_aware_iso_datetime(payload["reference_time"], "reference_time")
        expires_at = _parse_timezone_aware_iso_datetime(payload["expires_at"], "expires_at")
        if expires_at < reference_time:
            raise AdvisoryValidationError("expires_at must not precede reference_time")
        if expires_at != generated_at + dt.timedelta(days=REPORT_EXPIRY_DAYS):
            raise AdvisoryValidationError("expires_at must equal generated_at plus REPORT_EXPIRY_DAYS")
        freshness = _require_mapping(payload["freshness"], "freshness")
        expected_freshness = {"ai_signal", "theme_momentum"}
        missing_freshness = expected_freshness - set(freshness)
        if missing_freshness:
            raise AdvisoryValidationError(f"freshness missing entries: {', '.join(sorted(missing_freshness))}")
        for name in expected_freshness:
            item = freshness[name]
            if not isinstance(item, Mapping):
                raise AdvisoryValidationError(f"freshness[{name}] must be an object")
            if type(item.get("present")) is not bool:
                raise AdvisoryValidationError(f"freshness[{name}].present must be boolean")
            if type(item.get("valid")) is not bool:
                raise AdvisoryValidationError(f"freshness[{name}].valid must be boolean")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise AdvisoryValidationError(f"freshness[{name}].reason must be non-empty")
            legacy_expiry = item.get("reason") == "legacy_expiry_compatibility" and item.get("compatibility_warning") == "missing_expires_at"
            if item.get("valid") and item.get("as_of"):
                _require_iso_date(item["as_of"], f"freshness[{name}].as_of")
            if item.get("valid") and item.get("generated_at"):
                _require_timezone_aware_iso_datetime(item["generated_at"], f"freshness[{name}].generated_at")
            if item.get("valid") and item.get("expires_at"):
                _require_timezone_aware_iso_datetime(item["expires_at"], f"freshness[{name}].expires_at")
            if item.get("valid") and not item.get("as_of"):
                raise AdvisoryValidationError(f"freshness[{name}] valid entry missing time fields")
            if item.get("valid") and (not item.get("generated_at") or (not item.get("expires_at") and not legacy_expiry)):
                raise AdvisoryValidationError(f"freshness[{name}] valid entry missing time fields")
    else:
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

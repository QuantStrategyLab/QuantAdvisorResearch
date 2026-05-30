from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any


class AdvisoryValidationError(ValueError):
    """Raised when an advisory artifact violates the stable contract."""


ALLOWED_CADENCES = frozenset({"daily", "weekly", "monthly"})
ALLOWED_ACTIONS = frozenset({"source_review_only", "watch", "research_candidate", "avoid_or_defer", "monitor"})
ALLOWED_STYLES = frozenset(
    {
        "event_driven_speculation",
        "long_horizon_growth",
        "value_quality_review",
        "defensive_macro_context",
        "mixed_research",
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

    if payload["schema_version"] != "1":
        raise AdvisoryValidationError("schema_version must be '1'")
    _require_iso_date(payload["as_of"], "as_of")
    _require_iso_datetime(payload["generated_at"], "generated_at")
    if payload["mode"] != "recommendation_only":
        raise AdvisoryValidationError("mode must be recommendation_only")
    if payload["cadence"] not in ALLOWED_CADENCES:
        raise AdvisoryValidationError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    if payload["audience_scope"] != "non_personalized_research":
        raise AdvisoryValidationError("audience_scope must be non_personalized_research")

    _require_mapping(payload["source_artifacts"], "source_artifacts")
    _require_mapping(payload["summary"], "summary")

    recommendations = _require_sequence(payload["recommendations"], "recommendations")
    for index, recommendation in enumerate(recommendations):
        rec = _require_mapping(recommendation, f"recommendations[{index}]")
        for key in (
            "symbol",
            "stance",
            "action",
            "style",
            "conviction",
            "evidence_score",
            "risk_score",
            "thesis",
            "risks",
            "evidence_refs",
            "review_checklist",
        ):
            if key not in rec:
                raise AdvisoryValidationError(f"recommendations[{index}] missing {key}")
        _require_string(rec["symbol"], f"recommendations[{index}].symbol")
        _require_string(rec["stance"], f"recommendations[{index}].stance")
        if rec["action"] not in ALLOWED_ACTIONS:
            raise AdvisoryValidationError(f"recommendations[{index}].action is not allowed")
        if rec["style"] not in ALLOWED_STYLES:
            raise AdvisoryValidationError(f"recommendations[{index}].style is not allowed")
        _require_number_0_1(rec["conviction"], f"recommendations[{index}].conviction")
        if not isinstance(rec["evidence_score"], int):
            raise AdvisoryValidationError(f"recommendations[{index}].evidence_score must be an integer")
        if not isinstance(rec["risk_score"], int):
            raise AdvisoryValidationError(f"recommendations[{index}].risk_score must be an integer")
        _require_string(rec["thesis"], f"recommendations[{index}].thesis")
        _require_sequence(rec["risks"], f"recommendations[{index}].risks")
        _require_sequence(rec["evidence_refs"], f"recommendations[{index}].evidence_refs")
        _require_sequence(rec["review_checklist"], f"recommendations[{index}].review_checklist")

    policy = _require_mapping(payload["policy"], "policy")
    if policy.get("execution_allowed") is not False:
        raise AdvisoryValidationError("policy.execution_allowed must be false")
    if policy.get("portfolio_allocation_allowed") is not False:
        raise AdvisoryValidationError("policy.portfolio_allocation_allowed must be false")
    if policy.get("personalized_advice_allowed") is not False:
        raise AdvisoryValidationError("policy.personalized_advice_allowed must be false")
    _require_string(policy.get("downstream_use"), "policy.downstream_use")


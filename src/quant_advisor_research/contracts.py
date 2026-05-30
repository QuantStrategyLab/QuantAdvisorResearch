from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any


class AdvisoryValidationError(ValueError):
    """Raised when an advisory artifact violates the stable contract."""


ALLOWED_CADENCES = frozenset({"daily", "weekly", "monthly"})
ALLOWED_REVIEW_STATUSES = frozenset({"verify_source", "observe", "evidence_review", "risk_defer", "context_monitor"})
ALLOWED_RESEARCH_LENSES = frozenset(
    {
        "event_research",
        "long_horizon_context",
        "quality_review",
        "macro_context",
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
        "research_items",
        "policy",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AdvisoryValidationError(f"missing required keys: {', '.join(missing)}")

    if payload["schema_version"] != "2":
        raise AdvisoryValidationError("schema_version must be '2'")
    _require_iso_date(payload["as_of"], "as_of")
    _require_iso_datetime(payload["generated_at"], "generated_at")
    if payload["mode"] != "research_radar":
        raise AdvisoryValidationError("mode must be research_radar")
    if payload["cadence"] not in ALLOWED_CADENCES:
        raise AdvisoryValidationError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    if payload["audience_scope"] != "non_personalized_research":
        raise AdvisoryValidationError("audience_scope must be non_personalized_research")

    _require_mapping(payload["source_artifacts"], "source_artifacts")
    _require_mapping(payload["summary"], "summary")

    research_items = _require_sequence(payload["research_items"], "research_items")
    for index, research_item in enumerate(research_items):
        item = _require_mapping(research_item, f"research_items[{index}]")
        legacy_keys = {"action", "stance", "conviction", "recommendation"}
        present_legacy_keys = sorted(legacy_keys & set(item))
        if present_legacy_keys:
            raise AdvisoryValidationError(
                f"research_items[{index}] contains direct-recommendation wording: {', '.join(present_legacy_keys)}"
            )
        for key in (
            "symbol",
            "research_view",
            "review_status",
            "research_lens",
            "research_priority",
            "evidence_score",
            "risk_score",
            "evidence_summary",
            "risks",
            "evidence_refs",
            "review_checklist",
            "not_investment_rating",
        ):
            if key not in item:
                raise AdvisoryValidationError(f"research_items[{index}] missing {key}")
        _require_string(item["symbol"], f"research_items[{index}].symbol")
        _require_string(item["research_view"], f"research_items[{index}].research_view")
        if item["review_status"] not in ALLOWED_REVIEW_STATUSES:
            raise AdvisoryValidationError(f"research_items[{index}].review_status is not allowed")
        if item["research_lens"] not in ALLOWED_RESEARCH_LENSES:
            raise AdvisoryValidationError(f"research_items[{index}].research_lens is not allowed")
        _require_number_0_1(item["research_priority"], f"research_items[{index}].research_priority")
        if not isinstance(item["evidence_score"], int):
            raise AdvisoryValidationError(f"research_items[{index}].evidence_score must be an integer")
        if not isinstance(item["risk_score"], int):
            raise AdvisoryValidationError(f"research_items[{index}].risk_score must be an integer")
        _require_string(item["evidence_summary"], f"research_items[{index}].evidence_summary")
        _require_sequence(item["risks"], f"research_items[{index}].risks")
        _require_sequence(item["evidence_refs"], f"research_items[{index}].evidence_refs")
        _require_sequence(item["review_checklist"], f"research_items[{index}].review_checklist")
        if item["not_investment_rating"] is not True:
            raise AdvisoryValidationError(f"research_items[{index}].not_investment_rating must be true")

    policy = _require_mapping(payload["policy"], "policy")
    if policy.get("execution_allowed") is not False:
        raise AdvisoryValidationError("policy.execution_allowed must be false")
    if policy.get("portfolio_allocation_allowed") is not False:
        raise AdvisoryValidationError("policy.portfolio_allocation_allowed must be false")
    if policy.get("personalized_advice_allowed") is not False:
        raise AdvisoryValidationError("policy.personalized_advice_allowed must be false")
    if policy.get("direct_stock_recommendation_allowed") is not False:
        raise AdvisoryValidationError("policy.direct_stock_recommendation_allowed must be false")
    _require_string(policy.get("downstream_use"), "policy.downstream_use")

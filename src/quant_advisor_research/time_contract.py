"""Pure, side-effect-free time contract primitives for the advisory artifacts."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping


REPORT_EXPIRY_DAYS = 7
_VERSION_BY_SCHEMA = {"5": "model_recommendations.v5", "6": "model_recommendations.v6"}


class TimeContractError(ValueError):
    """Raised when a time or version contract cannot be satisfied."""


@dataclass(frozen=True)
class ReportTimeBounds:
    reference_time: dt.datetime
    generated_at: dt.datetime
    expires_at: dt.datetime


@dataclass(frozen=True)
class ContextFreshness:
    present: bool
    valid: bool
    reason: str
    as_of: dt.date | None = None
    generated_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    age_days: int | None = None


def normalize_aware_datetime(value: dt.datetime | str) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimeContractError("datetime must be timezone-aware")
    return parsed.astimezone(dt.UTC)


def canonical_reference_time(as_of: dt.date) -> dt.datetime:
    """Return the exclusive start of the next UTC calendar day."""
    return dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)


def report_time_bounds(as_of: dt.date, generated_at: dt.datetime | str) -> ReportTimeBounds:
    reference_time = canonical_reference_time(as_of)
    generated = normalize_aware_datetime(generated_at)
    if generated < reference_time:
        raise TimeContractError("generated_at must be at or after reference_time")
    return ReportTimeBounds(reference_time, generated, generated + dt.timedelta(days=REPORT_EXPIRY_DAYS))


def _local_date(value: str) -> dt.date | None:
    try:
        if "T" not in value and " " not in value:
            return dt.date.fromisoformat(value)
        original = dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return original.date() if original.tzinfo and original.utcoffset() is not None else None
    except (TypeError, ValueError, TimeContractError):
        return None


def _original_timezone(value: str) -> dt.tzinfo | None:
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return parsed.tzinfo if parsed.tzinfo and parsed.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def context_expiry_instant(expires_at: str, generated_at: str) -> dt.datetime:
    if "T" not in expires_at and " " not in expires_at:
        timezone = _original_timezone(generated_at)
        if timezone is None:
            raise TimeContractError("date-only expires_at requires timezone-aware generated_at")
        try:
            local_eod = dt.datetime.combine(dt.date.fromisoformat(expires_at), dt.time(23, 59, 59), tzinfo=timezone)
        except ValueError as exc:
            raise TimeContractError("expires_at must be an ISO date or datetime") from exc
        return local_eod.astimezone(dt.UTC)
    return normalize_aware_datetime(expires_at)


def assess_context_freshness(
    payload: Mapping[str, Any] | None,
    *,
    report_as_of: dt.date,
    reference_time: dt.datetime,
    report_generated_at: dt.datetime,
    max_age_days: int,
    allow_legacy_expiry: bool = False,
) -> ContextFreshness:
    if payload is None:
        return ContextFreshness(False, False, "not_provided")
    source_text = str(payload.get("as_of") or "").strip()
    generated_text = str(payload.get("generated_at") or "").strip()
    expires_text = str(payload.get("expires_at") or "").strip()
    missing = [name for name, value in (("as_of", source_text), ("generated_at", generated_text), ("expires_at", expires_text)) if not value]
    legacy = allow_legacy_expiry and missing == ["expires_at"] and payload.get("reason") == "legacy_expiry_compatibility" and payload.get("compatibility_warning") == "missing_expires_at"
    if missing and not legacy:
        return ContextFreshness(True, False, f"missing_{missing[0]}")
    source_as_of = _local_date(source_text)
    generated_local_date = _local_date(generated_text)
    try:
        generated = normalize_aware_datetime(generated_text)
    except (TypeError, ValueError, TimeContractError):
        generated = None
    if source_as_of is None:
        return ContextFreshness(True, False, "invalid_as_of")
    if generated is None or generated_local_date is None:
        return ContextFreshness(True, False, "invalid_generated_at")
    if source_as_of > report_as_of:
        return ContextFreshness(True, False, "as_of_in_future", source_as_of, generated)
    if generated > reference_time:
        return ContextFreshness(True, False, "generated_after_reference", source_as_of, generated)
    if generated > report_generated_at:
        return ContextFreshness(True, False, "generated_after_report_build", source_as_of, generated)
    if generated_local_date < source_as_of:
        return ContextFreshness(True, False, "generated_before_as_of", source_as_of, generated)
    if legacy:
        expires = None
    else:
        try:
            expires = context_expiry_instant(expires_text, generated_text)
        except (TypeError, ValueError, TimeContractError):
            return ContextFreshness(True, False, "invalid_expires_at", source_as_of, generated)
    if expires is not None and expires < generated:
        return ContextFreshness(True, False, "expires_before_generated", source_as_of, generated, expires)
    if expires is not None and reference_time > expires:
        return ContextFreshness(True, False, "expired", source_as_of, generated, expires)
    age_days = (report_as_of - source_as_of).days
    if age_days > max_age_days:
        return ContextFreshness(True, False, "stale_as_of", source_as_of, generated, expires, age_days)
    return ContextFreshness(True, True, "legacy_expiry_compatibility" if legacy else "fresh", source_as_of, generated, expires, age_days)


def schedule_cutoff_decision(as_of: dt.date, now: dt.datetime | str) -> str:
    current = normalize_aware_datetime(now)
    cutoff = canonical_reference_time(as_of)
    if current < cutoff:
        return "before_cutoff"
    if current == cutoff:
        return "at_cutoff"
    return "after_cutoff"


def contract_version_for_schema(schema_version: str) -> str:
    try:
        return _VERSION_BY_SCHEMA[schema_version]
    except KeyError as exc:
        raise TimeContractError(f"unsupported schema_version: {schema_version}") from exc


def schema_for_contract_version(contract_version: str) -> str:
    for schema, version in _VERSION_BY_SCHEMA.items():
        if version == contract_version:
            return schema
    raise TimeContractError(f"unsupported contract_version: {contract_version}")

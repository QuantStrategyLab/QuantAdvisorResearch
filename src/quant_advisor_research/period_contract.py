from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


SUPPORTED_CADENCES = frozenset({"daily", "weekly", "monthly"})


class PeriodContractError(ValueError):
    """Stable, sanitized error from canonical period derivation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CanonicalPeriod:
    cadence: str
    period_start: dt.date
    period_end: dt.date

    @property
    def key(self) -> str:
        return f"{self.cadence}:{self.period_start.isoformat()}:{self.period_end.isoformat()}"


def canonical_period_identity(cadence: str, as_of: str) -> CanonicalPeriod:
    if not isinstance(cadence, str):
        raise PeriodContractError("invalid_cadence")
    if cadence not in SUPPORTED_CADENCES:
        raise PeriodContractError("unsupported_cadence")
    if not isinstance(as_of, str):
        raise PeriodContractError("invalid_as_of")
    try:
        logical_date = dt.date.fromisoformat(as_of)
    except ValueError as error:
        raise PeriodContractError("invalid_as_of") from error
    if logical_date.isoformat() != as_of:
        raise PeriodContractError("invalid_as_of")

    if cadence == "daily":
        period_start = period_end = logical_date
    elif cadence == "weekly":
        try:
            period_start = logical_date - dt.timedelta(days=logical_date.isoweekday() - 1)
            period_end = period_start + dt.timedelta(days=6)
        except (OverflowError, ValueError) as error:
            raise PeriodContractError("period_boundary_unrepresentable") from error
    else:
        period_start = logical_date.replace(day=1)
        if logical_date.month == 12:
            period_end = dt.date(logical_date.year, 12, 31)
        else:
            next_month = dt.date(logical_date.year, logical_date.month + 1, 1)
            period_end = next_month - dt.timedelta(days=1)
    return CanonicalPeriod(cadence, period_start, period_end)

from __future__ import annotations

import datetime as dt

import pytest

from quant_advisor_research.period_contract import (
    PeriodContractError,
    canonical_period_identity,
)


@pytest.mark.parametrize(
    ("cadence", "as_of", "period_start", "period_end"),
    [
        ("daily", "2026-02-28", "2026-02-28", "2026-02-28"),
        ("weekly", "2026-06-15", "2026-06-15", "2026-06-21"),
        ("weekly", "2026-06-20", "2026-06-15", "2026-06-21"),
        ("weekly", "2026-06-21", "2026-06-15", "2026-06-21"),
        ("monthly", "2024-02-29", "2024-02-01", "2024-02-29"),
        ("monthly", "2026-04-30", "2026-04-01", "2026-04-30"),
    ],
)
def test_canonical_period_uses_cadence_specific_calendar_bounds(
    cadence: str, as_of: str, period_start: str, period_end: str
) -> None:
    period = canonical_period_identity(cadence, as_of)

    assert period.period_start == dt.date.fromisoformat(period_start)
    assert period.period_end == dt.date.fromisoformat(period_end)
    assert period.key == f"{cadence}:{period_start}:{period_end}"


def test_weekly_iso_year_boundary_is_stable() -> None:
    monday = canonical_period_identity("weekly", "2020-12-28")
    sunday = canonical_period_identity("weekly", "2021-01-03")

    assert monday == sunday
    assert monday.key == "weekly:2020-12-28:2021-01-03"


def test_v5_and_v6_metadata_do_not_change_derived_identity() -> None:
    v5 = canonical_period_identity("weekly", "2026-06-20")
    v6 = canonical_period_identity("weekly", "2026-06-20")

    assert v5 == v6
    assert canonical_period_identity("weekly", "2026-06-20") == v5


def test_generated_at_and_schema_changes_do_not_enter_identity() -> None:
    v5 = {"schema_version": "5", "cadence": "monthly", "as_of": "2026-02-01", "generated_at": "old"}
    v6 = {"schema_version": "6", "cadence": "monthly", "as_of": "2026-02-01", "generated_at": "new"}
    assert canonical_period_identity(v5["cadence"], v5["as_of"]) == canonical_period_identity(
        v6["cadence"], v6["as_of"]
    )


def test_old_weekly_less_than_seven_days_relation_is_replaced_by_one_bucket() -> None:
    a = canonical_period_identity("weekly", "2026-06-20")
    b = canonical_period_identity("weekly", "2026-06-26")
    c = canonical_period_identity("weekly", "2026-06-27")

    assert a != b
    assert b == c


@pytest.mark.parametrize(
    ("cadence", "as_of", "reason"),
    [
        ("quarterly", "2026-06-20", "unsupported_cadence"),
        ([], "2026-06-20", "invalid_cadence"),
        ("weekly", dt.date(2026, 6, 20), "invalid_as_of"),
        ("weekly", "2026-02-30", "invalid_as_of"),
        ("weekly", "2026-06-20T00:00:00Z", "invalid_as_of"),
    ],
)
def test_invalid_inputs_fail_closed_with_stable_sanitized_reason(cadence, as_of, reason: str) -> None:
    with pytest.raises(PeriodContractError) as error:
        canonical_period_identity(cadence, as_of)

    assert error.value.code == reason
    assert str(error.value) == reason
    assert "2026-02-30" not in str(error.value)


def test_unapproved_explicit_bounds_do_not_affect_identity() -> None:
    v6_without_bounds = {"schema_version": "6", "cadence": "weekly", "as_of": "2026-06-20"}
    v6_with_unapproved_bounds = {
        **v6_without_bounds,
        "period_start": "1900-01-01",
        "period_end": "1900-01-07",
    }
    assert canonical_period_identity(
        v6_without_bounds["cadence"], v6_without_bounds["as_of"]
    ) == canonical_period_identity(
        v6_with_unapproved_bounds["cadence"], v6_with_unapproved_bounds["as_of"]
    )

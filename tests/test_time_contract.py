from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.time_contract import (
    TimeContractError,
    assess_context_freshness,
    canonical_reference_time,
    contract_version_for_schema,
    context_expiry_instant,
    report_time_bounds,
    schedule_cutoff_decision,
    schema_for_contract_version,
)


ROOT = Path(__file__).resolve().parents[1]


def test_golden_reference_build_and_expiry_bounds() -> None:
    bounds = report_time_bounds(dt.date(2026, 5, 30), "2026-05-31T00:00:00.123456Z")

    assert bounds.reference_time == dt.datetime(2026, 5, 31, 0, 0, tzinfo=dt.UTC)
    assert bounds.generated_at == dt.datetime(2026, 5, 31, 0, 0, 0, 123456, tzinfo=dt.UTC)
    assert bounds.expires_at == dt.datetime(2026, 6, 7, 0, 0, 0, 123456, tzinfo=dt.UTC)


def test_reference_and_build_order_are_strict() -> None:
    assert canonical_reference_time(dt.date(2026, 5, 30)) == dt.datetime(2026, 5, 31, 0, 0, tzinfo=dt.UTC)
    with pytest.raises(TimeContractError, match="generated_at"):
        report_time_bounds(dt.date(2026, 5, 30), "2026-05-30T12:00:00Z")


def test_context_date_only_expiry_uses_original_offset_local_eod() -> None:
    assert context_expiry_instant("2026-06-30", "2026-05-30T00:30:00+08:00") == dt.datetime(
        2026, 6, 30, 15, 59, 59, tzinfo=dt.UTC
    )


def test_final_fractional_second_before_exclusive_next_day_cutoff_is_valid() -> None:
    result = assess_context_freshness(
        {"as_of": "2026-05-30", "generated_at": "2026-05-30T23:59:59.999999Z", "expires_at": "2026-06-30"},
        report_as_of=dt.date(2026, 5, 30),
        reference_time=canonical_reference_time(dt.date(2026, 5, 30)),
        report_generated_at=dt.datetime(2026, 5, 31, 0, 0, 1, tzinfo=dt.UTC),
        max_age_days=7,
    )
    assert result.valid is True
    assert context_expiry_instant("2026-06-30T23:00:00-04:00", "2026-05-30T00:30:00+08:00") == dt.datetime(
        2026, 7, 1, 3, 0, tzinfo=dt.UTC
    )


def test_context_freshness_bounds_and_legacy_marker() -> None:
    reference = canonical_reference_time(dt.date(2026, 5, 30))
    build = dt.datetime(2026, 5, 31, 12, tzinfo=dt.UTC)
    valid = assess_context_freshness(
        {"as_of": "2026-05-30", "generated_at": "2026-05-30T00:30:00+08:00", "expires_at": "2026-06-30"},
        report_as_of=dt.date(2026, 5, 30), reference_time=reference, report_generated_at=build, max_age_days=7,
    )
    assert valid.valid is True
    assert valid.reason == "fresh"

    legacy = assess_context_freshness(
        {"as_of": "2026-05-30", "generated_at": "2026-05-30T00:30:00+08:00", "reason": "legacy_expiry_compatibility", "compatibility_warning": "missing_expires_at"},
        report_as_of=dt.date(2026, 5, 30), reference_time=reference, report_generated_at=build, max_age_days=7,
        allow_legacy_expiry=True,
    )
    assert legacy.valid is True
    assert legacy.reason == "legacy_expiry_compatibility"


@pytest.mark.parametrize("expires_at", ["not-a-date", "2026-06-30Tbad"])
def test_malformed_context_expiry_is_deterministic_invalid(expires_at: str) -> None:
    result = assess_context_freshness(
        {"as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z", "expires_at": expires_at},
        report_as_of=dt.date(2026, 5, 30),
        reference_time=canonical_reference_time(dt.date(2026, 5, 30)),
        report_generated_at=dt.datetime(2026, 5, 31, tzinfo=dt.UTC),
        max_age_days=7,
    )
    assert result.valid is False
    assert result.reason == "invalid_expires_at"


@pytest.mark.parametrize("case", json.loads((ROOT / "tests/fixtures/time_contract_cases.json").read_text()))
def test_adversarial_freshness_cases(case: dict[str, object]) -> None:
    result = assess_context_freshness(
        case["payload"],
        report_as_of=dt.date.fromisoformat(case["report_as_of"]),
        reference_time=canonical_reference_time(dt.date.fromisoformat(case["report_as_of"])),
        report_generated_at=dt.datetime.fromisoformat(case["report_generated_at"].replace("Z", "+00:00")),
        max_age_days=7,
    )
    assert result.valid is case["valid"]
    assert result.reason == case["reason"]


@pytest.mark.parametrize(
    ("now", "expected"),
    [("2026-05-30T23:59:59.999999Z", "before_cutoff"), ("2026-05-31T00:00:00Z", "at_cutoff"), ("2026-05-31T00:00:00.000001Z", "after_cutoff")],
)
def test_schedule_cutoff_decisions(now: str, expected: str) -> None:
    assert schedule_cutoff_decision(dt.date(2026, 5, 30), now) == expected


def test_v5_v6_version_mapping_and_mismatch_rejection() -> None:
    assert contract_version_for_schema("5") == "model_recommendations.v5"
    assert contract_version_for_schema("6") == "model_recommendations.v6"
    assert schema_for_contract_version("model_recommendations.v5") == "5"
    assert schema_for_contract_version("model_recommendations.v6") == "6"
    with pytest.raises(TimeContractError):
        schema_for_contract_version("model_recommendations.v7")

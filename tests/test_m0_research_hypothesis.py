from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.m0_research_hypothesis import (
    M0_RESEARCH_HYPOTHESIS_SCHEMA_VERSION,
    M0ResearchHypothesisValidationError,
    adapt_advisory_report_to_m0_hypotheses,
    validate_m0_research_hypothesis,
)
from quant_advisor_research.time_contract import canonical_reference_time


ROOT = Path(__file__).resolve().parents[1]


def build_report() -> dict:
    return build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )


def test_adapter_projects_public_report_to_closed_research_only_hypotheses() -> None:
    report = build_report()

    hypotheses = adapt_advisory_report_to_m0_hypotheses(report)

    assert len(hypotheses) == len(report["recommendations"])
    first = hypotheses[0]
    assert first["schema_version"] == M0_RESEARCH_HYPOTHESIS_SCHEMA_VERSION
    assert first["authority"] == "research_only"
    assert first["no_order"] is True
    assert first["permitted_next_step"] == "research_validation_only"
    assert first["subject"]["kind"] == "asset_idea"
    assert first["subject"]["identifier"] == report["recommendations"][0]["symbol"]
    assert first["research_context"]["state"] in {
        "candidate",
        "source_verification_required",
        "deferred",
        "context_only",
    }
    assert first["research_context"]["primary_horizon"] == report["recommendations"][0]["primary_horizon"]
    assert first["research_context"]["suitable_horizons"] == list(
        dict.fromkeys(report["recommendations"][0]["suitable_horizons"])
    )
    assert first["research_context"]["primary_horizon"] in first["research_context"]["suitable_horizons"]
    assert first["provenance"]["source_schema_version"] == "6"
    assert first["provenance"]["source_input_digest"] == report["input_digest"]
    assert first["expires_at"] > first["generated_at"]
    assert "target_weight" not in first
    assert "recommendations" not in first
    validate_m0_research_hypothesis(first)


@pytest.mark.parametrize("field", ["targetWeight", "platform_route", "broker", "order_type"])
def test_closed_contract_rejects_nested_execution_or_routing_fields(field: str) -> None:
    hypothesis = adapt_advisory_report_to_m0_hypotheses(build_report())[0]
    hypothesis["research_context"][field] = "blocked"

    with pytest.raises(M0ResearchHypothesisValidationError, match="forbidden_semantic_field"):
        validate_m0_research_hypothesis(hypothesis)


def test_closed_contract_rejects_unknown_top_level_field() -> None:
    hypothesis = adapt_advisory_report_to_m0_hypotheses(build_report())[0]
    hypothesis["unexpected"] = True

    with pytest.raises(M0ResearchHypothesisValidationError, match="hypothesis_keys_invalid"):
        validate_m0_research_hypothesis(hypothesis)


def test_closed_contract_requires_explicit_no_order_true() -> None:
    hypothesis = adapt_advisory_report_to_m0_hypotheses(build_report())[0]
    hypothesis["no_order"] = False

    with pytest.raises(M0ResearchHypothesisValidationError, match="no_order_invalid"):
        validate_m0_research_hypothesis(hypothesis)


def test_adapter_deduplicates_suitable_horizons_without_splitting_the_hypothesis() -> None:
    report = build_report()
    source = report["recommendations"][0]
    source["suitable_horizons"] = ["short", source["primary_horizon"], "short"]

    hypothesis = adapt_advisory_report_to_m0_hypotheses(report)[0]

    assert hypothesis["research_context"]["primary_horizon"] == source["primary_horizon"]
    assert hypothesis["research_context"]["suitable_horizons"] == ["short", source["primary_horizon"]]


def test_adapter_supports_existing_v6_public_report_contract() -> None:
    report = build_report()
    reference_time = canonical_reference_time(dt.date.fromisoformat(report["as_of"]))
    report.update(
        {
            "schema_version": "6",
            "contract_version": "model_recommendations.v6",
            "generated_at": reference_time.isoformat().replace("+00:00", "Z"),
            "reference_time": reference_time.isoformat().replace("+00:00", "Z"),
            "expires_at": (reference_time + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z"),
            "input_digest": "a" * 64,
            "freshness": {
                "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
            },
        }
    )

    hypotheses = adapt_advisory_report_to_m0_hypotheses(report)

    assert hypotheses[0]["provenance"]["source_schema_version"] == "6"
    assert hypotheses[0]["provenance"]["source_contract_version"] == "model_recommendations.v6"
    assert hypotheses[0]["provenance"]["source_input_digest"] == "a" * 64
    assert hypotheses[0]["generated_at"] == "2026-05-31T00:00:00Z"
    assert hypotheses[0]["expires_at"] == "2026-06-07T00:00:00Z"


def test_adapter_rejects_source_report_execution_field_before_projection() -> None:
    report = build_report()
    report["recommendations"][0]["target_weight"] = 0.1

    with pytest.raises(M0ResearchHypothesisValidationError, match="source_report_invalid"):
        adapt_advisory_report_to_m0_hypotheses(report)

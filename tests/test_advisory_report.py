from __future__ import annotations

from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report, render_markdown
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report


ROOT = Path(__file__).resolve().parents[1]


def test_build_advisory_report_blocks_execution_and_allocation() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    assert report["mode"] == "recommendation_only"
    assert report["audience_scope"] == "non_personalized_research"
    assert report["policy"]["execution_allowed"] is False
    assert report["policy"]["portfolio_allocation_allowed"] is False
    assert report["policy"]["personalized_advice_allowed"] is False
    assert report["recommendations"]


def test_low_confidence_events_remain_source_review_only_until_verified() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="daily",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {recommendation["symbol"]: recommendation for recommendation in report["recommendations"]}

    assert by_symbol["EVT3"]["action"] == "source_review_only"
    assert by_symbol["EVT3"]["stance"] == "watch_pending_source_verification"
    assert by_symbol["EVT1"]["evidence_score"] > by_symbol["EVT4"]["evidence_score"]


def test_ai_avoid_bias_defers_candidate() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="monthly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {recommendation["symbol"]: recommendation for recommendation in report["recommendations"]}

    assert by_symbol["LEV1"]["action"] == "avoid_or_defer"


def test_contract_rejects_execution_enabled_report() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )
    report["policy"]["execution_allowed"] = True

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_render_markdown_contains_policy_section() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    markdown = render_markdown(report)

    assert "## Policy" in markdown
    assert "Execution allowed: `false`" in markdown

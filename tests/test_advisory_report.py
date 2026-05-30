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

    assert report["mode"] == "model_recommendations"
    assert report["audience_scope"] == "non_personalized_model_research"
    assert report["policy"]["non_personalized_recommendations_allowed"] is True
    assert report["policy"]["execution_allowed"] is False
    assert report["policy"]["portfolio_allocation_allowed"] is False
    assert report["policy"]["personalized_advice_allowed"] is False
    assert report["policy"]["account_specific_advice_allowed"] is False
    assert report["recommendations"]


def test_low_confidence_events_remain_verify_source_until_verified() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="daily",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {item["symbol"]: item for item in report["recommendations"]}

    assert by_symbol["EVT3"]["rating"] == "verify_source"
    assert by_symbol["EVT1"]["evidence_score"] > by_symbol["EVT4"]["evidence_score"]


def test_ai_avoid_bias_defers_research_item() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="monthly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {item["symbol"]: item for item in report["recommendations"]}

    assert by_symbol["LEV1"]["rating"] == "defer"


def test_high_evidence_events_generate_recommendations_with_horizon() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {item["symbol"]: item for item in report["recommendations"]}

    assert by_symbol["EVT1"]["rating"] == "recommend"
    assert by_symbol["EVT1"]["rating_label"] == "重点推荐"
    assert by_symbol["EVT1"]["recommendation_tier"] == "tier_1"
    assert by_symbol["EVT1"]["recommendation_tier_label"] == "一级推荐"
    assert by_symbol["EVT1"]["primary_horizon"] in {"short", "medium", "long"}
    assert by_symbol["EVT1"]["primary_horizon_window"] == "2-12周"
    assert by_symbol["EVT1"]["suitable_horizon_windows"]["short"] == "1-10个交易日"
    assert "1-10个交易日" in by_symbol["EVT1"]["horizon_note"]
    assert by_symbol["EVT1"]["source_confidence"] == "medium"
    assert by_symbol["EVT1"]["reasons"]


def test_mixed_confidence_recommendation_is_not_tier_one(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "\n".join(
            [
                "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes",
                "high-mention,2026-05-29,MIX,public_mention,bullish,high,https://example.invalid/high,high source",
                "low-lead,2026-05-29,MIX,disclosure_buy,bullish,low,https://example.invalid/low,low source",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    watchlist_path = tmp_path / "watchlist.csv"
    watchlist_path.write_text(
        "\n".join(
            [
                "symbol,name,bucket,research_status,thesis,source_url",
                "MIX,Mixed Source Candidate,named_mentioned,triggered,mixed source evidence,https://example.invalid/watch",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events_path,
        political_watchlist_path=watchlist_path,
    )

    rec = report["recommendations"][0]
    assert rec["rating"] == "recommend"
    assert rec["source_confidence"] == "mixed"
    assert rec["recommendation_tier"] == "tier_2"


def test_long_horizon_window_is_measured_in_years() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )

    by_symbol = {item["symbol"]: item for item in report["recommendations"]}

    assert by_symbol["IDX1"]["primary_horizon"] == "long"
    assert by_symbol["IDX1"]["primary_horizon_window"] == "1-3年"
    assert "超过3年" in by_symbol["IDX1"]["horizon_note"]


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
    assert "Non-personalized recommendations allowed: `true`" in markdown


def test_contract_rejects_account_action_fields() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )
    report["recommendations"][0]["target_weight"] = 0.1

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)

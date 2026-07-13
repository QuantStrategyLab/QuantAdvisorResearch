from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import (
    Event,
    WatchlistItem,
    accepted_entity_events,
    build_recommendation,
    build_advisory_report,
    build_final_decisions,
    load_theme_momentum,
    normalize_source_score,
    primary_horizon_from_actions,
    render_markdown,
)
from quant_advisor_research.artifacts import write_report_manifest
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report


ROOT = Path(__file__).resolve().parents[1]


def test_build_advisory_report_blocks_execution_and_allocation() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )

    assert report["mode"] == "model_recommendations"
    assert report["audience_scope"] == "non_personalized_model_research"
    assert report["policy"]["non_personalized_recommendations_allowed"] is True
    assert report["policy"]["execution_allowed"] is False
    assert report["policy"]["portfolio_allocation_allowed"] is False
    assert report["policy"]["personalized_advice_allowed"] is False
    assert report["policy"]["account_specific_advice_allowed"] is False
    assert report["summary"]["source_mode"] == "fixture"
    assert report["summary"]["data_quality_warnings"]
    assert report["recommendations"]


def test_report_freshness_fields_are_deterministic() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )

    assert report["reference_time"] == "2026-06-01T23:59:59Z"
    assert report["generated_at"] == report["reference_time"]
    assert report["expires_at"] == "2026-06-08T23:59:59Z"
    assert report["freshness"]["ai_signal"]["valid"] is True


def test_expired_ai_signal_fails_closed_for_long_context(tmp_path: Path) -> None:
    ai_signal = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    ai_signal.update(
        {
            "as_of": "2026-06-01",
            "generated_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-30",
        }
    )
    ai_path = tmp_path / "expired_ai_signal.json"
    ai_path.write_text(json.dumps(ai_signal) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-07-11",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:expired" in report["summary"]["data_quality_warnings"]
    assert report["summary"]["long_context_available"] is False
    assert report["final_decisions"]["horizon_action_buckets"]["long"]["recommend"] == []


def test_missing_context_expiry_fails_closed_with_warning(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload.pop("expires_at", None)
    ai_path = tmp_path / "missing_expiry.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:missing_expires_at" in report["summary"]["data_quality_warnings"]


def test_stale_theme_momentum_fails_closed_with_warning(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/theme_momentum_snapshot.example.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "as_of": "2026-04-01",
            "generated_at": "2026-04-01T00:00:00Z",
            "expires_at": "2026-12-31",
        }
    )
    theme_path = tmp_path / "stale_theme.json"
    theme_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=theme_path,
    )

    assert report["freshness"]["theme_momentum"]["valid"] is False
    assert "theme_momentum:stale_as_of" in report["summary"]["data_quality_warnings"]
    assert report["summary"]["theme_momentum_available"] is False



def test_old_schema_v5_report_without_new_freshness_fields_remains_compatible() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )
    report.pop("reference_time")
    report.pop("expires_at")
    report.pop("freshness")

    validate_advisory_report(report)


def test_old_generated_at_fails_closed_even_with_recent_as_of(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "as_of": "2026-07-06",
            "generated_at": "2026-07-06T00:00:00Z",
            "expires_at": "2026-12-31",
        }
    )
    ai_path = tmp_path / "old_generated_at.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-07-11",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:stale_generated_at" in report["summary"]["data_quality_warnings"]


def test_context_generated_at_must_not_precede_context_as_of(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "as_of": "2026-05-30",
            "generated_at": "2026-05-29T23:00:00Z",
            "expires_at": "2026-06-30",
        }
    )
    ai_path = tmp_path / "generated_before_as_of.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:generated_before_as_of" in report["summary"]["data_quality_warnings"]


def test_malformed_context_as_of_fails_closed_without_raising(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload["as_of"] = "not-a-date"
    ai_path = tmp_path / "malformed_as_of.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:invalid_as_of" in report["summary"]["data_quality_warnings"]


def test_future_context_as_of_is_rejected_against_report_cutoff(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "as_of": "2026-06-01",
            "generated_at": "2026-06-01T12:00:00Z",
            "expires_at": "2026-06-30",
        }
    )
    ai_path = tmp_path / "future_source_as_of.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is False
    assert "ai_signal:as_of_in_future" in report["summary"]["data_quality_warnings"]


def test_generated_at_offset_preserves_source_local_date(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "as_of": "2026-05-30",
            "generated_at": "2026-05-30T00:30:00+08:00",
            "expires_at": "2026-06-30",
        }
    )
    ai_path = tmp_path / "offset_generated_at.json"
    ai_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ai_path,
    )

    assert report["freshness"]["ai_signal"]["valid"] is True

def test_low_confidence_events_remain_verify_source_until_verified() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="daily",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
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
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )

    by_symbol = {item["symbol"]: item for item in report["recommendations"]}

    assert by_symbol["LEV1"]["rating"] == "defer"


def test_high_evidence_events_generate_recommendations_with_horizon() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
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
    assert by_symbol["EVT4"]["rating_label"] == "背景跟踪"
    assert by_symbol["EVT4"]["recommendation_tier_label"] == "背景跟踪"


def test_mixed_confidence_recommendation_is_not_tier_one(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "\n".join(
            [
                "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes,entity_match_type,match_evidence,relationship_type",
                "high-mention,2026-05-29,MIX,public_mention,bullish,high,https://example.invalid/high,high source,issuer,MIX is explicitly named,issuer",
                "low-lead,2026-05-29,MIX,disclosure_buy,bullish,low,https://example.invalid/low,low source,issuer,MIX is explicitly named,issuer",
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
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
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
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )
    report["policy"]["execution_allowed"] = True

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_render_markdown_keeps_public_report_direct() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )

    markdown = render_markdown(report)

    assert "# 智慧投顾研究周度复盘 - 2026-05-30" in markdown
    assert "股票背景" in markdown
    assert "推荐理由" in markdown
    assert "主要风险" in markdown
    assert "## 政策边界" not in markdown
    assert "允许下单" not in markdown
    assert "模式:" not in markdown
    assert "受众:" not in markdown
    assert "AI 状态" not in markdown
    assert "本期最终结论" not in markdown
    assert "中线主题上下文" in markdown
    assert "AI信号仓库" not in markdown
    assert "ResearchSignalContextPipelines" not in markdown


def test_contract_rejects_account_action_fields() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )
    report["recommendations"][0]["target_weight"] = 0.1

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_contract_rejects_theme_candidate_account_action_fields() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )
    report["theme_first_candidates"][0]["target_weight"] = 0.1

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_report_manifest_records_contract_version_and_hashes(tmp_path: Path) -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
    )
    report_path = tmp_path / "advisory_report.json"
    markdown_path = tmp_path / "advisory_report.md"
    report_path.write_text('{"ok": true}\n', encoding="utf-8")
    markdown_path.write_text("# Report\n", encoding="utf-8")

    manifest_path = write_report_manifest(
        report=report,
        report_path=report_path,
        markdown_path=markdown_path,
        manifest_path=tmp_path / "advisory_report.json.manifest.json",
        repository="QuantStrategyLab/QuantAdvisorResearch",
        git_sha="abcdef1234567890",
        run_id="123",
        run_attempt="2",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_type"] == "model_recommendation_report"
    assert manifest["contract_version"] == "model_recommendations.v5"
    assert manifest["version"] == "2026-05-30-weekly-schema-5-run-123-attempt-2"
    assert manifest["producer"]["git_sha"] == "abcdef1234567890"
    assert manifest["artifacts"]["json"]["sha256"]
    assert manifest["artifacts"]["markdown"]["sha256"]


def test_theme_bias_can_lift_static_watchlist_item_without_direct_symbol_bias(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n",
        encoding="utf-8",
    )
    watchlist_path = tmp_path / "watchlist.csv"
    watchlist_path.write_text(
        "\n".join(
            [
                "symbol,name,bucket,research_status,thesis,source_url",
                "MU,Micron Technology,policy_capital,watchlist,HBM and memory-cycle watch,https://example.invalid/mu",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ai_signal_path = tmp_path / "ai_signal.json"
    ai_signal_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "as_of": "2026-05-30",
                "generated_at": "2026-05-30T00:00:00Z",
                "mode": "shadow",
                "horizon": "1-3 years",
                "universe": ["MU"],
                "regime": "neutral",
                "risk_flags": [],
                "candidate_bias": {},
                "theme_bias": {"hbm_memory": "positive"},
                "symbol_theme_exposure": {"MU": ["hbm_memory"]},
                "confidence": 0.6,
                "evidence": {
                    "sources": ["theme-test"],
                    "summary": "Synthetic theme context.",
                    "data_gaps": [],
                },
                "expires_at": "2026-06-30",
                "policy": {
                    "execution_allowed": False,
                    "downstream_use": "Research-only shadow context.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events_path,
        political_watchlist_path=watchlist_path,
        ai_signal_path=ai_signal_path,
    )

    rec = report["recommendations"][0]
    assert rec["symbol"] == "MU"
    assert rec["rating"] == "watch"
    assert rec["evidence_score"] > 4
    assert any("主题=hbm_memory" in reason for reason in rec["reasons"])
    assert report["summary"]["long_context_available"] is False
    assert report["summary"]["long_context_missing_reason"] == "current_candidates_do_not_meet_long_context_gate"
    assert "MU" not in report["summary"]["long_context_symbols"]
    assert report["final_decisions"]["horizon_action_buckets"]["long"]["watch"] == []


def test_theme_momentum_snapshot_is_display_context_not_rating_input(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,event_date,symbol,event_type,direction,confidence,source_url,notes\n",
        encoding="utf-8",
    )
    watchlist_path = tmp_path / "watchlist.csv"
    watchlist_path.write_text(
        "\n".join(
            [
                "symbol,name,bucket,research_status,thesis,source_url",
                "MU,Micron Technology,policy_capital,watchlist,HBM and memory-cycle watch,https://example.invalid/mu",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    theme_momentum_path = ROOT / "examples/theme_momentum_snapshot.example.json"

    report_without_theme = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events_path,
        political_watchlist_path=watchlist_path,
    )
    report_with_theme = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=events_path,
        political_watchlist_path=watchlist_path,
        theme_momentum_path=theme_momentum_path,
    )

    assert report_with_theme["summary"]["theme_momentum_artifact_type"] == "medium_horizon_theme_context"
    assert report_with_theme["summary"]["theme_momentum_horizon"] == "medium"
    assert report_with_theme["summary"]["theme_momentum_horizon_window"] == "2-12周"
    assert report_with_theme["summary"]["top_theme_ids"][:1] == ["hbm_memory"]
    assert report_with_theme["summary"]["top_theme_candidate_symbols"][:3] == ["MU", "NVDA", "DELL"]
    assert report_with_theme["theme_momentum"]["top_themes"][0]["theme_id"] == "hbm_memory"
    assert report_with_theme["theme_momentum"]["top_themes"][0]["top_symbols"][:1] == ["MU"]
    assert report_with_theme["theme_first_candidates"][0]["symbol"] == "MU"
    assert report_with_theme["theme_first_candidates"][0]["primary_theme_id"] == "hbm_memory"
    assert report_with_theme["theme_first_candidates"][0]["industry_background"]
    assert report_with_theme["theme_first_candidates"][0]["recommendation_summary"]
    assert report_with_theme["theme_first_candidates"][2]["symbol"] == "DELL"
    first_pick = report_with_theme["final_decisions"]["recommendations"][0]
    assert first_pick["symbol"] == "MU"
    assert first_pick["business_summary"]
    assert "存储周期" in first_pick["risk_summary"]
    assert "ai_signal_score" in first_pick
    assert first_pick["medium_context_score"] == first_pick["ai_signal_score"]
    assert first_pick["supporting_context"]["medium"] == ["theme_momentum_snapshot"]
    assert set(first_pick["horizon_scores"]) == {"short", "medium", "long"}
    assert first_pick["horizon_scores"]["medium"]["score"] == first_pick["combined_score"]
    assert first_pick["selection_trace"]
    assert "ResearchSignalContextPipelines" not in report_with_theme["final_decisions"]["method"]
    assert report_with_theme["final_decisions"]["watchlist"][0]["symbol"] == "DELL"
    assert report_with_theme["recommendations"][0]["rating"] == report_without_theme["recommendations"][0]["rating"]
    assert report_with_theme["recommendations"][0]["score"] == report_without_theme["recommendations"][0]["score"]

    markdown = render_markdown(report_with_theme)
    assert "## 本期最终结论" not in markdown
    assert "股票背景" in markdown
    assert "推荐理由" in markdown
    assert "中线主题上下文" in markdown
    assert "AI信号仓库" not in markdown
    assert "ResearchSignalContextPipelines" not in markdown
    assert "## 主题候选（解释材料，不是最终推荐）" not in markdown
    assert "为什么入选" not in markdown
    assert "买多少" not in markdown
    assert "## 主题动量" not in markdown


def test_market_confirmation_is_optional_audit_input_not_public_copy() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
        market_confirmation_path=ROOT / "examples/market_confirmation.example.csv",
    )

    pick = report["final_decisions"]["recommendations"][0]
    assert report["source_artifacts"]["market_confirmation"].endswith("market_confirmation.example.csv")
    assert report["summary"]["market_confirmation_count"] == 5
    assert "market_confirmation" in pick["horizon_scores"]["medium"]["drivers"]
    assert "market_confirmation" in pick["supporting_context"]["medium"]
    assert set(pick["horizon_actions"]) == {"short", "medium", "long"}
    assert pick["horizon_actions"]["medium"] == "recommend"
    assert pick["primary_horizon"] == "medium"
    assert any("medium_score=" in item for item in pick["selection_trace"])

    markdown = render_markdown(report)
    assert "market_confirmation" not in markdown




def test_primary_horizon_requires_decisive_short_edge() -> None:
    actions = {"short": "recommend", "medium": "recommend", "long": "recommend"}

    near_tie_scores = {
        "short": {"score": 0.859},
        "medium": {"score": 0.845},
        "long": {"score": 0.657},
    }
    decisive_short_scores = {
        "short": {"score": 0.781},
        "medium": {"score": 0.688},
        "long": {"score": 0.631},
    }

    assert primary_horizon_from_actions(near_tie_scores, actions) == ("medium", "recommend")
    assert primary_horizon_from_actions(decisive_short_scores, actions) == ("short", "recommend")

def test_contract_rejects_final_decision_account_action_fields() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )
    report["final_decisions"]["recommendations"][0]["target_weight"] = 0.1

    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_source_score_does_not_use_recommendation_tier_prior() -> None:
    assert normalize_source_score(
        {
            "evidence_score": 5,
            "source_confidence": "no_event",
            "recommendation_tier": "watchlist",
        }
    ) == 0.0


def test_entity_acceptance_rejects_industry_context_from_company_source_score() -> None:
    industry_event = Event(
        event_id="industry-context",
        event_date=dt.date(2026, 5, 29),
        symbol="MSTR",
        event_type="public_mention",
        direction="neutral",
        confidence="high",
        source_url="https://www.nist.gov/example",
        notes="Generic standards context without company evidence.",
        entity_match_type="industry_context",
        match_evidence="nuclear reactors",
        relationship_type="industry_context",
    )

    assert accepted_entity_events([industry_event]) == []

    recommendation = build_recommendation(
        symbol="MSTR",
        item=WatchlistItem(
            symbol="MSTR",
            name="Strategy",
            bucket="named_mentioned",
            research_status="watchlist",
            thesis="Research candidate.",
            source_url="https://example.invalid/mstr",
        ),
        events=[industry_event],
        ai_signal=None,
        as_of=dt.date(2026, 5, 30),
    )

    assert recommendation["source_confidence"] == "no_event"
    assert recommendation["source_score"] == 0.0
    assert recommendation["entity_evidence"][0]["accepted"] is False


@pytest.mark.parametrize("symbol", ["MSTR", "OKLO", "PANW", "COIN"])
def test_entity_acceptance_false_positive_fixtures_are_not_company_evidence(symbol: str) -> None:
    event = Event(
        event_id=f"false-positive-{symbol}",
        event_date=dt.date(2026, 5, 29),
        symbol=symbol,
        event_type="public_mention",
        direction="neutral",
        confidence="high",
        source_url="https://www.nist.gov/example",
        notes="Generic policy context only.",
        entity_match_type="industry_context",
        match_evidence="generic industry term",
        relationship_type="industry_context",
    )

    assert accepted_entity_events([event]) == []


def test_entity_acceptance_allows_explicit_issuer_evidence() -> None:
    issuer_event = Event(
        event_id="issuer-release",
        event_date=dt.date(2026, 5, 29),
        symbol="COIN",
        event_type="public_mention",
        direction="bullish",
        confidence="medium",
        source_url="https://www.coinbase.com/news/example",
        notes="Issuer release.",
        entity_match_type="issuer",
        match_evidence="Coinbase is named in the release.",
        relationship_type="issuer",
    )

    assert accepted_entity_events([issuer_event]) == [issuer_event]

    recommendation = build_recommendation(
        symbol="COIN",
        item=None,
        events=[issuer_event],
        ai_signal=None,
        as_of=dt.date(2026, 5, 30),
    )

    assert recommendation["source_confidence"] == "medium"
    assert recommendation["source_score"] > 0.0
    assert recommendation["entity_evidence"][0]["accepted"] is True


def test_entity_acceptance_uses_relationship_type_for_company_semantics() -> None:
    event = Event(
        event_id="issuer-with-preserved-match-class",
        event_date=dt.date(2026, 5, 29),
        symbol="COIN",
        event_type="public_mention",
        direction="bullish",
        confidence="medium",
        source_url="https://www.coinbase.com/news/example",
        notes="Issuer release.",
        entity_match_type="named_entity_match",
        match_evidence="Coinbase is named in the release.",
        relationship_type="issuer",
    )

    assert accepted_entity_events([event]) == [event]


def test_final_decision_sections_keep_action_semantics_and_overflow() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )
    decisions = build_final_decisions(
        report["recommendations"],
        load_theme_momentum(ROOT / "examples/theme_momentum_snapshot.example.json"),
        max_recommendations=1,
        max_watchlist=1,
    )

    assert all(item["action"] == "recommend" for item in decisions["recommendations"])
    assert all(item["action"] == "watch" for item in decisions["watchlist"])
    assert all(item["action"] == "recommend" for item in decisions["overflow_recommendations"])
    assert decisions["overflow_recommendations"]
    assert report["summary"]["recommendation_count"] == report["summary"]["base_recommendation_count"]
    assert report["summary"]["final_recommendation_count"] == len(report["final_decisions"]["recommendations"])
    assert report["summary"]["final_watchlist_count"] == len(report["final_decisions"]["watchlist"])


def test_contract_rejects_final_decision_section_action_mismatch() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )
    report["final_decisions"]["watchlist"][0]["action"] = "recommend"

    with pytest.raises(AdvisoryValidationError, match="watchlist.*action must be watch"):
        validate_advisory_report(report)

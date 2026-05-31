from __future__ import annotations

from quant_advisor_research.monthly_review import build_monthly_review, render_monthly_review_markdown


def _report(as_of: str, picks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "as_of": as_of,
        "final_decisions": {
            "recommendations": picks,
        },
    }


def _pick(symbol: str, horizon: str = "medium") -> dict[str, object]:
    return {
        "symbol": symbol,
        "name": symbol,
        "primary_horizon": horizon,
        "primary_horizon_label": {"short": "短线", "medium": "中线", "long": "长线"}[horizon],
        "primary_horizon_window": {"short": "1-10个交易日", "medium": "2-12周", "long": "1-3年"}[horizon],
        "combined_score": 0.7,
        "source_score": 0.2,
        "momentum_score": 0.8,
        "ai_signal_score": 0.7,
        "business_summary": f"{symbol} background",
        "prospect_summary": f"{symbol} reason",
        "risk_summary": f"{symbol} risk",
    }


def test_monthly_review_compares_final_recommendations() -> None:
    current = _report("2026-05-31", [_pick("MU"), _pick("AMD", "long")])
    previous = _report("2026-04-30", [_pick("MU"), _pick("DELL")])

    review = build_monthly_review(current_report=current, previous_report=previous)

    assert review["mode"] == "monthly_advisory_review"
    assert review["summary"]["current_final_recommendations"] == ["MU", "AMD"]
    assert review["summary"]["added_symbols"] == ["AMD"]
    assert review["summary"]["removed_symbols"] == ["DELL"]
    assert review["summary"]["unchanged_symbols"] == ["MU"]
    assert review["summary"]["current_horizon_buckets"]["medium"] == ["MU"]
    assert review["summary"]["current_horizon_buckets"]["long"] == ["AMD"]


def test_monthly_review_records_missing_previous_report_warning() -> None:
    current = _report("2026-05-31", [_pick("MU")])

    review = build_monthly_review(current_report=current)
    markdown = render_monthly_review_markdown(review)

    assert review["summary"]["data_quality_warnings"]
    assert "本月最终推荐" in markdown
    assert "新增：MU" in markdown
    assert "No previous report supplied" in markdown

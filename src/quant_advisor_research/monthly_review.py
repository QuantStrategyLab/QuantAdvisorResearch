from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


HORIZON_LABELS_ZH = {
    "short": "短线",
    "medium": "中线",
    "long": "长线",
}

HORIZON_WINDOWS_ZH = {
    "short": "1-10个交易日",
    "medium": "2-12周",
    "long": "1-3年",
}


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def final_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = report.get("final_decisions")
    if not isinstance(decisions, dict):
        return []
    items = decisions.get("recommendations", [])
    return [item for item in items if isinstance(item, dict) and item.get("symbol")]


def symbols(items: list[dict[str, Any]]) -> list[str]:
    return [str(item["symbol"]).upper() for item in items]


def horizon_buckets(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    buckets = {"short": [], "medium": [], "long": []}
    for item in items:
        horizon = str(item.get("primary_horizon", ""))
        if horizon in buckets:
            buckets[horizon].append(str(item["symbol"]).upper())
    return buckets


def compact_pick(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(item.get("symbol", "")).upper(),
        "name": str(item.get("name", "")),
        "primary_horizon": str(item.get("primary_horizon", "")),
        "primary_horizon_label": str(item.get("primary_horizon_label", "")),
        "primary_horizon_window": str(item.get("primary_horizon_window", "")),
        "combined_score": item.get("combined_score"),
        "source_score": item.get("source_score"),
        "momentum_score": item.get("momentum_score"),
        "ai_signal_score": item.get("ai_signal_score"),
        "business_summary": str(item.get("business_summary", "")),
        "prospect_summary": str(item.get("prospect_summary", "")),
        "risk_summary": str(item.get("risk_summary", "")),
    }


def build_monthly_review(
    *,
    current_report: dict[str, Any],
    previous_report: dict[str, Any] | None = None,
    current_report_path: str | Path = "",
    previous_report_path: str | Path = "",
) -> dict[str, Any]:
    current_items = final_recommendations(current_report)
    previous_items = final_recommendations(previous_report or {})
    current_symbols = symbols(current_items)
    previous_symbols = symbols(previous_items)
    current_set = set(current_symbols)
    previous_set = set(previous_symbols)
    data_quality_warnings: list[str] = []
    if previous_report is None:
        data_quality_warnings.append("No previous report supplied; month-over-month changes are not available.")
    if not current_items:
        data_quality_warnings.append("Current report has no final recommendations.")

    return {
        "schema_version": "1",
        "mode": "monthly_advisory_review",
        "as_of": str(current_report.get("as_of", "")),
        "generated_at": utc_now_iso(),
        "source_artifacts": {
            "current_report": str(current_report_path),
            "previous_report": str(previous_report_path) if previous_report_path else "",
        },
        "summary": {
            "current_final_recommendations": current_symbols,
            "previous_final_recommendations": previous_symbols,
            "added_symbols": sorted(current_set - previous_set),
            "removed_symbols": sorted(previous_set - current_set),
            "unchanged_symbols": [symbol for symbol in current_symbols if symbol in previous_set],
            "current_horizon_buckets": horizon_buckets(current_items),
            "data_quality_warnings": data_quality_warnings,
        },
        "current_recommendations": [compact_pick(item) for item in current_items],
        "previous_recommendations": [compact_pick(item) for item in previous_items],
        "policy": {
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "personalized_advice_allowed": False,
            "downstream_use": "Monthly review of intelligent advisory research output only.",
        },
    }


def render_monthly_review_markdown(review: dict[str, Any]) -> str:
    lines = [f"# 智慧投顾研究月度复盘 - {review.get('as_of', '')}", ""]
    summary = review.get("summary", {})
    buckets = summary.get("current_horizon_buckets", {})
    lines.append("## 本月最终推荐")
    lines.append("")
    for horizon in ("short", "medium", "long"):
        label = HORIZON_LABELS_ZH[horizon]
        window = HORIZON_WINDOWS_ZH[horizon]
        value = ", ".join(buckets.get(horizon, [])) or "暂无系统结论"
        lines.append(f"- {label}（{window}）：{value}")
    lines.append("")
    lines.append("## 较上次变化")
    lines.append("")
    lines.append(f"- 新增：{', '.join(summary.get('added_symbols', [])) or '无'}")
    lines.append(f"- 移除：{', '.join(summary.get('removed_symbols', [])) or '无'}")
    lines.append(f"- 保持：{', '.join(summary.get('unchanged_symbols', [])) or '无'}")
    warnings = summary.get("data_quality_warnings", [])
    if warnings:
        lines.append("")
        lines.append("## 数据质量提示")
        lines.extend(f"- {warning}" for warning in warnings)
    picks = review.get("current_recommendations", [])
    if picks:
        lines.append("")
        lines.append("## 标的摘要")
        for item in picks:
            lines.extend(
                [
                    "",
                    f"### {item.get('symbol')} - {item.get('name')}",
                    f"- 周期：{item.get('primary_horizon_label')}（{item.get('primary_horizon_window')}）",
                    f"- 股票背景：{item.get('business_summary')}",
                    f"- 推荐理由：{item.get('prospect_summary')}",
                    f"- 主要风险：{item.get('risk_summary')}",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a monthly review artifact from advisory report JSON files.")
    parser.add_argument("--current-report", required=True, help="Current advisory report JSON path.")
    parser.add_argument("--previous-report", help="Optional previous advisory report JSON path.")
    parser.add_argument("--output-json", required=True, help="Output monthly review JSON path.")
    parser.add_argument("--output-md", required=True, help="Output monthly review Markdown path.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    current = load_report(args.current_report)
    previous = load_report(args.previous_report) if args.previous_report else None
    review = build_monthly_review(
        current_report=current,
        previous_report=previous,
        current_report_path=args.current_report,
        previous_report_path=args.previous_report or "",
    )
    write_json(args.output_json, review)
    write_text(args.output_md, render_monthly_review_markdown(review))


if __name__ == "__main__":
    main()

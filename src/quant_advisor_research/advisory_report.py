from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ALLOWED_CADENCES, validate_advisory_report
from .csv_utils import read_csv_rows


EVENT_WEIGHTS = {
    "public_mention": 4,
    "policy_capital": 4,
    "procurement": 4,
    "disclosure_buy": 3,
    "regulatory_action": 3,
    "market_reaction": 1,
}

BUCKET_WEIGHTS = {
    "named_mentioned": 4,
    "policy_capital": 4,
    "disclosed_holding": 2,
    "drone_policy_watchlist": 2,
    "macro_index": 1,
}

CONFIDENCE_WEIGHTS = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

AI_BIAS_WEIGHTS = {
    "positive": 3,
    "watch": 1,
    "neutral": 0,
    "avoid": -4,
    "negative": -3,
}


@dataclass(frozen=True)
class Event:
    event_id: str
    event_date: dt.date
    symbol: str
    event_type: str
    direction: str
    confidence: str
    source_url: str
    notes: str


@dataclass(frozen=True)
class WatchlistItem:
    symbol: str
    name: str
    bucket: str
    research_status: str
    thesis: str
    source_url: str


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_events(path: str | Path, as_of: dt.date) -> list[Event]:
    events: list[Event] = []
    for row in read_csv_rows(path):
        event_date = parse_date(row["event_date"])
        if event_date > as_of:
            continue
        events.append(
            Event(
                event_id=row["event_id"],
                event_date=event_date,
                symbol=row["symbol"].upper(),
                event_type=row["event_type"],
                direction=row.get("direction", ""),
                confidence=row.get("confidence", ""),
                source_url=row.get("source_url", ""),
                notes=row.get("notes", ""),
            )
        )
    return events


def load_watchlist(path: str | Path) -> dict[str, WatchlistItem]:
    items: dict[str, WatchlistItem] = {}
    for row in read_csv_rows(path):
        symbol = row["symbol"].upper()
        items[symbol] = WatchlistItem(
            symbol=symbol,
            name=row.get("name", ""),
            bucket=row.get("bucket", ""),
            research_status=row.get("research_status") or row.get("article_status", ""),
            thesis=row.get("thesis", ""),
            source_url=row.get("source_url", ""),
        )
    return items


def load_ai_signal(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("mode") != "shadow":
        raise ValueError("AI signal input must remain mode=shadow.")
    if payload.get("policy", {}).get("execution_allowed") is not False:
        raise ValueError("AI signal input must not allow execution.")
    return payload


def freshness_bonus(event_date: dt.date, as_of: dt.date) -> int:
    age_days = (as_of - event_date).days
    if age_days <= 7:
        return 2
    if age_days <= 30:
        return 1
    return 0


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def strategy_style(item: WatchlistItem | None, events: list[Event], ai_bias: str | None) -> str:
    event_types = {event.event_type for event in events}
    bucket = item.bucket if item else ""
    if event_types & {"policy_capital", "procurement", "regulatory_action", "public_mention", "disclosure_buy"}:
        return "event_driven"
    if bucket == "macro_index" or ai_bias in {"positive", "negative"}:
        return "macro_context" if ai_bias in {"negative", "avoid"} else "long_horizon_growth"
    if bucket in {"disclosed_holding", "named_mentioned"}:
        return "value_quality"
    return "mixed_research"


def horizon_fit(style: str, rating: str) -> tuple[str, list[str], str, str]:
    if rating in {"verify_source", "defer", "monitor"}:
        return "not_applicable", ["not_applicable"], "不适用", "该项不是当前推荐，仅用于来源核验、风险暂缓或持续监控。"
    if style == "event_driven":
        return "medium", ["short", "medium"], "中线", "事件驱动以中线验证为主；短线只适合观察催化反应，波动和反转风险更高。"
    if style in {"long_horizon_growth", "value_quality"}:
        return "long", ["medium", "long"], "长线", "更适合用中长期基本面和趋势验证，不适合按短线噪声频繁切换。"
    if style == "macro_context":
        return "medium", ["medium"], "中线", "宏观和政策背景更适合中线观察，需要结合市场环境复核。"
    return "medium", ["medium"], "中线", "默认按中线研究处理，等待更多证据后再调整周期判断。"


def rating_label(rating: str) -> str:
    labels = {
        "recommend": "重点推荐",
        "watch": "观察",
        "verify_source": "先核验来源",
        "defer": "暂缓",
        "monitor": "监控",
    }
    return labels[rating]


def source_confidence(events: list[Event]) -> tuple[str, str]:
    if not events:
        return "no_event", "无事件"
    levels = {event.confidence for event in events if event.confidence}
    if not levels:
        return "unknown", "未知"
    if levels == {"high"}:
        return "high", "高"
    if levels <= {"high", "medium"}:
        return "medium", "中"
    if levels == {"low"}:
        return "low", "低"
    return "mixed", "混合"


def recommendation_tier(rating: str, score: float, confidence: str) -> tuple[str, str]:
    if rating == "recommend" and score >= 0.75 and confidence in {"high", "medium"}:
        return "tier_1", "一级推荐"
    if rating == "recommend":
        return "tier_2", "二级推荐"
    if rating == "watch":
        return "watchlist", "观察名单"
    if rating == "verify_source":
        return "source_check", "来源核验"
    if rating == "defer":
        return "defer", "暂缓"
    return "monitor", "监控"


def build_recommendation(
    symbol: str,
    item: WatchlistItem | None,
    events: list[Event],
    ai_signal: dict[str, Any] | None,
    as_of: dt.date,
) -> dict[str, Any]:
    ai_bias_map = (ai_signal.get("research_bias") or ai_signal.get("candidate_bias", {})) if ai_signal else {}
    ai_bias = ai_bias_map.get(symbol)
    ai_confidence = float(ai_signal.get("confidence", 0.0)) if ai_signal else 0.0
    ai_regime = ai_signal.get("regime") if ai_signal else "unknown"

    evidence_score = BUCKET_WEIGHTS.get(item.bucket, 0) if item else 0
    risk_score = 0
    evidence_refs: list[str] = []
    risks: list[str] = []
    review_checklist: list[str] = []

    if item and item.source_url:
        evidence_refs.append(item.source_url)

    low_confidence_count = 0
    for event in events:
        evidence_score += EVENT_WEIGHTS.get(event.event_type, 0)
        evidence_score += CONFIDENCE_WEIGHTS.get(event.confidence, 0)
        evidence_score += freshness_bonus(event.event_date, as_of)
        if event.source_url:
            evidence_refs.append(event.source_url)
        if event.confidence == "low":
            low_confidence_count += 1
        if event.event_type == "market_reaction":
            risk_score += 1

    if ai_bias:
        evidence_score += AI_BIAS_WEIGHTS.get(ai_bias, 0)
        if ai_bias in {"avoid", "negative"}:
            risk_score += 4
        if ai_bias == "positive":
            evidence_score += round(ai_confidence * 2)

    risk_flags = list(ai_signal.get("risk_flags", [])) if ai_signal else []
    if any("volatility" in flag or "high_vol" in flag for flag in risk_flags):
        risk_score += 2
    if ai_regime == "risk_off":
        risk_score += 3
    elif ai_regime == "mixed":
        risk_score += 1

    if low_confidence_count:
        risk_score += low_confidence_count * 2
        risks.append("Event evidence includes low-confidence source rows that require official-source verification.")
        review_checklist.append("Verify event dates and source URLs against official filings, remarks, or issuer materials.")

    if ai_signal:
        evidence_refs.extend(ai_signal.get("evidence", {}).get("sources", []))
        data_gaps = ai_signal.get("evidence", {}).get("data_gaps", [])
        if data_gaps:
            risks.append("AI shadow context reports unresolved data gaps.")
            review_checklist.append("Review AI shadow data gaps before escalating the recommendation.")

    if ai_bias in {"avoid", "negative"}:
        rating = "defer"
    elif low_confidence_count and not any(event.confidence in {"medium", "high"} for event in events):
        rating = "verify_source"
    elif evidence_score >= 12 and risk_score <= 7:
        rating = "recommend"
    elif evidence_score >= 5:
        rating = "watch"
    else:
        rating = "monitor"

    style = strategy_style(item, events, ai_bias)
    score = round(clamp((evidence_score - risk_score + 8) / 24, 0.05, 0.85), 2)
    primary_horizon, suitable_horizons, primary_horizon_label, horizon_note = horizon_fit(style, rating)
    confidence, confidence_label = source_confidence(events)
    tier, tier_label = recommendation_tier(rating, score, confidence)

    reasons: list[str] = []
    if item and item.thesis:
        reasons.append(item.thesis)
    if events:
        event_names = ", ".join(sorted({event.event_type for event in events}))
        reasons.append(f"Observed event evidence: {event_names}.")
    if ai_bias:
        reasons.append(f"AI shadow bias is {ai_bias} with regime={ai_regime}.")
    if not reasons:
        reasons.append("No strong point-in-time evidence yet; keep as context only.")

    if not risks:
        risks.append("Recommendation may be stale without fresh market, valuation, source, and liquidity checks.")
    review_checklist.extend(
        [
            "Check latest price action, earnings calendar, valuation, and sector news.",
            "Document source quality and model limits before any separate strategy discussion.",
        ]
    )

    return {
        "symbol": symbol,
        "name": item.name if item else symbol,
        "rating": rating,
        "rating_label": rating_label(rating),
        "recommendation_tier": tier,
        "recommendation_tier_label": tier_label,
        "primary_horizon": primary_horizon,
        "primary_horizon_label": primary_horizon_label,
        "horizon_note": horizon_note,
        "suitable_horizons": suitable_horizons,
        "strategy_style": style,
        "score": score,
        "evidence_score": int(evidence_score),
        "risk_score": int(risk_score),
        "source_confidence": confidence,
        "source_confidence_label": confidence_label,
        "reasons": dedupe(reasons),
        "risk_notes": dedupe(risks),
        "evidence_summary": " ".join(reasons),
        "evidence_refs": dedupe(evidence_refs),
        "review_checklist": dedupe(review_checklist),
    }


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_advisory_report(
    *,
    as_of: str,
    cadence: str,
    political_events_path: str | Path,
    political_watchlist_path: str | Path,
    ai_signal_path: str | Path | None = None,
    max_candidates: int = 12,
) -> dict[str, Any]:
    if cadence not in ALLOWED_CADENCES:
        raise ValueError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    as_of_date = parse_date(as_of)
    watchlist = load_watchlist(political_watchlist_path)
    events = load_events(political_events_path, as_of_date)
    ai_signal = load_ai_signal(ai_signal_path)

    events_by_symbol: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        events_by_symbol[event.symbol].append(event)

    symbols = set(watchlist) | set(events_by_symbol)
    if ai_signal:
        symbols |= {symbol.upper() for symbol in ai_signal.get("universe", [])}
        ai_bias_symbols = ai_signal.get("research_bias") or ai_signal.get("candidate_bias", {})
        symbols |= {symbol.upper() for symbol in ai_bias_symbols}

    recommendations = [
        build_recommendation(
            symbol=symbol,
            item=watchlist.get(symbol),
            events=sorted(events_by_symbol.get(symbol, []), key=lambda event: event.event_date),
            ai_signal=ai_signal,
            as_of=as_of_date,
        )
        for symbol in sorted(symbols)
    ]
    recommendations.sort(key=lambda rec: (-rec["evidence_score"], rec["risk_score"], rec["symbol"]))
    recommendations = recommendations[:max_candidates]

    report = {
        "schema_version": "4",
        "as_of": as_of_date.isoformat(),
        "generated_at": utc_now_iso(),
        "mode": "model_recommendations",
        "cadence": cadence,
        "audience_scope": "non_personalized_model_research",
        "source_artifacts": {
            "political_events": str(political_events_path),
            "political_watchlist": str(political_watchlist_path),
            "ai_signal": str(ai_signal_path) if ai_signal_path else "",
        },
        "summary": {
            "recommendation_count": len(recommendations),
            "source_event_count": len(events),
            "ai_regime": ai_signal.get("regime", "not_available") if ai_signal else "not_available",
            "ai_confidence": ai_signal.get("confidence", 0.0) if ai_signal else 0.0,
            "top_recommended_symbols": [rec["symbol"] for rec in recommendations if rec["recommendation_tier"] == "tier_1"][:5],
            "review_note": "Non-personalized model recommendations. No order, target quantity, account suitability, or portfolio allocation is encoded.",
        },
        "recommendations": recommendations,
        "policy": {
            "non_personalized_recommendations_allowed": True,
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "personalized_advice_allowed": False,
            "account_specific_advice_allowed": False,
            "downstream_use": "Model recommendation research only; do not route to broker execution or account-level allocation.",
        },
    }
    validate_advisory_report(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Quant Model Recommendations {report['cadence'].title()} Review",
        "",
        f"- As of: `{report['as_of']}`",
        f"- Mode: `{report['mode']}`",
        f"- Audience: `{report['audience_scope']}`",
        f"- AI regime: `{report['summary']['ai_regime']}`",
        "",
        "## Policy",
        "",
        "- Execution allowed: `false`",
        "- Portfolio allocation allowed: `false`",
        "- Personalized advice allowed: `false`",
        "- Non-personalized recommendations allowed: `true`",
        "- Account-specific advice allowed: `false`",
        "",
        "## 推荐列表",
        "",
    ]
    for rec in report["recommendations"]:
        lines.extend(
            [
                f"### {rec['symbol']} - {rec['rating_label']}",
                "",
                f"- 推荐层级: `{rec['recommendation_tier_label']}`",
                f"- 适合周期: `{rec['primary_horizon_label']}`",
                f"- 周期说明: {rec['horizon_note']}",
                f"- Strategy style: `{rec['strategy_style']}`",
                f"- Model score: `{rec['score']}`",
                f"- Source confidence: `{rec['source_confidence_label']}`",
                f"- Evidence score: `{rec['evidence_score']}`",
                f"- Risk score: `{rec['risk_score']}`",
                "- 理由:",
            ]
        )
        lines.extend(f"  - {reason}" for reason in rec["reasons"])
        lines.append("- 风险:")
        lines.extend(f"  - {risk}" for risk in rec["risk_notes"])
        lines.append("- 复核清单:")
        lines.extend(f"  - {check}" for check in rec["review_checklist"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_text(path: str | Path, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a non-personalized model recommendation report.")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--cadence", required=True, choices=sorted(ALLOWED_CADENCES))
    parser.add_argument("--political-events", required=True, help="Political event CSV.")
    parser.add_argument("--political-watchlist", required=True, help="Political watchlist CSV.")
    parser.add_argument("--ai-signal", help="Saved AI shadow signal JSON.")
    parser.add_argument("--max-items", "--max-candidates", dest="max_candidates", type=int, default=12)
    parser.add_argument("--output-json", required=True, help="Output JSON artifact path.")
    parser.add_argument("--output-md", required=True, help="Output Markdown report path.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    report = build_advisory_report(
        as_of=args.as_of,
        cadence=args.cadence,
        political_events_path=args.political_events,
        political_watchlist_path=args.political_watchlist,
        ai_signal_path=args.ai_signal,
        max_candidates=args.max_candidates,
    )
    write_json(args.output_json, report)
    write_text(args.output_md, render_markdown(report))


if __name__ == "__main__":
    main()

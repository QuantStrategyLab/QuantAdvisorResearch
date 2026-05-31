from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import write_report_manifest
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

HORIZON_WINDOWS = {
    "short": "1-10个交易日",
    "medium": "2-12周",
    "long": "1-3年",
    "not_applicable": "不适用",
}

CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}

SECTOR_LABELS_ZH = {
    "technology": "科技",
    "energy": "能源",
    "financials": "金融",
    "healthcare": "医疗",
    "industrials": "工业",
    "consumer": "消费",
    "consumer_discretionary": "可选消费",
    "communication_services": "通信服务",
    "utilities": "公用事业",
}

THEME_LABELS_ZH = {
    "ai_compute": "AI 算力平台",
    "hbm_memory": "HBM / 存储",
    "foundry_semicap": "晶圆代工 / 半导体设备",
    "ai_server_infrastructure": "AI 服务器 / 数据中心硬件",
    "data_center_power": "数据中心电力与冷却",
    "cybersecurity": "企业网络安全",
    "defense_aerospace": "国防与航空航天",
    "energy_security": "能源安全 / 油气",
    "clean_energy_grid": "清洁能源 / 电网",
    "financial_market_infrastructure": "金融与市场基础设施",
    "healthcare_policy": "医疗政策 / 管理式医疗",
    "consumer_platforms": "消费平台 / 广告",
    "industrial_automation": "工业自动化 / 回流制造",
    "crypto_infrastructure": "加密资产基础设施",
    "automobility_ev": "汽车智能化 / EV 转型",
}

COMPANY_PROFILES_ZH = {
    "AMD": {
        "business": "AMD 主要做 CPU、GPU、AI 加速器和数据中心芯片。",
        "prospect": "前景主要来自 AI 加速器放量、数据中心服务器更新，以及与 NVIDIA 之外第二供应商相关的需求。",
    },
    "AVGO": {
        "business": "Broadcom 主要做网络芯片、定制 ASIC、半导体连接方案和企业软件。",
        "prospect": "前景主要来自 AI 数据中心网络、定制加速芯片、云厂商资本开支和软件现金流。",
    },
    "COIN": {
        "business": "Coinbase 是美国主要加密资产交易和托管平台。",
        "prospect": "前景主要取决于数字资产监管清晰度、交易活跃度和机构托管需求。",
    },
    "CVX": {
        "business": "Chevron 是综合油气公司，覆盖上游勘探生产、炼化和天然气业务。",
        "prospect": "前景主要来自能源安全、油气供给约束、现金流和股东回报能力。",
    },
    "DELL": {
        "business": "Dell 主要做企业服务器、存储、PC 和 AI 服务器基础设施。",
        "prospect": "前景主要来自 AI 服务器、企业基础设施更新和数据中心资本开支。",
    },
    "INTC": {
        "business": "Intel 主要做 CPU、数据中心芯片、制造工艺和晶圆代工。",
        "prospect": "前景主要来自美国本土半导体制造、CHIPS Act、代工恢复和 AI PC / 数据中心需求。",
    },
    "MSTR": {
        "business": "Strategy 经营企业软件业务，同时持有大量比特币资产。",
        "prospect": "前景主要取决于比特币价格、资本市场融资能力和数字资产监管环境。",
    },
    "MU": {
        "business": "Micron 主要做 DRAM、NAND 和 HBM 等存储芯片。",
        "prospect": "前景主要来自 AI 服务器对 HBM 和高端 DRAM 的需求，以及存储周期修复。",
    },
    "NEE": {
        "business": "NextEra Energy 是美国大型电力公用事业和可再生能源公司。",
        "prospect": "前景主要来自电网投资、数据中心用电增长、可再生能源和储能项目需求。",
    },
    "TSM": {
        "business": "台积电是全球领先晶圆代工厂，服务 AI、手机、高性能计算和汽车芯片客户。",
        "prospect": "前景主要来自先进制程、AI 芯片代工需求和长期半导体外包趋势。",
    },
    "VRT": {
        "business": "Vertiv 主要做数据中心电源、散热、机柜和关键基础设施设备。",
        "prospect": "前景主要来自 AI 数据中心建设、电力密度提升、液冷和供电基础设施升级。",
    },
    "XOM": {
        "business": "Exxon Mobil 是综合油气公司，覆盖上游生产、炼化、化工和 LNG。",
        "prospect": "前景主要来自能源安全、LNG 需求、油气供给约束和长期现金流。",
    },
}

EXCLUDED_THEME_PICK_SYMBOLS = {
    "DIA",
    "IWM",
    "QQQ",
    "SMH",
    "SOXL",
    "SOXX",
    "SPY",
    "TQQQ",
    "XLE",
    "XLK",
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



def load_theme_momentum(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("mode") != "theme_momentum_snapshot":
        raise ValueError("Theme momentum input must remain mode=theme_momentum_snapshot.")
    if payload.get("policy", {}).get("execution_allowed") is not False:
        raise ValueError("Theme momentum input must not allow execution.")
    return payload


def summarize_theme_momentum(payload: dict[str, Any] | None, *, max_themes: int = 5) -> dict[str, Any]:
    if not payload:
        return {"available": False, "top_themes": [], "data_quality": {}}
    top_themes: list[dict[str, Any]] = []
    for theme in list(payload.get("theme_ranks", []))[:max_themes]:
        if not isinstance(theme, dict):
            continue
        top_symbols = []
        for item in list(theme.get("top_symbols", []))[:5]:
            if isinstance(item, dict) and item.get("symbol"):
                top_symbols.append(str(item["symbol"]).upper())
        top_themes.append(
            {
                "rank": theme.get("rank"),
                "theme_id": theme.get("theme_id", ""),
                "theme_name": theme.get("theme_name", ""),
                "sector": theme.get("sector", ""),
                "momentum_score": theme.get("momentum_score"),
                "breadth_3m": theme.get("breadth_3m"),
                "top_symbols": top_symbols,
            }
        )
    return {
        "available": True,
        "as_of": payload.get("as_of", ""),
        "taxonomy_version": payload.get("taxonomy_version", ""),
        "top_themes": top_themes,
        "data_quality": payload.get("data_quality", {}),
        "policy": {
            "execution_allowed": False,
            "theme_rank_is_research_context_only": True,
        },
    }


def as_float(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def display_number(value: Any, *, digits: int = 2) -> str:
    if value in {None, ""}:
        return "无"
    return f"{as_float(value):.{digits}f}"


def display_percent(value: Any, *, digits: int = 1) -> str:
    if value in {None, ""}:
        return "无"
    return f"{as_float(value) * 100:+.{digits}f}%"


def sector_label(value: Any) -> str:
    text = str(value or "").strip()
    return SECTOR_LABELS_ZH.get(text, text or "未分类")


def theme_label(theme_id: Any, theme_name: Any = "") -> str:
    theme_key = str(theme_id or "").strip()
    fallback = str(theme_name or "").strip()
    return THEME_LABELS_ZH.get(theme_key, fallback or theme_key or "未分类主题")


def event_evidence_label(confidence: Any) -> str:
    labels = {
        "high": "已有高置信来源事件",
        "medium": "已有中等置信来源事件",
        "mixed": "已有混合置信来源事件",
        "low": "仅低置信来源事件，需先核验",
        "unknown": "事件来源置信度待核验",
        "no_event": "暂无明确事件催化",
    }
    return labels.get(str(confidence or "").strip(), "暂无明确事件催化")


def company_profile(symbol: Any, name: Any = "") -> dict[str, str]:
    symbol_text = str(symbol or "").upper()
    profile = COMPANY_PROFILES_ZH.get(symbol_text)
    if profile:
        return profile
    display_name = str(name or symbol_text).strip() or symbol_text
    return {
        "business": f"{display_name}（{symbol_text}）为当前观察股票池标的。",
        "prospect": "推荐理由需要结合行业需求、公司财报、估值和价格趋势继续复核。",
    }


def normalize_ai_mapping(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {str(key).upper(): value for key, value in mapping.items()}


def aggregate_theme_bias(values: list[str]) -> str | None:
    if not values:
        return None
    if "avoid" in values:
        return "avoid"
    if "negative" in values:
        return "negative"
    if "positive" in values:
        return "positive"
    if "watch" in values:
        return "watch"
    if "neutral" in values:
        return "neutral"
    return None


def resolve_ai_bias(symbol: str, ai_signal: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    if not ai_signal:
        return None, []
    normalized_symbol = symbol.upper()
    explicit_bias = normalize_ai_mapping(ai_signal.get("research_bias") or ai_signal.get("candidate_bias", {}))
    if normalized_symbol in explicit_bias:
        return str(explicit_bias[normalized_symbol]), []

    theme_bias = {str(theme): str(bias) for theme, bias in dict(ai_signal.get("theme_bias") or {}).items()}
    raw_exposure = normalize_ai_mapping(ai_signal.get("symbol_theme_exposure") or {})
    theme_ids = raw_exposure.get(normalized_symbol, [])
    if isinstance(theme_ids, str):
        theme_ids = [theme_ids]
    if not isinstance(theme_ids, list):
        return None, []
    matched_biases = [theme_bias[theme_id] for theme_id in theme_ids if theme_id in theme_bias]
    return aggregate_theme_bias(matched_biases), [theme_id for theme_id in theme_ids if theme_id in theme_bias]

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
        return "not_applicable", ["not_applicable"], "不适用", "该项不是当前推荐，仅用于来源核验、风险暂缓或背景跟踪。"
    if style == "event_driven":
        return "medium", ["short", "medium"], "中线", "事件驱动主周期为2-12周；1-10个交易日只适合观察催化反应，波动和反转风险更高。"
    if style in {"long_horizon_growth", "value_quality"}:
        return "long", ["medium", "long"], "长线", "主周期为1-3年，更适合用基本面、产业趋势和事件持续性验证；超过3年需要年度复盘确认逻辑仍成立。"
    if style == "macro_context":
        return "medium", ["medium"], "中线", "主周期为2-12周，宏观和政策背景需要结合市场环境复核。"
    return "medium", ["medium"], "中线", "默认按2-12周中线研究处理，等待更多证据后再调整周期判断。"


def rating_label(rating: str) -> str:
    labels = {
        "recommend": "重点推荐",
        "watch": "观察",
        "verify_source": "先核验来源",
        "defer": "暂缓",
        "monitor": "背景跟踪",
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
    return "monitor", "背景跟踪"


def build_theme_first_candidates(
    theme_momentum: dict[str, Any] | None,
    recommendations: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
    max_themes: int = 5,
) -> list[dict[str, Any]]:
    if not theme_momentum:
        return []

    rec_by_symbol = {str(rec.get("symbol", "")).upper(): rec for rec in recommendations}
    by_symbol: dict[str, dict[str, Any]] = {}
    for theme in list(theme_momentum.get("theme_ranks", []))[:max_themes]:
        if not isinstance(theme, dict):
            continue
        theme_rank = int(as_float(theme.get("rank"), default=999))
        theme_id = str(theme.get("theme_id", ""))
        theme_name = str(theme.get("theme_name", ""))
        theme_sector = str(theme.get("sector", ""))
        theme_score = round(as_float(theme.get("momentum_score")), 6)
        theme_breadth = round(as_float(theme.get("breadth_3m")), 6)
        for item in theme.get("top_symbols", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            if symbol in EXCLUDED_THEME_PICK_SYMBOLS:
                continue
            symbol_score = round(as_float(item.get("momentum_score")), 6)
            candidate = by_symbol.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": rec_by_symbol.get(symbol, {}).get("name", symbol),
                    "candidate_type": "theme_first",
                    "symbol_momentum_score": symbol_score,
                    "return_3m": item.get("return_3m"),
                    "return_6_1m": item.get("return_6_1m"),
                    "return_12_1m": item.get("return_12_1m"),
                    "best_theme_rank": theme_rank,
                    "primary_theme_id": theme_id,
                    "primary_theme_name": theme_name,
                    "primary_theme_sector": theme_sector,
                    "primary_theme_score": theme_score,
                    "primary_theme_breadth_3m": theme_breadth,
                    "theme_ids": [],
                    "themes": [],
                },
            )
            if symbol_score > as_float(candidate.get("symbol_momentum_score")):
                candidate["symbol_momentum_score"] = symbol_score
                candidate["return_3m"] = item.get("return_3m")
                candidate["return_6_1m"] = item.get("return_6_1m")
                candidate["return_12_1m"] = item.get("return_12_1m")
            if theme_rank < int(candidate.get("best_theme_rank", 999)):
                candidate["best_theme_rank"] = theme_rank
                candidate["primary_theme_id"] = theme_id
                candidate["primary_theme_name"] = theme_name
                candidate["primary_theme_sector"] = theme_sector
                candidate["primary_theme_score"] = theme_score
                candidate["primary_theme_breadth_3m"] = theme_breadth
            if theme_id and theme_id not in candidate["theme_ids"]:
                candidate["theme_ids"].append(theme_id)
                candidate["themes"].append(
                    {
                        "theme_id": theme_id,
                        "theme_name": theme_name,
                        "sector": theme_sector,
                        "rank": theme_rank,
                        "momentum_score": theme_score,
                        "breadth_3m": theme_breadth,
                    }
                )

    candidates = list(by_symbol.values())
    candidates.sort(
        key=lambda item: (
            -as_float(item.get("symbol_momentum_score")),
            int(item.get("best_theme_rank", 999)),
            str(item.get("symbol", "")),
        )
    )

    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:max_candidates], start=1):
        symbol = str(candidate["symbol"])
        rec = rec_by_symbol.get(symbol)
        advisor_status = "主题候选"
        source_confidence = str(rec.get("source_confidence", "no_event")) if rec else "no_event"
        source_confirmation = event_evidence_label(source_confidence)
        if rec:
            if rec.get("recommendation_tier") != "monitor":
                advisor_status = rec.get("recommendation_tier_label") or rec.get("rating_label") or advisor_status
        theme_ids = candidate.get("theme_ids", [])
        theme_name_by_id = {
            str(theme.get("theme_id", "")): str(theme.get("theme_name", ""))
            for theme in candidate.get("themes", [])
            if isinstance(theme, dict)
        }
        theme_labels = [theme_label(theme_id, theme_name_by_id.get(str(theme_id), "")) for theme_id in theme_ids]
        primary_theme_label = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
        reasons = [
            "主题和个股动量靠前，适合放入本期主题优先候选池。",
            (
                f"主主题 #{candidate.get('best_theme_rank')} {primary_theme_label} "
                f"主题分数={candidate.get('primary_theme_score')}，3个月广度={candidate.get('primary_theme_breadth_3m')}。"
            ),
            f"个股动量分数={candidate.get('symbol_momentum_score')}。",
        ]
        if len(theme_labels) > 1:
            reasons.append(f"同时暴露于多个强主题：{', '.join(theme_labels)}。")
        industry_background = (
            f"{sector_label(candidate.get('primary_theme_sector'))} / "
            f"{primary_theme_label}"
        )
        recommendation_summary = (
            f"属于{industry_background}，主主题排名 #{candidate.get('best_theme_rank')}；"
            f"个股动量 {display_number(candidate.get('symbol_momentum_score'))}，"
            f"近3个月 {display_percent(candidate.get('return_3m'))}。"
        )
        if len(theme_labels) > 1:
            recommendation_summary += f" 同时覆盖 {', '.join(theme_labels[:3])} 等主题。"
        risk_summary = "需复核估值、财报、回撤和流动性；当前暂无明确事件催化。"
        if source_confidence in {"high", "medium", "mixed"}:
            risk_summary = "已有来源事件，但仍需复核估值、财报、回撤和流动性。"
        elif source_confidence == "low":
            risk_summary = "事件来源置信度偏低，需先核验来源，再评估是否升级。"
        risk_notes = [
            "该候选来自主题和价格动量排序，不代表个性化建议或下单信号。",
            risk_summary,
        ]
        if rec and rec.get("risk_notes"):
            risk_notes.append(str(rec["risk_notes"][0]))
        result.append(
            {
                **candidate,
                "rank": index,
                "advisor_status": advisor_status,
                "source_confirmation": source_confirmation,
                "industry_background": industry_background,
                "recommendation_summary": recommendation_summary,
                "risk_summary": risk_summary,
                "reasons": dedupe(reasons),
                "risk_notes": dedupe(risk_notes),
            }
        )
    return result


def build_recommendation(
    symbol: str,
    item: WatchlistItem | None,
    events: list[Event],
    ai_signal: dict[str, Any] | None,
    as_of: dt.date,
) -> dict[str, Any]:
    ai_bias, ai_bias_source_themes = resolve_ai_bias(symbol, ai_signal)
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
        risks.append("事件证据包含低置信来源行，需要用官方来源复核。")
        review_checklist.append("对照官方公告、披露文件、讲话或公司材料复核事件日期和来源链接。")

    if ai_signal:
        evidence_refs.extend(ai_signal.get("evidence", {}).get("sources", []))
        data_gaps = ai_signal.get("evidence", {}).get("data_gaps", [])
        if data_gaps:
            risks.append("AI 长周期背景仍有未解决的数据缺口。")
            review_checklist.append("升级推荐前先复核 AI 长周期背景中的数据缺口。")

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
    primary_horizon_window = HORIZON_WINDOWS[primary_horizon]
    suitable_horizon_windows = {horizon: HORIZON_WINDOWS[horizon] for horizon in suitable_horizons}
    confidence, confidence_label = source_confidence(events)
    tier, tier_label = recommendation_tier(rating, score, confidence)

    reasons: list[str] = []
    if item and item.thesis:
        reasons.append(item.thesis)
    if events:
        event_names = ", ".join(sorted({event.event_type for event in events}))
        reasons.append(f"观察到事件证据：{event_names}。")
    if ai_bias:
        if ai_bias_source_themes:
            reasons.append(
                f"AI 长周期主题偏向为 {ai_bias}，市场状态={ai_regime}；主题={', '.join(ai_bias_source_themes)}。"
            )
        else:
            reasons.append(f"AI 长周期偏向为 {ai_bias}，市场状态={ai_regime}。")
    if not reasons:
        reasons.append("尚无足够强的时点证据，暂时只作为研究背景。")

    if not risks:
        risks.append("如果缺少最新价格、估值、来源和流动性检查，推荐结论可能失效。")
    review_checklist.extend(
        [
            "检查最新价格走势、财报日、估值和行业新闻。",
            "单独讨论策略前，记录来源质量和模型边界。",
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
        "primary_horizon_window": primary_horizon_window,
        "horizon_note": horizon_note,
        "suitable_horizons": suitable_horizons,
        "suitable_horizon_windows": suitable_horizon_windows,
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


def source_mode_for_paths(*paths: str | Path | None) -> tuple[str, list[str]]:
    text = " ".join(str(path or "") for path in paths)
    warnings: list[str] = []
    if "/examples/" in text or text.startswith("examples/") or " example" in text:
        warnings.append("Input artifacts include example fixture paths; do not treat this report as live recommendations.")
    return ("fixture", warnings) if warnings else ("operator_supplied", warnings)


def normalize_source_score(rec: dict[str, Any] | None) -> float:
    if not rec:
        return 0.0
    confidence_scores = {
        "high": 1.0,
        "medium": 0.75,
        "mixed": 0.55,
        "low": 0.25,
        "unknown": 0.1,
        "no_event": 0.0,
    }
    tier_scores = {
        "tier_1": 1.0,
        "tier_2": 0.85,
        "watchlist": 0.6,
        "source_check": 0.25,
        "defer": 0.0,
        "monitor": 0.0,
    }
    evidence_component = clamp(as_float(rec.get("evidence_score")) / 18, 0, 1)
    confidence_component = confidence_scores.get(str(rec.get("source_confidence", "")), 0.0)
    blended = evidence_component * 0.65 + confidence_component * 0.35
    return round(max(blended, tier_scores.get(str(rec.get("recommendation_tier", "")), 0.0)), 3)


def theme_symbol_context(theme_momentum: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not theme_momentum:
        return {}
    theme_ranks = [theme for theme in theme_momentum.get("theme_ranks", []) if isinstance(theme, dict)]
    total_themes = max(len(theme_ranks), 1)
    contexts: dict[str, dict[str, Any]] = {}
    for theme in theme_ranks:
        theme_id = str(theme.get("theme_id", ""))
        theme_name = str(theme.get("theme_name", ""))
        rank = int(as_float(theme.get("rank"), default=total_themes))
        rank_score = clamp((total_themes - min(rank, total_themes) + 1) / total_themes, 0, 1)
        theme_score = clamp(as_float(theme.get("momentum_score")) / 2, 0, 1)
        ai_signal_score = round(rank_score * 0.65 + theme_score * 0.35, 3)
        for item in theme.get("top_symbols", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            if symbol in EXCLUDED_THEME_PICK_SYMBOLS:
                continue
            symbol_momentum_score = round(as_float(item.get("momentum_score")), 6)
            momentum_score = round(clamp(symbol_momentum_score / 1.5, 0, 1), 3)
            return_3m = item.get("return_3m")
            current = contexts.setdefault(
                symbol,
                {
                    "theme_ids": [],
                    "theme_labels": [],
                    "primary_theme_id": theme_id,
                    "primary_theme_label": theme_label(theme_id, theme_name),
                    "best_theme_rank": rank,
                    "ai_signal_score": ai_signal_score,
                    "symbol_momentum_score": symbol_momentum_score,
                    "momentum_score": momentum_score,
                    "return_3m": return_3m,
                },
            )
            if theme_id and theme_id not in current["theme_ids"]:
                current["theme_ids"].append(theme_id)
                current["theme_labels"].append(theme_label(theme_id, theme_name))
            if rank < int(current.get("best_theme_rank", total_themes + 1)):
                current["primary_theme_id"] = theme_id
                current["primary_theme_label"] = theme_label(theme_id, theme_name)
                current["best_theme_rank"] = rank
            if ai_signal_score > as_float(current.get("ai_signal_score")):
                current["ai_signal_score"] = ai_signal_score
            if momentum_score > as_float(current.get("momentum_score")):
                current["symbol_momentum_score"] = symbol_momentum_score
                current["momentum_score"] = momentum_score
                current["return_3m"] = return_3m
    return contexts


def final_action_for(
    rec: dict[str, Any] | None,
    combined_score: float,
    support_count: int,
    momentum_score: float,
    ai_signal_score: float,
) -> str:
    theme_and_momentum_confirmed = momentum_score >= 0.35 and ai_signal_score >= 0.35
    if combined_score >= 0.52 and theme_and_momentum_confirmed:
        return "recommend"
    if (
        rec
        and rec.get("recommendation_tier") in {"tier_1", "tier_2"}
        and combined_score >= 0.45
        and (theme_and_momentum_confirmed or momentum_score >= 0.35 or ai_signal_score >= 0.35)
    ):
        return "recommend"
    if rec and rec.get("recommendation_tier") in {"watchlist", "source_check"}:
        return "watch"
    if combined_score >= 0.35 and support_count >= 2:
        return "watch"
    return "skip"


def final_action_label(action: str) -> str:
    return {
        "recommend": "最终推荐",
        "watch": "观察名单",
    }.get(action, "跳过")


def build_final_decisions(
    recommendations: list[dict[str, Any]],
    theme_momentum: dict[str, Any] | None,
    *,
    max_recommendations: int = 5,
    max_watchlist: int = 8,
) -> dict[str, Any]:
    rec_by_symbol = {str(rec.get("symbol", "")).upper(): rec for rec in recommendations}
    theme_context = theme_symbol_context(theme_momentum)
    symbols = sorted(set(rec_by_symbol) | set(theme_context))
    picks: list[dict[str, Any]] = []

    for symbol in symbols:
        rec = rec_by_symbol.get(symbol)
        theme = theme_context.get(symbol, {})
        source_score = normalize_source_score(rec)
        momentum_score = as_float(theme.get("momentum_score"))
        ai_signal_score = as_float(theme.get("ai_signal_score"))
        support_count = sum(score >= 0.35 for score in (source_score, momentum_score, ai_signal_score))
        combined_score = round(source_score * 0.15 + momentum_score * 0.40 + ai_signal_score * 0.45, 3)
        action = final_action_for(rec, combined_score, support_count, momentum_score, ai_signal_score)
        if action == "skip":
            continue
        name = rec.get("name", symbol) if rec else symbol
        profile = company_profile(symbol, name)
        reasons: list[str] = []
        if source_score >= 0.35 and rec:
            reasons.append(
                f"政策/新闻：{rec.get('source_confidence_label')}置信来源，证据分数={rec.get('evidence_score')}。"
            )
        if momentum_score >= 0.35:
            reasons.append(
                f"动量：个股动量分数={display_number(theme.get('symbol_momentum_score'))}，近3个月={display_percent(theme.get('return_3m'))}。"
            )
        if ai_signal_score >= 0.35:
            labels = ", ".join(theme.get("theme_labels", [])[:3]) or str(theme.get("primary_theme_label", ""))
            reasons.append(f"AI信号仓库：{labels}。")
        if not reasons:
            reasons.append("当前进入观察名单，但多源证据仍需继续补强。")
        if rec and rec.get("primary_horizon") != "not_applicable":
            primary_horizon = rec.get("primary_horizon", "long")
            primary_horizon_label = rec.get("primary_horizon_label", "长线")
            primary_horizon_window = rec.get("primary_horizon_window", HORIZON_WINDOWS["long"])
        elif momentum_score >= 0.35:
            primary_horizon = "medium"
            primary_horizon_label = "中线"
            primary_horizon_window = HORIZON_WINDOWS["medium"]
        else:
            primary_horizon = "long"
            primary_horizon_label = "长线"
            primary_horizon_window = HORIZON_WINDOWS["long"]
        picks.append(
            {
                "symbol": symbol,
                "name": name,
                "action": action,
                "action_label": final_action_label(action),
                "primary_horizon": primary_horizon,
                "primary_horizon_label": primary_horizon_label,
                "primary_horizon_window": primary_horizon_window,
                "combined_score": combined_score,
                "source_score": round(source_score, 3),
                "momentum_score": round(momentum_score, 3),
                "ai_signal_score": round(ai_signal_score, 3),
                "business_summary": profile["business"],
                "prospect_summary": profile["prospect"],
                "why_selected": dedupe(reasons),
                "risk_summary": rec.get("risk_notes", ["需复核估值、财报、回撤和流动性。"])[0] if rec else "需复核估值、财报、回撤和流动性。",
            }
        )

    picks.sort(
        key=lambda item: (
            0 if item["action"] == "recommend" else 1,
            -as_float(item.get("combined_score")),
            str(item.get("symbol", "")),
        )
    )
    recommendation_candidates = [item for item in picks if item["action"] == "recommend"]
    recommendations_out = recommendation_candidates[:max_recommendations]
    recommendation_symbols = {item["symbol"] for item in recommendations_out}
    watchlist_out = [
        item
        for item in picks
        if item["action"] == "watch" or (item["action"] == "recommend" and item["symbol"] not in recommendation_symbols)
    ][:max_watchlist]
    horizon_buckets = {
        horizon: [item["symbol"] for item in recommendations_out if item.get("primary_horizon") == horizon]
        for horizon in ("short", "medium", "long")
    }
    return {
        "method": "AiLongHorizonSignalPipelines signal and price momentum first; policy/news evidence is a confidence and risk modifier",
        "recommendations": recommendations_out,
        "watchlist": watchlist_out,
        "horizon_buckets": horizon_buckets,
        "position_policy": "No target shares, position size, portfolio weight, or account-specific allocation is provided.",
    }


def build_advisory_report(
    *,
    as_of: str,
    cadence: str,
    political_events_path: str | Path,
    political_watchlist_path: str | Path,
    ai_signal_path: str | Path | None = None,
    theme_momentum_path: str | Path | None = None,
    max_candidates: int = 12,
) -> dict[str, Any]:
    if cadence not in ALLOWED_CADENCES:
        raise ValueError(f"cadence must be one of: {', '.join(sorted(ALLOWED_CADENCES))}")
    as_of_date = parse_date(as_of)
    watchlist = load_watchlist(political_watchlist_path)
    events = load_events(political_events_path, as_of_date)
    ai_signal = load_ai_signal(ai_signal_path)
    theme_momentum = load_theme_momentum(theme_momentum_path)
    theme_momentum_summary = summarize_theme_momentum(theme_momentum)
    source_mode, data_quality_warnings = source_mode_for_paths(
        political_events_path,
        political_watchlist_path,
        ai_signal_path,
        theme_momentum_path,
    )

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
    theme_first_candidates = build_theme_first_candidates(theme_momentum, recommendations)
    final_decisions = build_final_decisions(recommendations, theme_momentum)

    report = {
        "schema_version": "5",
        "as_of": as_of_date.isoformat(),
        "generated_at": utc_now_iso(),
        "mode": "model_recommendations",
        "cadence": cadence,
        "audience_scope": "non_personalized_model_research",
        "source_artifacts": {
            "political_events": str(political_events_path),
            "political_watchlist": str(political_watchlist_path),
            "ai_signal": str(ai_signal_path) if ai_signal_path else "",
            "theme_momentum": str(theme_momentum_path) if theme_momentum_path else "",
        },
        "summary": {
            "recommendation_count": len(recommendations),
            "source_event_count": len(events),
            "ai_regime": ai_signal.get("regime", "not_available") if ai_signal else "not_available",
            "ai_confidence": ai_signal.get("confidence", 0.0) if ai_signal else 0.0,
            "source_mode": source_mode,
            "data_quality_warnings": data_quality_warnings,
            "theme_momentum_available": theme_momentum_summary["available"],
            "top_theme_ids": [theme["theme_id"] for theme in theme_momentum_summary["top_themes"]],
            "theme_first_candidate_count": len(theme_first_candidates),
            "top_theme_candidate_symbols": [item["symbol"] for item in theme_first_candidates[:8]],
            "top_recommended_symbols": [item["symbol"] for item in final_decisions["recommendations"][:5]],
            "review_note": "Non-personalized model recommendations. No order, target quantity, account suitability, or portfolio allocation is encoded.",
        },
        "recommendations": recommendations,
        "final_decisions": final_decisions,
        "theme_first_candidates": theme_first_candidates,
        "theme_momentum": theme_momentum_summary,
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
    cadence_label = CADENCE_LABELS_ZH.get(str(report["cadence"]), str(report["cadence"]).title())
    lines = [
        f"# 量化模型推荐{cadence_label}复盘",
        "",
        f"- 日期: `{report['as_of']}`",
        f"- 模式: `{report['mode']}`",
        f"- 受众: `{report['audience_scope']}`",
        f"- AI 状态: `{report['summary']['ai_regime']}`",
        "",
        "## 政策边界",
        "",
        "- 允许下单: `false`",
        "- 允许组合配置: `false`",
        "- 允许个性化建议: `false`",
        "- 允许非个性化模型推荐: `true`",
        "- 允许账户级建议: `false`",
        "",
    ]
    final_decisions = report.get("final_decisions", {})
    if final_decisions:
        lines.extend(["## 本期最终结论", ""])
        lines.append("- 口径: 以 AI信号仓库（AiLongHorizonSignalPipelines）和动量为主，政策/新闻事件用于提高置信度和提示风险。")
        horizon_buckets = final_decisions.get("horizon_buckets", {})
        for horizon, label in (("short", "短线"), ("medium", "中线"), ("long", "长线")):
            symbols = ", ".join(horizon_buckets.get(horizon, [])) or "暂无最终推荐"
            lines.append(f"- {label}({HORIZON_WINDOWS[horizon]}): {symbols}")
        lines.append("")
        for pick in final_decisions.get("recommendations", []):
            lines.extend(
                [
                    f"### {pick.get('symbol')} - {pick.get('action_label')}",
                    "",
                    f"- 周期: {pick.get('primary_horizon_label')}({pick.get('primary_horizon_window')})",
                    f"- 股票背景: {pick.get('business_summary')}",
                    f"- 推荐理由: {pick.get('prospect_summary')}",
                    "- 多源依据:",
                ]
            )
            lines.extend(f"  - {reason}" for reason in pick.get("why_selected", []))
            lines.extend(
                [
                    f"- 主要风险: {pick.get('risk_summary')}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"
    theme_candidates = report.get("theme_first_candidates", [])
    if theme_candidates:
        lines.extend(["## 主题候选（解释材料，不是最终推荐）", ""])
        lines.append("- 先看这里: 每期选出 5-10 个股票/公司标的，说明行业主题、入选理由、事件证据和主要风险。")
        lines.append("- 边界: 这是非个性化模型股票池，不是买入清单；`暂无明确事件催化` 表示该标的主要来自主题/动量排序。")
        lines.append("")
        for candidate in theme_candidates:
            primary_theme_label = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
            lines.extend(
                [
                    f"### #{candidate.get('rank')} {candidate.get('symbol')} - {candidate.get('advisor_status')}",
                    "",
                    f"- 行业/主题: {candidate.get('industry_background')}",
                    f"- 主主题: {primary_theme_label}",
                    f"- 个股动量分数: `{display_number(candidate.get('symbol_momentum_score'))}`",
                    f"- 近3个月: `{display_percent(candidate.get('return_3m'))}`",
                    f"- 事件证据: `{candidate.get('source_confirmation')}`",
                    f"- 为什么入选: {candidate.get('recommendation_summary')}",
                    f"- 主要风险: {candidate.get('risk_summary')}",
                ]
            )
            lines.append("")
    theme_momentum = report.get("theme_momentum", {})
    if theme_momentum.get("available"):
        lines.extend(["## 主题动量", ""])
        lines.append(f"- 快照日期: `{theme_momentum.get('as_of', '')}`")
        lines.append(f"- 主题版本: `{theme_momentum.get('taxonomy_version', '')}`")
        lines.append("- 注意: 主题动量只用于研究排序和候选展示，不直接改变推荐评级。")
        lines.append("")
        for theme in theme_momentum.get("top_themes", []):
            symbols = ", ".join(theme.get("top_symbols", [])) or "无"
            lines.append(
                f"- #{theme.get('rank')} {theme_label(theme.get('theme_id'), theme.get('theme_name'))} "
                f"分数=`{theme.get('momentum_score')}` 3个月广度=`{theme.get('breadth_3m')}` 代表标的={symbols}"
            )
        lines.append("")
    lines.extend([
        "## 推荐列表",
        "",
    ])
    for rec in report["recommendations"]:
        lines.extend(
            [
                f"### {rec['symbol']} - {rec['rating_label']}",
                "",
                f"- 推荐层级: `{rec['recommendation_tier_label']}`",
                f"- 适合周期: `{rec['primary_horizon_label']}({rec['primary_horizon_window']})`",
                "- 可观察周期: "
                + ", ".join(
                    f"`{horizon}={window}`" for horizon, window in rec["suitable_horizon_windows"].items()
                ),
                f"- 周期说明: {rec['horizon_note']}",
                f"- 策略风格: `{rec['strategy_style']}`",
                f"- 模型分数: `{rec['score']}`",
                f"- 来源置信度: `{rec['source_confidence_label']}`",
                f"- 证据分数: `{rec['evidence_score']}`",
                f"- 风险分数: `{rec['risk_score']}`",
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
    parser.add_argument("--theme-momentum", help="Saved theme momentum snapshot JSON.")
    parser.add_argument("--max-items", "--max-candidates", dest="max_candidates", type=int, default=12)
    parser.add_argument("--output-json", required=True, help="Output JSON artifact path.")
    parser.add_argument("--output-md", required=True, help="Output Markdown report path.")
    parser.add_argument("--output-manifest", help="Output artifact manifest path. Defaults to <output-json>.manifest.json.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    report = build_advisory_report(
        as_of=args.as_of,
        cadence=args.cadence,
        political_events_path=args.political_events,
        political_watchlist_path=args.political_watchlist,
        ai_signal_path=args.ai_signal,
        theme_momentum_path=args.theme_momentum,
        max_candidates=args.max_candidates,
    )
    write_json(args.output_json, report)
    write_text(args.output_md, render_markdown(report))
    manifest_path = args.output_manifest or f"{args.output_json}.manifest.json"
    write_report_manifest(
        report=report,
        report_path=args.output_json,
        markdown_path=args.output_md,
        manifest_path=manifest_path,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        git_sha=os.environ.get("GITHUB_SHA"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
    )


if __name__ == "__main__":
    main()

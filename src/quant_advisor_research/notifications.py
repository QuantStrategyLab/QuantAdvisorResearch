from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .advisory_report import display_number, display_percent, theme_label
from .publisher import cadence_label, report_filename


def report_public_url(report: dict[str, Any], *, site_url: str) -> str:
    return f"{site_url.rstrip('/')}/{quote(report_filename(report))}"


def _format_themes(report: dict[str, Any], *, limit: int) -> list[str]:
    theme_momentum = report.get("theme_momentum", {})
    if not theme_momentum.get("available"):
        return ["- 主题动量：暂无"]
    lines = ["主题动量："]
    for theme in theme_momentum.get("top_themes", [])[:limit]:
        symbols = ", ".join(theme.get("top_symbols", [])[:5]) or "无"
        label = theme_label(theme.get("theme_id"), theme.get("theme_name"))
        lines.append(f"- #{theme.get('rank')} {label} 分数={display_number(theme.get('momentum_score'))} 标的={symbols}")
    return lines


def _format_final_decisions(report: dict[str, Any]) -> list[str]:
    decisions = report.get("final_decisions", {})
    picks = decisions.get("recommendations", [])
    if not picks:
        return ["本期最终推荐：暂无（口径：AI信号仓库 + 动量为主，政策/新闻辅助）"]
    lines = ["本期最终推荐（AI信号仓库 + 动量为主，政策/新闻辅助）："]
    for item in picks:
        lines.append(
            "- {symbol} | {horizon} | 综合分={score} | 股票背景：{business}".format(
                symbol=item.get("symbol", ""),
                horizon=item.get("primary_horizon_label", ""),
                score=display_number(item.get("combined_score")),
                business=item.get("business_summary", ""),
            )
        )
        if item.get("prospect_summary"):
            lines.append(f"  推荐理由：{item.get('prospect_summary')}")
    buckets = decisions.get("horizon_buckets", {})
    lines.append("周期：短线={short}；中线={medium}；长线={long}".format(
        short=", ".join(buckets.get("short", [])) or "暂无",
        medium=", ".join(buckets.get("medium", [])) or "暂无",
        long=", ".join(buckets.get("long", [])) or "暂无",
    ))
    return lines


def _format_theme_candidates(report: dict[str, Any], *, limit: int) -> list[str]:
    candidates = report.get("theme_first_candidates", [])[:limit]
    if not candidates:
        return ["主题候选：暂无"]
    lines = ["主题候选（不是最终推荐）："]
    for item in candidates:
        lines.append(
            "- #{rank} {symbol} | {background} | 近3月 {ret3m} | 事件证据：{confirmation} | 结论：{status}".format(
                rank=item.get("rank", ""),
                symbol=item.get("symbol", ""),
                background=item.get("industry_background", item.get("primary_theme_id", "")),
                ret3m=display_percent(item.get("return_3m")),
                status=item.get("advisor_status", ""),
                confirmation=item.get("source_confirmation", ""),
            )
        )
        if item.get("recommendation_summary"):
            lines.append(f"  为什么：{item.get('recommendation_summary')}")
    return lines


def _format_recommendations(report: dict[str, Any], *, limit: int) -> list[str]:
    recommendations = report.get("recommendations", [])
    publishable = [
        item
        for item in recommendations
        if item.get("recommendation_tier") in {"tier_1", "tier_2", "watchlist", "source_check"}
    ][:limit]
    if not publishable:
        return ["推荐/观察摘要：暂无升级标的；仅监控标的保留在完整 JSON 中用于复盘。"]
    lines = ["推荐/观察摘要："]
    for item in publishable:
        lines.append(
            "- {symbol} | {tier} | {rating} | {horizon} | 分数={score}".format(
                symbol=item.get("symbol", ""),
                tier=item.get("recommendation_tier_label", item.get("recommendation_tier", "")),
                rating=item.get("rating_label", item.get("rating", "")),
                horizon=item.get("primary_horizon_label", ""),
                score=item.get("score", ""),
            )
        )
    return lines


def format_telegram_message(
    report: dict[str, Any],
    *,
    site_url: str,
    max_recommendations: int = 8,
    max_themes: int = 5,
) -> str:
    summary = report.get("summary", {})
    lines = [
        f"量化模型推荐 | {cadence_label(report)} | {report.get('as_of', '')}",
        "",
        f"模式：{report.get('mode', '')}",
        f"来源：{summary.get('source_mode', 'unknown')}",
        f"来源事件：{summary.get('source_event_count', 0)}",
        "",
        *_format_final_decisions(report),
        "",
        "说明：非个性化模型输出；不包含下单、仓位配置或账户级建议。",
        f"完整报告：{report_public_url(report, site_url=site_url)}",
    ]
    return "\n".join(str(line) for line in lines if line is not None)


def send_telegram_message(*, bot_token: str, chat_id: str, text: str, timeout: int = 20) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed Telegram API endpoint.
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}

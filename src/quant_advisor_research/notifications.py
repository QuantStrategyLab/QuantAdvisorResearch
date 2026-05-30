from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .publisher import report_filename


def report_public_url(report: dict[str, Any], *, site_url: str) -> str:
    return f"{site_url.rstrip('/')}/{quote(report_filename(report))}"


def _format_themes(report: dict[str, Any], *, limit: int) -> list[str]:
    theme_momentum = report.get("theme_momentum", {})
    if not theme_momentum.get("available"):
        return ["- Themes: not available"]
    lines = ["Top themes:"]
    for theme in theme_momentum.get("top_themes", [])[:limit]:
        symbols = ", ".join(theme.get("top_symbols", [])[:5]) or "None"
        lines.append(f"- #{theme.get('rank')} {theme.get('theme_id')} score={theme.get('momentum_score')} symbols={symbols}")
    return lines


def _format_recommendations(report: dict[str, Any], *, limit: int) -> list[str]:
    recommendations = report.get("recommendations", [])
    publishable = [
        item
        for item in recommendations
        if item.get("recommendation_tier") in {"tier_1", "tier_2", "watchlist", "source_check"}
    ][:limit]
    if not publishable:
        return ["Recommendations: None promoted; review full report for monitor list."]
    lines = ["Recommendations:"]
    for item in publishable:
        lines.append(
            "- {symbol} | {tier} | {rating} | {horizon} | score={score}".format(
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
    max_recommendations: int = 5,
    max_themes: int = 5,
) -> str:
    summary = report.get("summary", {})
    lines = [
        f"Quant Model Recommendations | {str(report.get('cadence', '')).title()} | {report.get('as_of', '')}",
        "",
        f"Mode: {report.get('mode', '')}",
        f"Source: {summary.get('source_mode', 'unknown')}",
        f"Source events: {summary.get('source_event_count', 0)}",
        "",
        *_format_themes(report, limit=max_themes),
        "",
        *_format_recommendations(report, limit=max_recommendations),
        "",
        "Policy: non-personalized model output only; no execution, allocation, or account-specific advice.",
        f"Full report: {report_public_url(report, site_url=site_url)}",
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

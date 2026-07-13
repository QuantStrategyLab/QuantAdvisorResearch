from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .advisory_report import display_number, display_percent, sector_label, theme_label


CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}

HORIZON_COLUMNS = (
    ("long", "长线", "1-3年"),
    ("medium", "中线", "2-12周"),
    ("short", "短线", "1-10个交易日"),
)
INDEX_HISTORY_LIMIT = 12
RSS_ITEM_LIMIT = 20

SITE_ICON_FILENAME = "favicon.svg"
SITE_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="qsl-bg" x1="8" y1="6" x2="58" y2="62" gradientUnits="userSpaceOnUse">
      <stop stop-color="#1e4dd8"/>
      <stop offset="0.56" stop-color="#00a6c8"/>
      <stop offset="1" stop-color="#d99b2b"/>
    </linearGradient>
    <filter id="qsl-shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#172033" flood-opacity=".28"/>
    </filter>
  </defs>
  <rect x="5" y="5" width="54" height="54" rx="16" fill="#172033"/>
  <path d="M18 43V25.5L29.2 36.7 44.8 20" fill="none" stroke="url(#qsl-bg)" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round" filter="url(#qsl-shadow)"/>
  <circle cx="18" cy="43" r="4" fill="#fffaf0"/>
  <circle cx="30" cy="36" r="4" fill="#fffaf0"/>
  <circle cx="46" cy="19" r="4.5" fill="#fffaf0"/>
  <path d="M45 45c-4 3.7-9.7 5-15.1 3.3-8.8-2.8-13.7-12.2-10.9-21 2.1-6.7 8.1-11.1 14.7-11.6" fill="none" stroke="#fffaf0" stroke-width="3.2" stroke-linecap="round" opacity=".88"/>
</svg>
"""


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "report"


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def report_content_fingerprint(report: dict[str, Any]) -> str:
    ignored_top_level_keys = {
        "as_of",
        "generated_at",
        "reference_time",
        "expires_at",
        "freshness_status",
        "freshness",
        "source_artifacts",
    }
    normalized = {key: value for key, value in report.items() if key not in ignored_top_level_keys}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def report_as_of_date(report: dict[str, Any]) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(report.get("as_of", "")))
    except ValueError:
        return None


def is_same_period_duplicate(report: dict[str, Any], previous_report: dict[str, Any]) -> bool:
    if str(report.get("cadence", "")) != str(previous_report.get("cadence", "")):
        return False
    as_of = report_as_of_date(report)
    previous_as_of = report_as_of_date(previous_report)
    if as_of is None or previous_as_of is None:
        return True
    if str(report.get("cadence", "")) == "weekly":
        return abs((as_of - previous_as_of).days) < 7
    return as_of == previous_as_of


def unique_report_paths_by_content(report_paths: list[str | Path]) -> list[Path]:
    unique_paths: list[Path] = []
    seen_reports_by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    for report_path in report_paths:
        path = Path(report_path)
        report = load_report(path)
        fingerprint = report_content_fingerprint(report)
        previous_reports = seen_reports_by_fingerprint.setdefault(fingerprint, [])
        if any(is_same_period_duplicate(report, previous) for previous in previous_reports):
            continue
        previous_reports.append(report)
        unique_paths.append(path)
    return unique_paths


def format_datetime(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def report_filename(report: dict[str, Any]) -> str:
    return f"{report['as_of']}-{slug(report['cadence'])}-model-recommendations.html"


def cadence_label(report: dict[str, Any]) -> str:
    cadence = str(report.get("cadence", ""))
    return CADENCE_LABELS_ZH.get(cadence, cadence.title())


def format_theme_ids(theme_ids: Any) -> str:
    if isinstance(theme_ids, str):
        theme_ids = [theme_ids]
    if not isinstance(theme_ids, list):
        theme_ids = []
    return ", ".join(theme_label(theme_id) for theme_id in theme_ids) or "无"


def format_candidate_theme_ids(candidate: dict[str, Any]) -> str:
    theme_name_by_id = {
        str(theme.get("theme_id", "")): str(theme.get("theme_name", ""))
        for theme in candidate.get("themes", [])
        if isinstance(theme, dict)
    }
    labels = [
        theme_label(theme_id, theme_name_by_id.get(str(theme_id), ""))
        for theme_id in candidate.get("theme_ids", [])
    ]
    return ", ".join(labels) or "无"


def render_site_mark() -> str:
    return """
    <span class="site-mark" aria-hidden="true">
      <svg viewBox="0 0 64 64" focusable="false">
        <rect x="5" y="5" width="54" height="54" rx="16"></rect>
        <path class="mark-line" d="M18 43V25.5L29.2 36.7 44.8 20"></path>
        <circle cx="18" cy="43" r="4"></circle>
        <circle cx="30" cy="36" r="4"></circle>
        <circle cx="46" cy="19" r="4.5"></circle>
        <path class="mark-ring" d="M45 45c-4 3.7-9.7 5-15.1 3.3-8.8-2.8-13.7-12.2-10.9-21 2.1-6.7 8.1-11.1 14.7-11.6"></path>
      </svg>
    </span>
    """


def render_market_wave() -> str:
    return """
    <svg class="market-wave" viewBox="0 0 720 260" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="wave-line" x1="68" y1="208" x2="696" y2="44" gradientUnits="userSpaceOnUse">
          <stop stop-color="#8fd2ff" stop-opacity=".12"/>
          <stop offset=".48" stop-color="#3aa7ff" stop-opacity=".58"/>
          <stop offset="1" stop-color="#1664d9" stop-opacity=".78"/>
        </linearGradient>
        <linearGradient id="wave-area" x1="0" y1="78" x2="0" y2="246" gradientUnits="userSpaceOnUse">
          <stop stop-color="#dff4ff" stop-opacity=".52"/>
          <stop offset="1" stop-color="#dff4ff" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="M72 220 C128 194 164 206 224 170 S324 136 374 154 466 178 526 112 626 120 696 62"
        fill="none" stroke="#ffffff" stroke-width="2" opacity=".72"/>
      <path d="M72 226 C132 210 164 214 222 184 S324 150 374 168 472 190 532 132 636 138 696 86 L696 250 L72 250 Z"
        fill="url(#wave-area)" opacity=".86"/>
      <path d="M72 226 C132 210 164 214 222 184 S324 150 374 168 472 190 532 132 636 138 696 86"
        fill="none" stroke="url(#wave-line)" stroke-width="3" stroke-linecap="round"/>
      <g fill="#ffffff" stroke="#8bd4ff" stroke-width="2">
        <circle cx="224" cy="184" r="5"/><circle cx="374" cy="168" r="5"/>
        <circle cx="532" cy="132" r="5"/><circle cx="696" cy="86" r="5"/>
      </g>
      <g opacity=".22" fill="#7fbfff">
        <rect x="102" y="206" width="16" height="44" rx="5"/>
        <rect x="156" y="188" width="16" height="62" rx="5"/>
        <rect x="210" y="168" width="16" height="82" rx="5"/>
        <rect x="264" y="150" width="16" height="100" rx="5"/>
        <rect x="318" y="136" width="16" height="114" rx="5"/>
        <rect x="372" y="156" width="16" height="94" rx="5"/>
        <rect x="426" y="174" width="16" height="76" rx="5"/>
        <rect x="480" y="148" width="16" height="102" rx="5"/>
        <rect x="534" y="112" width="16" height="138" rx="5"/>
        <rect x="588" y="126" width="16" height="124" rx="5"/>
        <rect x="642" y="104" width="16" height="146" rx="5"/>
      </g>
    </svg>
    """


def horizon_pick_score(pick: dict[str, Any], horizon: str) -> float:
    score = pick.get("horizon_scores", {}).get(horizon, {}).get("score")
    return float(score) if isinstance(score, (int, float)) else as_sortable_float(pick.get("combined_score"))


def as_sortable_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def ranked_horizon_picks(final_picks: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    primary_picks = [pick for pick in final_picks if pick.get("primary_horizon") == horizon]
    if horizon == "long" and not primary_picks:
        picks = [
            pick
            for pick in final_picks
            if pick.get("horizon_actions", {}).get(horizon) in {"recommend", "watch"}
        ]
    else:
        picks = primary_picks
    return sorted(picks, key=lambda pick: (-horizon_pick_score(pick, horizon), str(pick.get("symbol", ""))))


def horizon_display_meta(pick: dict[str, Any], horizon: str) -> tuple[str, str, float]:
    labels = {"short": "短线", "medium": "中线", "long": "长线"}
    windows = {"short": "1-10个交易日", "medium": "2-12周", "long": "1-3年"}
    if pick.get("primary_horizon") == horizon:
        label = str(pick.get("primary_horizon_label") or labels.get(horizon, ""))
        window = str(pick.get("primary_horizon_window") or windows.get(horizon, ""))
        score = as_sortable_float(pick.get("combined_score"))
        return label, window, score
    score = horizon_pick_score(pick, horizon)
    return labels.get(horizon, ""), windows.get(horizon, ""), score


def render_final_card(pick: dict[str, Any], *, rank: int, horizon: str) -> str:
    horizon_label, horizon_window, _score = horizon_display_meta(pick, horizon)
    return f"""
    <article class="final-card">
      <header>
        <h3><span class="rank">推荐 #{rank}</span>{html.escape(str(pick.get('symbol', '')))}</h3>
        <p>{html.escape(str(pick.get('name', '')))}</p>
      </header>
      <dl>
        <div><dt>周期</dt><dd>{html.escape(horizon_label)} / {html.escape(horizon_window)}</dd></div>
      </dl>
      <p><strong>股票背景：</strong>{html.escape(str(pick.get('business_summary', '')))}</p>
      <p><strong>推荐理由：</strong>{html.escape(str(pick.get('prospect_summary', '')))}</p>
      <p><strong>主要风险：</strong>{html.escape(str(pick.get('risk_summary', '')))}</p>
    </article>
    """


def join_zh_items(items: list[str], *, limit: int = 5, empty: str = "暂无") -> str:
    cleaned = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    if not cleaned:
        return empty
    visible = cleaned[:limit]
    suffix = "等" if len(cleaned) > limit else ""
    return "、".join(visible) + suffix


def displayed_horizon_symbols(report: dict[str, Any], horizon: str) -> list[str]:
    decisions = report.get("final_decisions", {})
    if not isinstance(decisions, dict):
        return []
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    return [
        str(pick.get("symbol", "")).strip()
        for pick in ranked_horizon_picks(final_picks, horizon)
        if str(pick.get("symbol", "")).strip()
    ]


def format_horizon_conclusion(report: dict[str, Any]) -> str:
    parts = []
    for horizon, label, _window in HORIZON_COLUMNS:
        symbols = displayed_horizon_symbols(report, horizon)
        value = join_zh_items(symbols, empty="暂无稳定结论")
        parts.append(f"{label}：{value}")
    return "；".join(parts)


def format_momentum_factor_summary(report: dict[str, Any]) -> str:
    theme_momentum = report.get("theme_momentum", {})
    if not isinstance(theme_momentum, dict) or not theme_momentum.get("available"):
        return "本期暂无足够稳定的主题排序。"

    themes = [theme for theme in theme_momentum.get("top_themes", []) if isinstance(theme, dict)]
    theme_names = [theme_label(theme.get("theme_id"), theme.get("theme_name")) for theme in themes[:4]]
    sectors = [sector_label(theme.get("sector")) for theme in themes[:4]]
    sector_text = join_zh_items(sectors, limit=3, empty="暂无明确板块")
    theme_text = join_zh_items(theme_names, limit=4, empty="暂无明确主题")
    if sector_text == "暂无明确板块":
        return f"本期较突出的方向包括 {theme_text}。"
    return f"本期较突出的方向主要在{sector_text}板块，代表主题包括 {theme_text}。"


def format_report_takeaway(report: dict[str, Any]) -> str:
    has_long = bool(displayed_horizon_symbols(report, "long"))
    has_medium = bool(displayed_horizon_symbols(report, "medium"))
    has_short = bool(displayed_horizon_symbols(report, "short"))
    if has_long and has_medium and has_short:
        return "整体看，当前结论存在跨周期共振，后续重点观察趋势能否延续和风险事件变化。"
    if has_long and has_medium:
        return "整体看，当前结论更偏中长线，短线暂不强调，后续重点观察趋势能否延续和基本面兑现。"
    if has_medium:
        return "整体看，当前结论更偏中线，短线暂不强调，后续重点观察趋势能否延续和基本面兑现。"
    if has_long:
        return "整体看，当前信号更偏长线观察，短线和中线暂未形成稳定排序。"
    if has_short:
        return "整体看，当前只出现短线机会，持续性仍需要后续数据确认。"
    return "整体看，当前暂未形成稳定系统结论，继续等待更清晰的主题和价格确认。"


def render_report_lead(report: dict[str, Any]) -> str:
    return " ".join(
        [
            f"本期结论：{format_horizon_conclusion(report)}。",
            format_momentum_factor_summary(report),
            format_report_takeaway(report),
        ]
    )


def render_final_decisions_html(report: dict[str, Any]) -> str:
    decisions = report.get("final_decisions", {})
    if not decisions:
        return ""
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    columns = []
    for horizon, label, window in HORIZON_COLUMNS:
        cards = [
            render_final_card(pick, rank=index, horizon=horizon)
            for index, pick in enumerate(ranked_horizon_picks(final_picks, horizon), start=1)
        ]
        body = "".join(cards)
        if not body:
            body = '<p class="empty-column">暂无</p>'
        columns.append(
            f"""
            <section class="horizon-column horizon-{html.escape(horizon)}">
              <header class="horizon-column-header">
                <h2>{html.escape(label)}</h2>
                <p>{html.escape(window)}</p>
              </header>
              <div class="horizon-cards">{body}</div>
            </section>
            """
        )
    return f"""
    <section class="final-decisions">
      <div class="horizon-columns">{''.join(columns)}</div>
    </section>
    """


def render_theme_first_candidates_html(report: dict[str, Any]) -> str:
    candidates = report.get("theme_first_candidates", [])
    if not candidates:
        return ""
    cards = []
    for candidate in candidates:
        theme_ids = format_candidate_theme_ids(candidate)
        primary_theme = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
        reasons = candidate.get("reasons", [])
        reason = reasons[0] if reasons else ""
        cards.append(
            f"""
            <article class="candidate-card">
              <header>
                <span class="rank">#{html.escape(str(candidate.get('rank', '')))}</span>
                <div>
                  <h3>{html.escape(str(candidate.get('symbol', '')))}</h3>
                  <p>{html.escape(str(candidate.get('industry_background', '')))}</p>
                </div>
              </header>
              <dl>
                <div><dt>主题</dt><dd>{html.escape(primary_theme)}</dd></div>
                <div><dt>动量强度</dt><dd>{html.escape(display_number(candidate.get('symbol_momentum_score')))}</dd></div>
                <div><dt>近3个月</dt><dd>{html.escape(display_percent(candidate.get('return_3m')))}</dd></div>
                <div><dt>事件证据</dt><dd>{html.escape(str(candidate.get('source_confirmation', '')))}</dd></div>
                <div><dt>当前结论</dt><dd>{html.escape(str(candidate.get('advisor_status', '')))}</dd></div>
              </dl>
              <p><strong>为什么入选：</strong>{html.escape(str(candidate.get('recommendation_summary') or reason))}</p>
              <p><strong>主要风险：</strong>{html.escape(str(candidate.get('risk_summary', '')))}</p>
              <p><strong>相关主题：</strong>{html.escape(theme_ids)}</p>
            </article>
            """
        )
    return f"""
    <section class="theme-candidates">
      <h2>主题候选（解释材料，不是最终推荐）</h2>
      <p><strong>用途：</strong>这里只解释哪些股票进入主题/动量候选池，公开页面默认只显示最终推荐。</p>
      <p><strong>怎么理解：</strong>这是非个性化模型股票池，不是买入清单；“暂无明确事件催化”表示该标的主要来自主题/动量排序，
      还没有足够稳定的新闻、政策或公司事件证据。</p>
      <div class="candidate-grid">{''.join(cards)}</div>
    </section>
    """


def render_theme_momentum_html(report: dict[str, Any]) -> str:
    theme_momentum = report.get("theme_momentum", {})
    if not theme_momentum.get("available"):
        return ""
    rows = []
    for theme in theme_momentum.get("top_themes", []):
        symbols = ", ".join(theme.get("top_symbols", [])) or "无"
        theme_name = theme_label(theme.get("theme_id"), theme.get("theme_name"))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(theme.get('rank', '')))}</td>"
            f"<td>{html.escape(theme_name)}</td>"
            f"<td>{html.escape(sector_label(theme.get('sector', '')))}</td>"
            f"<td>{html.escape(display_number(theme.get('momentum_score')))}</td>"
            f"<td>{html.escape(display_percent(theme.get('breadth_3m')))}</td>"
            f"<td>{html.escape(symbols)}</td>"
            "</tr>"
        )
    return f"""
    <section class="theme-momentum">
      <h2>主题动量</h2>
      <p>研究用途主题排序，快照日期：{html.escape(str(theme_momentum.get('as_of', '')))}。
      主题动量只提示强主题和候选标的，不直接改变推荐评级。</p>
      <table>
        <thead><tr><th>排名</th><th>主题</th><th>板块</th><th>分数</th><th>3个月广度</th><th>代表标的</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """

def render_report_html(report: dict[str, Any]) -> str:
    title = f"智慧投顾研究{cadence_label(report)}复盘 - {report['as_of']}"
    display_title = f"智慧投顾研究{cadence_label(report)}复盘"
    final_decisions_html = render_final_decisions_html(report)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>
    :root {{
      color-scheme: light;
      --ink: #0b1430;
      --muted: #5f6f89;
      --line: #d9e5f4;
      --paper: #f8fbff;
      --panel: rgba(255,255,255,.86);
      --blue: #1d4ed8;
      --cyan: #06a7c8;
      --gold: #d99412;
      --green: #059669;
      --rose: #b54708;
      --shadow: 0 24px 70px rgba(12,24,54,.12);
      --font-sans: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", ui-sans-serif, system-ui, sans-serif;
      --font-display: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", "STSong", "SimSun", ui-serif, serif;
      font-family: var(--font-sans);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 12%, rgba(6,167,200,.17), transparent 28rem),
        radial-gradient(circle at 92% 6%, rgba(29,78,216,.12), transparent 34rem),
        linear-gradient(135deg, #eef8ff 0%, #f7fbff 45%, #fff8e8 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(12,24,54,.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(12,24,54,.045) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 78%);
    }}
    a {{ color: var(--blue); word-break: break-word; }}
    .report-shell {{ max-width: 1280px; margin: 0 auto; padding: 28px 24px 72px; position: relative; }}
    .topbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 26px;
      padding: 12px 14px;
      border: 1px solid rgba(217,229,244,.88);
      border-radius: 24px;
      background: rgba(255,255,255,.82);
      backdrop-filter: blur(18px);
      box-shadow: 0 16px 42px rgba(12,24,54,.07);
    }}
    .brand-link {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--ink);
      text-decoration: none;
      font-size: 1.02rem;
      font-weight: 900;
      letter-spacing: -.025em;
    }}
    .brand-link .site-mark {{ width: 38px; height: 38px; margin: 0; }}
    .topbar-actions {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    .topbar-actions a {{
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      padding: 0 14px;
      border: 1px solid rgba(217,229,244,.95);
      border-radius: 999px;
      background: rgba(255,255,255,.72);
      color: var(--ink);
      text-decoration: none;
      font-size: .92rem;
      font-weight: 750;
      box-shadow: 0 10px 24px rgba(12,24,54,.06);
    }}
    .report-hero {{
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(230px, .28fr);
      gap: 24px;
      align-items: stretch;
      margin-bottom: 26px;
      padding: clamp(24px, 3.4vw, 40px);
      border: 1px solid rgba(217,229,244,.95);
      border-radius: 30px;
      background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(255,255,255,.82));
      box-shadow: var(--shadow);
    }}
    .report-hero::after {{
      content: "";
      position: absolute;
      right: -86px;
      top: -120px;
      width: 286px;
      height: 286px;
      border-radius: 999px;
      background: rgba(6,167,200,.13);
      filter: blur(6px);
    }}
    .market-wave {{
      position: absolute;
      right: 190px;
      top: 18px;
      width: min(610px, 54vw);
      height: auto;
      opacity: .24;
    }}
    .report-hero-copy {{ position: relative; z-index: 1; text-align: center; }}
    .site-mark {{ display: inline-flex; width: 64px; height: 64px; margin: 0 auto 16px; filter: drop-shadow(0 18px 28px rgba(29,78,216,.22)); }}
    .site-mark svg {{ width: 100%; height: 100%; }}
    .site-mark rect {{ fill: #0b1430; }}
    .site-mark .mark-line {{ fill: none; stroke: var(--cyan); stroke-width: 5.5; stroke-linecap: round; stroke-linejoin: round; }}
    .site-mark circle {{ fill: #ffffff; }}
    .site-mark .mark-ring {{ fill: none; stroke: #ffffff; stroke-width: 3.2; stroke-linecap: round; opacity: .88; }}
    .eyebrow {{ margin: 0 0 10px; color: var(--blue); font-size: .72rem; font-weight: 850; letter-spacing: .18em; text-transform: uppercase; }}
    h1 {{ margin: 0 auto; max-width: 760px; font-family: var(--font-display); font-size: clamp(2.05rem, 4vw, 3.45rem); font-weight: 800; line-height: 1.08; letter-spacing: -.045em; }}
    .report-lead {{ margin: 16px auto 0; max-width: 760px; color: var(--muted); font-size: .99rem; line-height: 1.82; }}
    .date-card {{
      position: relative;
      z-index: 1;
      display: grid;
      align-content: end;
      min-height: 220px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 22px;
      background: rgba(255,255,255,.78);
      backdrop-filter: blur(10px);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.6);
    }}
    .date-card .date-label {{ margin: 0; color: var(--muted); font-size: .78rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    .date-card .date-value {{ margin: 8px 0 16px; font-size: clamp(1.55rem, 2.2vw, 2rem); line-height: 1; font-weight: 850; letter-spacing: -.04em; white-space: nowrap; }}
    .date-card .cadence-value {{ margin: 0; display: inline-flex; width: fit-content; padding: 7px 11px; border-radius: 999px; border: 1px solid rgba(29,78,216,.22); background: #fff; font-size: .92rem; font-weight: 800; }}
    .final-decisions {{ margin-top: 22px; }}
    .horizon-columns {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-items: start; }}
    .horizon-column {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 16px;
      min-height: 220px;
      background: var(--panel);
      box-shadow: 0 18px 44px rgba(12,24,54,.09);
    }}
    .horizon-column::before {{ content: ""; position: absolute; left: 0; right: 0; top: 0; height: 5px; }}
    .horizon-long::before {{ background: var(--green); }}
    .horizon-medium::before {{ background: var(--blue); }}
    .horizon-short::before {{ background: var(--gold); }}
    .horizon-column-header {{ text-align: center; padding: 12px 8px 16px; }}
    .horizon-column-header h2 {{ margin: 0; font-size: 1.34rem; font-weight: 850; letter-spacing: -.03em; }}
    .horizon-column-header p {{ margin: 5px 0 0; color: var(--muted); font-size: .88rem; }}
    .horizon-cards {{ display: grid; gap: 13px; }}
    .empty-column {{ margin: 24px 0; color: var(--muted); text-align: center; }}
    .final-card {{
      background: rgba(255,255,255,.9);
      border: 1px solid rgba(217,226,239,.95);
      border-radius: 20px;
      padding: 18px;
      box-shadow: 0 10px 28px rgba(12,24,54,.075);
    }}
    .final-card header {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; border-bottom: 1px solid #edf2f7; padding-bottom: 12px; margin-bottom: 12px; }}
    .final-card h3 {{ margin: 0; display: flex; align-items: center; gap: 8px; font-size: 1.18rem; font-weight: 850; letter-spacing: -.03em; }}
    .final-card header p {{ margin: 0; color: var(--muted); text-align: right; font-size: .86rem; }}
    .final-card .rank {{ display: inline-flex; align-items: center; justify-content: center; min-width: 38px; min-height: 26px; padding: 0 8px; border-radius: 999px; background: #eef4ff; color: var(--blue); font-weight: 900; font-size: .86rem; }}
    .final-card p {{ margin: 12px 0 0; font-size: .95rem; line-height: 1.68; color: #334155; }}
    .final-card strong {{ color: var(--ink); }}
    dl {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 9px; margin: 0 0 12px; }}
    dl div {{ border: 1px solid #e5edf6; border-radius: 15px; padding: 10px; background: #fbfdff; }}
    dt {{ color: var(--muted); font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; }}
    dd {{ margin: 4px 0 0; font-size: .95rem; font-weight: 800; }}
    ul {{ margin: 8px 0 0; padding-left: 1.15rem; color: #334155; font-size: .95rem; line-height: 1.6; }}
    li {{ margin: 5px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ text-align: left; border-bottom: 1px solid #eaeef2; padding: 8px; vertical-align: top; }}
    .theme-candidates, .theme-momentum, .recommendation-section, .recommendation, .monitor-note, .horizon-note {{ display: none; }}
    @media (max-width: 980px) {{
      .report-hero {{ grid-template-columns: 1fr; }}
      .date-card {{ min-height: auto; }}
      .horizon-columns {{ grid-template-columns: 1fr; }}
      .final-card header {{ display: block; }}
      .final-card header p {{ margin-top: 5px; text-align: left; }}
    }}
    @media (max-width: 640px) {{
      .report-shell {{ padding: 20px 14px 48px; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .topbar-actions {{ justify-content: flex-start; }}
      .report-hero {{ border-radius: 24px; padding: 22px 18px; }}
      .horizon-column {{ border-radius: 22px; }}
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    <nav class="topbar" aria-label="站点导航">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <div class="topbar-actions">
        <a href="index.html">返回首页</a>
        <a href="archive.html">历史归档</a>
        <a href="feed.xml">RSS 订阅</a>
      </div>
    </nav>
    <section class="report-hero">
      {render_market_wave()}
      <div class="report-hero-copy">
        {render_site_mark()}
        <p class="eyebrow">Advisory briefing</p>
        <h1>{html.escape(display_title)}</h1>
        <p class="report-lead">{html.escape(render_report_lead(report))}</p>
      </div>
      <aside class="date-card" aria-label="报告日期">
        <p class="date-label">Report date</p>
        <p class="date-value">{html.escape(str(report['as_of']))}</p>
        <p class="cadence-value">{html.escape(cadence_label(report))}更新</p>
      </aside>
    </section>
    {final_decisions_html}
  </main>
</body>
</html>
"""


def horizon_summary_symbols(report: dict[str, Any], horizon: str) -> list[str]:
    decisions = report.get("final_decisions", {})
    buckets = decisions.get("horizon_buckets", {}) if isinstance(decisions, dict) else {}
    primary_symbols = [str(symbol) for symbol in buckets.get(horizon, [])]
    if primary_symbols:
        return primary_symbols

    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    secondary_picks = [
        pick
        for pick in final_picks
        if pick.get("horizon_actions", {}).get(horizon) in {"recommend", "watch"}
    ]
    return [
        str(pick.get("symbol", ""))
        for pick in sorted(
            secondary_picks,
            key=lambda item: (-horizon_pick_score(item, horizon), str(item.get("symbol", ""))),
        )
        if str(pick.get("symbol", ""))
    ]


def format_horizon_summary(report: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
    return [
        (horizon, label, window, horizon_summary_symbols(report, horizon))
        for horizon, label, window in HORIZON_COLUMNS
    ]


def render_symbol_tags(symbols: list[str], *, empty_label: str = "暂无") -> str:
    if not symbols:
        return f'<span class="symbol-tag empty">{html.escape(empty_label)}</span>'
    return "".join(f'<span class="symbol-tag">{html.escape(symbol)}</span>' for symbol in symbols)


def render_horizon_snapshot(report: dict[str, Any], *, linked: bool = False) -> str:
    columns = []
    href = report_filename(report)
    for horizon, label, window, symbols in format_horizon_summary(report):
        tags = render_symbol_tags(symbols)
        body = f'<a class="horizon-link" href="{html.escape(href)}">{tags}</a>' if linked else tags
        columns.append(
            f"""
            <section class="snapshot-column snapshot-{html.escape(horizon)}">
              <p class="snapshot-label">{html.escape(label)}</p>
              <p class="snapshot-window">{html.escape(window)}</p>
              <div class="symbol-strip">{body}</div>
            </section>
            """
        )
    return f'<div class="snapshot-grid">{"".join(columns)}</div>'


def render_index_html(reports: list[dict[str, Any]]) -> str:
    sorted_reports = sorted(reports, key=lambda item: item["as_of"], reverse=True)
    latest = sorted_reports[0] if sorted_reports else None
    latest_block = ""
    if latest:
        latest_filename = report_filename(latest)
        top_themes = format_theme_ids(latest["summary"].get("top_theme_ids", []))
        top_symbols = latest["summary"].get("top_recommended_symbols", [])
        latest_block = f"""
        <section class="latest-panel">
          <div class="latest-copy">
            <p class="eyebrow">Latest advisory</p>
            <h2>{html.escape(latest['as_of'])} {html.escape(cadence_label(latest))}智慧投顾研究</h2>
            <p class="lead">结合主题动量、市场确认和事件证据，生成普通投资者更容易阅读的研究结论。</p>
            <div class="theme-line"><span>主要信号</span>{html.escape(top_themes or '无')}</div>
            <div class="symbol-strip hero-symbols">{render_symbol_tags([str(symbol) for symbol in top_symbols])}</div>
            <a class="primary-action" href="{html.escape(latest_filename)}">打开最新报告</a>
          </div>
          {render_horizon_snapshot(latest)}
        </section>
        """
    items = []
    recent_reports = sorted_reports[1 : INDEX_HISTORY_LIMIT + 1]
    for report in recent_reports:
        filename = report_filename(report)
        top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
        top_symbols = [str(symbol) for symbol in report["summary"].get("top_recommended_symbols", [])]
        items.append(
            f"""
            <article class="archive-card">
              <a class="archive-title" href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(cadence_label(report))}复盘</a>
              <p>主要信号：{html.escape(top_themes or '无')}</p>
              <div class="archive-symbols">{render_symbol_tags(top_symbols)}</div>
              {render_horizon_snapshot(report, linked=True)}
            </article>
            """
        )
    archive = "".join(items) or '<p class="empty-archive">暂无更多历史报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>智慧投顾研究系统</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>
    :root {{
      color-scheme: light;
      --ink: #0b1430;
      --muted: #5f6f89;
      --line: #d9e5f4;
      --paper: #f8fbff;
      --panel: rgba(255,255,255,.86);
      --blue: #1d4ed8;
      --cyan: #06a7c8;
      --gold: #d99412;
      --green: #059669;
      --shadow: 0 24px 70px rgba(12,24,54,.12);
      --font-sans: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", ui-sans-serif, system-ui, sans-serif;
      --font-display: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", "STSong", "SimSun", ui-serif, serif;
      font-family: var(--font-sans);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 12%, rgba(6,167,200,.17), transparent 28rem),
        radial-gradient(circle at 92% 6%, rgba(29,78,216,.12), transparent 34rem),
        linear-gradient(135deg, #eef8ff 0%, #f7fbff 45%, #fff8e8 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(12,24,54,.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(12,24,54,.045) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 78%);
    }}
    body::after {{
      content: "";
      position: fixed;
      inset: 80px 0 auto 0;
      height: 320px;
      pointer-events: none;
      background: linear-gradient(90deg, rgba(255,255,255,.72), rgba(255,255,255,0));
      opacity: .72;
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 0 24px 72px; position: relative; }}
    .site-header {{
      position: relative;
      z-index: 5;
      border-bottom: 1px solid rgba(217,229,244,.88);
      background: rgba(255,255,255,.82);
      backdrop-filter: blur(18px);
      box-shadow: 0 1px 0 rgba(255,255,255,.72);
    }}
    .site-header-inner {{
      max-width: 1280px;
      margin: 0 auto;
      min-height: 74px;
      padding: 0 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }}
    .brand-link {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      color: var(--ink);
      text-decoration: none;
      font-size: 1.08rem;
      font-weight: 900;
      letter-spacing: -.025em;
    }}
    .brand-link .site-mark {{ width: 42px; height: 42px; }}
    .site-nav {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: flex-end; }}
    .site-nav a {{
      min-height: 38px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 14px;
      border: 1px solid transparent;
      border-radius: 999px;
      color: var(--ink);
      text-decoration: none;
      font-size: .94rem;
      font-weight: 850;
    }}
    .site-nav a:hover {{ border-color: var(--line); background: rgba(248,251,255,.9); }}
    .nav-glyph {{ color: var(--blue); font-size: 1rem; line-height: 1; }}
    .hero {{
      position: relative;
      overflow: hidden;
      min-height: 300px;
      padding: 54px 0 42px;
      display: grid;
      align-items: center;
    }}
    .hero-copy {{ max-width: 740px; position: relative; z-index: 2; }}
    .market-wave {{
      position: absolute;
      right: max(-110px, -7vw);
      top: 20px;
      width: min(720px, 58vw);
      height: auto;
      opacity: .9;
    }}
    .site-mark {{ flex: 0 0 auto; display: inline-flex; width: 64px; height: 64px; filter: drop-shadow(0 18px 28px rgba(29,78,216,.22)); }}
    .site-mark svg {{ width: 100%; height: 100%; }}
    .site-mark rect {{ fill: #0b1430; }}
    .site-mark .mark-line {{ fill: none; stroke: var(--cyan); stroke-width: 5.5; stroke-linecap: round; stroke-linejoin: round; }}
    .site-mark circle {{ fill: #ffffff; }}
    .site-mark .mark-ring {{ fill: none; stroke: #ffffff; stroke-width: 3.2; stroke-linecap: round; opacity: .88; }}
    .eyebrow {{ margin: 0 0 10px; color: var(--blue); font-size: .72rem; font-weight: 850; letter-spacing: .18em; text-transform: uppercase; }}
    h1 {{ margin: 0; max-width: 780px; font-family: var(--font-display); font-size: clamp(2.5rem, 5.5vw, 4.8rem); font-weight: 800; line-height: 1.03; letter-spacing: -.055em; }}
    .hero p {{ margin: 18px 0 0; max-width: 720px; color: #42526f; font-size: 1.04rem; line-height: 1.82; }}
    .latest-panel {{
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1.02fr) minmax(460px, .98fr);
      gap: 28px;
      border: 1px solid rgba(217,229,244,.95);
      border-radius: 26px;
      padding: 28px;
      background: linear-gradient(135deg, rgba(255,255,255,.96), rgba(255,255,255,.82));
      box-shadow: var(--shadow);
    }}
    .latest-panel::after {{ content: ""; position: absolute; right: -90px; top: -100px; width: 280px; height: 280px; border-radius: 999px; background: rgba(6,167,200,.15); filter: blur(6px); }}
    .latest-copy {{ position: relative; z-index: 1; }}
    h2 {{ margin: 0; font-size: clamp(1.72rem, 2.7vw, 2.3rem); font-weight: 900; letter-spacing: -.04em; }}
    .lead {{ color: var(--muted); line-height: 1.7; max-width: 620px; }}
    .theme-line {{ display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px 0 16px; color: var(--ink); line-height: 1.55; }}
    .theme-line span {{ color: var(--blue); font-weight: 800; }}
    .symbol-strip {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .hero-symbols {{ margin-bottom: 20px; }}
    .symbol-tag {{ display: inline-flex; align-items: center; min-height: 30px; padding: 6px 11px; border-radius: 999px; border: 1px solid rgba(29,78,216,.20); background: #fff; color: var(--ink); font-size: .94rem; font-weight: 850; box-shadow: 0 6px 16px rgba(12,24,54,.06); }}
    .symbol-tag.empty {{ color: var(--muted); font-weight: 700; }}
    .primary-action {{ display: inline-flex; align-items: center; justify-content: center; min-height: 46px; padding: 0 20px; border-radius: 14px; background: linear-gradient(135deg, #0b1430, #102765); color: #fff; text-decoration: none; font-weight: 900; box-shadow: 0 14px 28px rgba(12,24,54,.22); }}
    .primary-action:hover {{ transform: translateY(-1px); }}
    .snapshot-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-self: stretch; position: relative; z-index: 1; }}
    .snapshot-column {{
      position: relative;
      overflow: hidden;
      padding: 22px 18px;
      border: 1px solid var(--line);
      border-radius: 19px;
      background: rgba(255,255,255,.72);
      backdrop-filter: blur(10px);
      min-height: 230px;
    }}
    .snapshot-column::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 4px; background: currentColor; }}
    .snapshot-column::after {{
      content: "";
      position: absolute;
      left: 16px;
      right: 16px;
      bottom: 16px;
      height: 58px;
      border-bottom: 2px solid currentColor;
      border-radius: 50% 45% 0 0;
      opacity: .22;
      transform: skewY(-8deg);
    }}
    .snapshot-label {{ margin: 0; font-size: 1.12rem; font-weight: 850; letter-spacing: -.025em; }}
    .snapshot-window {{ margin: 4px 0 14px; color: var(--muted); font-size: .9rem; }}
    .snapshot-long {{ color: var(--green); }}
    .snapshot-medium {{ color: var(--blue); }}
    .snapshot-short {{ color: var(--gold); }}
    .snapshot-column .symbol-strip {{ position: relative; z-index: 1; }}
    .snapshot-column .symbol-tag {{ color: var(--ink); }}
    .horizon-link {{ color: inherit; text-decoration: none; }}
    .section-title {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 34px 0 14px; }}
    .section-title h2 {{ font-size: 1.28rem; }}
    .section-title p {{ margin: 0; color: var(--muted); }}
    .archive-action {{ color: var(--blue); font-weight: 900; text-decoration: none; white-space: nowrap; }}
    .archive-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 400px)); gap: 16px; justify-content: start; }}
    .archive-card {{ border: 1px solid var(--line); border-radius: 20px; padding: 18px; background: var(--panel); box-shadow: 0 14px 34px rgba(12,24,54,.075); transition: transform .18s ease, box-shadow .18s ease; }}
    .archive-card:hover {{ transform: translateY(-2px); box-shadow: 0 18px 42px rgba(12,24,54,.12); }}
    .archive-title {{ color: var(--ink); font-size: 1rem; font-weight: 850; text-decoration: none; }}
    .archive-card p {{ margin: 10px 0; color: var(--muted); line-height: 1.55; }}
    .archive-symbols {{ margin: 0 0 14px; }}
    .archive-card .snapshot-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .archive-card .snapshot-column {{ min-height: 118px; padding: 12px; border-radius: 15px; }}
    .archive-card .snapshot-column::after {{ display: none; }}
    .archive-card .snapshot-label {{ font-size: 1rem; }}
    .archive-card .snapshot-window {{ margin-bottom: 8px; }}
    .empty-archive {{ color: var(--muted); }}
    @media (prefers-reduced-motion: reduce) {{
      .primary-action:hover, .archive-card:hover {{ transform: none; }}
    }}
    @media (max-width: 1080px) {{
      .latest-panel {{ grid-template-columns: 1fr; }}
      .market-wave {{ width: 620px; opacity: .35; }}
    }}
    @media (max-width: 880px) {{
      .site-header-inner {{ align-items: flex-start; flex-direction: column; padding-top: 14px; padding-bottom: 14px; }}
      .site-nav {{ justify-content: flex-start; }}
      .snapshot-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      main {{ padding: 0 16px 54px; }}
      .hero {{ min-height: auto; padding: 42px 0 32px; }}
      .market-wave {{ display: none; }}
      h1 {{ font-size: clamp(2.35rem, 14vw, 3.4rem); }}
      .latest-panel {{ padding: 20px; border-radius: 22px; }}
      .section-title {{ align-items: flex-start; flex-direction: column; }}
    }}
    @media (max-width: 520px) {{
      .archive-card .snapshot-grid {{ grid-template-columns: 1fr; }}
      .archive-card .snapshot-column {{ min-height: auto; }}
    }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <nav class="site-nav" aria-label="站点导航">
        <a href="archive.html"><span class="nav-glyph" aria-hidden="true">▦</span>历史归档</a>
        <a href="feed.xml"><span class="nav-glyph" aria-hidden="true">◔</span>RSS 订阅</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero">
      {render_market_wave()}
      <div class="hero-copy">
        <h1>智慧投顾研究系统</h1>
        <p>把主题动量、市场确认和政策/新闻证据整理成普通投资者能读懂的研究结论。页面只展示推荐、周期、背景、理由和风险。投资有风险，不构成投资建议。</p>
      </div>
    </section>
    {latest_block}
    <section class="archive">
      <div class="section-title">
        <div>
          <h2>近期历史报告</h2>
          <p>首页最多显示最近 {INDEX_HISTORY_LIMIT} 期，完整记录保留在归档页</p>
        </div>
        <a class="archive-action" href="archive.html">查看全部</a>
      </div>
      <div class="archive-grid">{archive}</div>
    </section>
  </main>
</body>
</html>
"""


def render_archive_card(report: dict[str, Any]) -> str:
    filename = report_filename(report)
    top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
    top_symbols = [str(symbol) for symbol in report["summary"].get("top_recommended_symbols", [])]
    return f"""
    <article class="archive-card">
      <a class="archive-title" href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(cadence_label(report))}复盘</a>
      <p>主要信号：{html.escape(top_themes or '无')}</p>
      <div class="archive-symbols">{render_symbol_tags(top_symbols)}</div>
      {render_horizon_snapshot(report, linked=True)}
    </article>
    """


def render_archive_html(reports: list[dict[str, Any]]) -> str:
    sorted_reports = sorted(reports, key=lambda item: item["as_of"], reverse=True)
    groups: dict[str, list[dict[str, Any]]] = {}
    for report in sorted_reports:
        key = str(report.get("as_of", ""))[:7] or "unknown"
        groups.setdefault(key, []).append(report)

    sections = []
    for key, group_reports in groups.items():
        year, _, month = key.partition("-")
        title = f"{year} 年 {month} 月" if month else key
        cards = "".join(render_archive_card(report) for report in group_reports)
        sections.append(
            f"""
            <section class="month-group">
              <h2>{html.escape(title)}</h2>
              <div class="archive-grid">{cards}</div>
            </section>
            """
        )
    archive = "".join(sections) or '<p class="empty-archive">暂无报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>历史归档 - 智慧投顾研究系统</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>
    :root {{
      color-scheme: light;
      --ink: #0b1430;
      --muted: #5f6f89;
      --line: #d9e5f4;
      --paper: #f8fbff;
      --panel: rgba(255,255,255,.86);
      --blue: #1d4ed8;
      --cyan: #06a7c8;
      --gold: #d99412;
      --green: #059669;
      --shadow: 0 24px 70px rgba(12,24,54,.12);
      --font-sans: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", ui-sans-serif, system-ui, sans-serif;
      --font-display: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", "STSong", "SimSun", ui-serif, serif;
      font-family: var(--font-sans);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 12%, rgba(6,167,200,.17), transparent 28rem),
        radial-gradient(circle at 92% 6%, rgba(29,78,216,.12), transparent 34rem),
        linear-gradient(135deg, #eef8ff 0%, #f7fbff 45%, #fff8e8 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(12,24,54,.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(12,24,54,.045) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 78%);
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px 24px 72px; position: relative; }}
    .topbar {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 30px; padding: 12px 14px; border: 1px solid rgba(217,229,244,.88); border-radius: 24px; background: rgba(255,255,255,.82); backdrop-filter: blur(18px); box-shadow: 0 16px 42px rgba(12,24,54,.07); }}
    .brand-link {{ display: inline-flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none; font-size: 1.02rem; font-weight: 900; letter-spacing: -.025em; }}
    .brand-link .site-mark {{ width: 38px; height: 38px; margin: 0; }}
    .topbar-actions {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    .topbar-actions a {{ min-height: 38px; display: inline-flex; align-items: center; padding: 0 14px; border: 1px solid rgba(217,229,244,.95); border-radius: 999px; background: rgba(255,255,255,.72); color: var(--ink); text-decoration: none; font-size: .92rem; font-weight: 800; }}
    .site-mark {{ display: inline-flex; width: 64px; height: 64px; filter: drop-shadow(0 18px 28px rgba(29,78,216,.22)); }}
    .site-mark svg {{ width: 100%; height: 100%; }}
    .site-mark rect {{ fill: #0b1430; }}
    .site-mark .mark-line {{ fill: none; stroke: var(--cyan); stroke-width: 5.5; stroke-linecap: round; stroke-linejoin: round; }}
    .site-mark circle {{ fill: #ffffff; }}
    .site-mark .mark-ring {{ fill: none; stroke: #ffffff; stroke-width: 3.2; stroke-linecap: round; opacity: .88; }}
    .hero {{ position: relative; overflow: hidden; padding: 42px 0 46px; }}
    .market-wave {{ position: absolute; right: max(-120px, -8vw); top: 12px; width: min(680px, 56vw); height: auto; opacity: .42; }}
    .eyebrow {{ margin: 0 0 10px; color: var(--blue); font-size: .72rem; font-weight: 850; letter-spacing: .18em; text-transform: uppercase; }}
    h1 {{ margin: 0; font-family: var(--font-display); font-size: clamp(2.2rem, 4.4vw, 3.9rem); font-weight: 800; line-height: 1.06; letter-spacing: -.05em; }}
    .hero p {{ margin: 14px 0 0; max-width: 760px; color: var(--muted); line-height: 1.78; position: relative; z-index: 1; }}
    .month-group {{ margin-top: 30px; position: relative; z-index: 1; }}
    .month-group h2 {{ margin: 0 0 14px; font-size: 1.28rem; font-weight: 850; }}
    .archive-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 400px)); gap: 16px; justify-content: start; }}
    .archive-card {{ border: 1px solid var(--line); border-radius: 20px; padding: 18px; background: var(--panel); box-shadow: 0 14px 34px rgba(12,24,54,.075); transition: transform .18s ease, box-shadow .18s ease; }}
    .archive-card:hover {{ transform: translateY(-2px); box-shadow: 0 18px 42px rgba(12,24,54,.12); }}
    .archive-title {{ color: var(--ink); font-size: 1rem; font-weight: 850; text-decoration: none; }}
    .archive-card p {{ margin: 10px 0; color: var(--muted); line-height: 1.55; }}
    .archive-symbols {{ margin: 0 0 14px; }}
    .symbol-strip {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .symbol-tag {{ display: inline-flex; align-items: center; min-height: 30px; padding: 6px 11px; border-radius: 999px; border: 1px solid rgba(29,78,216,.20); background: #fff; color: var(--ink); font-size: .94rem; font-weight: 850; box-shadow: 0 6px 16px rgba(12,24,54,.06); }}
    .symbol-tag.empty {{ color: var(--muted); font-weight: 700; }}
    .snapshot-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .snapshot-column {{ position: relative; overflow: hidden; padding: 12px; border: 1px solid var(--line); border-radius: 15px; background: rgba(255,255,255,.72); }}
    .snapshot-label {{ margin: 0; font-size: 1rem; font-weight: 850; }}
    .snapshot-window {{ margin: 4px 0 8px; color: var(--muted); font-size: .88rem; }}
    .snapshot-column::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 4px; background: currentColor; }}
    .snapshot-long {{ color: var(--green); }}
    .snapshot-medium {{ color: var(--blue); }}
    .snapshot-short {{ color: var(--gold); }}
    .snapshot-column .symbol-tag {{ color: var(--ink); }}
    .horizon-link {{ color: inherit; text-decoration: none; }}
    .empty-archive {{ color: var(--muted); }}
    @media (max-width: 720px) {{
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .topbar-actions {{ justify-content: flex-start; }}
      .market-wave {{ display: none; }}
      .snapshot-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <nav class="topbar" aria-label="站点导航">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <div class="topbar-actions">
        <a href="index.html">返回首页</a>
        <a href="feed.xml">RSS 订阅</a>
      </div>
    </nav>
    <section class="hero">
      {render_market_wave()}
      <p class="eyebrow">Archive</p>
      <h1>历史归档</h1>
      <p>报告文件长期保留，便于复盘系统结论、观察风格漂移和检查不同阶段的主题变化。首页只展示最新和近期记录，这里按月份列出全部报告。</p>
    </section>
    {archive}
  </main>
</body>
</html>
"""


def render_reports_index_json(reports: list[dict[str, Any]]) -> str:
    items = []
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        as_of = str(report.get("as_of", ""))
        items.append(
            {
                "as_of": as_of,
                "cadence": str(report.get("cadence", "")),
                "html": report_filename(report),
                "json": f"advisory_report_{as_of}.json",
            }
        )
    return json.dumps({"schema_version": 1, "reports": items}, ensure_ascii=False, indent=2) + "\n"


def render_feed_xml(reports: list[dict[str, Any]], *, site_url: str, feed_title: str) -> str:
    channel = ET.Element("channel")
    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "QuantStrategyLab 智慧投顾研究系统，包含推荐理由、周期和风险提示。"
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True)[:RSS_ITEM_LIMIT]:
        filename = report_filename(report)
        link = f"{site_url.rstrip('/')}/{quote(filename)}"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{report['as_of']} {cadence_label(report)}智慧投顾研究"
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid").text = link
        ET.SubElement(item, "pubDate").text = format_datetime(report["generated_at"])
        top_symbols = ", ".join(report["summary"].get("top_recommended_symbols", []))
        top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
        ET.SubElement(item, "description").text = (
            f"主要信号={top_themes or '无'}；系统结论={top_symbols or '无'}。"
            "智慧投顾研究输出；不包含下单、仓位配置或账户级建议。"
        )
    rss = ET.Element("rss", {"version": "2.0"})
    rss.append(channel)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


def publish_reports(report_paths: list[str | Path], output_dir: str | Path, *, site_url: str, feed_title: str) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_paths = unique_report_paths_by_content(report_paths)
    reports = [load_report(path) for path in report_paths]
    written: list[Path] = []
    for report in reports:
        path = output / report_filename(report)
        path.write_text(render_report_html(report), encoding="utf-8")
        written.append(path)
    icon_path = output / SITE_ICON_FILENAME
    icon_path.write_text(SITE_ICON_SVG, encoding="utf-8")
    written.append(icon_path)
    index_path = output / "index.html"
    index_path.write_text(render_index_html(reports), encoding="utf-8")
    written.append(index_path)
    archive_path = output / "archive.html"
    archive_path.write_text(render_archive_html(reports), encoding="utf-8")
    written.append(archive_path)
    reports_index_path = output / "reports_index.json"
    reports_index_path.write_text(render_reports_index_json(reports), encoding="utf-8")
    written.append(reports_index_path)
    feed_path = output / "feed.xml"
    feed_path.write_text(render_feed_xml(reports, site_url=site_url, feed_title=feed_title), encoding="utf-8")
    written.append(feed_path)
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish intelligent advisory research reports as static HTML and RSS.")
    parser.add_argument("--reports", nargs="+", required=True, help="One or more advisory report JSON files.")
    parser.add_argument("--output-dir", required=True, help="Static site output directory.")
    parser.add_argument("--site-url", default="https://quantstrategylab.github.io/QuantAdvisorResearch")
    parser.add_argument("--feed-title", default="智慧投顾研究系统")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    publish_reports(args.reports, args.output_dir, site_url=args.site_url, feed_title=args.feed_title)


if __name__ == "__main__":
    main()

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


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "report"


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


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
    picks = [pick for pick in final_picks if pick.get("primary_horizon") == horizon]
    return sorted(picks, key=lambda pick: (-horizon_pick_score(pick, horizon), str(pick.get("symbol", ""))))


def render_final_card(pick: dict[str, Any], *, rank: int) -> str:
    reasons = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in pick.get("why_selected", []))
    return f"""
    <article class="final-card">
      <header>
        <h3><span class="rank">#{rank}</span>{html.escape(str(pick.get('symbol', '')))}</h3>
        <p>{html.escape(str(pick.get('name', '')))}</p>
      </header>
      <dl>
        <div><dt>周期</dt><dd>{html.escape(str(pick.get('primary_horizon_label', '')))} / {html.escape(str(pick.get('primary_horizon_window', '')))}</dd></div>
        <div><dt>综合分</dt><dd>{html.escape(display_number(pick.get('combined_score')))}</dd></div>
        <div><dt>政策/新闻</dt><dd>{html.escape(display_number(pick.get('source_score')))}</dd></div>
        <div><dt>动量</dt><dd>{html.escape(display_number(pick.get('momentum_score')))}</dd></div>
        <div><dt>主题/背景</dt><dd>{html.escape(display_number(pick.get('medium_context_score', pick.get('ai_signal_score'))))}</dd></div>
      </dl>
      <p><strong>股票背景：</strong>{html.escape(str(pick.get('business_summary', '')))}</p>
      <p><strong>推荐理由：</strong>{html.escape(str(pick.get('prospect_summary', '')))}</p>
      <p><strong>多源依据：</strong></p>
      <ul>{reasons}</ul>
      <p><strong>主要风险：</strong>{html.escape(str(pick.get('risk_summary', '')))}</p>
    </article>
    """


def render_final_decisions_html(report: dict[str, Any]) -> str:
    decisions = report.get("final_decisions", {})
    if not decisions:
        return ""
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    columns = []
    for horizon, label, window in HORIZON_COLUMNS:
        cards = [
            render_final_card(pick, rank=index)
            for index, pick in enumerate(ranked_horizon_picks(final_picks, horizon), start=1)
        ]
        body = "".join(cards) if cards else '<p class="empty-column">暂无</p>'
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
    title = f"量化模型推荐{cadence_label(report)}复盘 - {report['as_of']}"
    final_decisions_html = render_final_decisions_html(report)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="alternate" type="application/rss+xml" title="量化模型推荐 RSS" href="feed.xml">
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #1b1f24; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 56px; }}
    .hero {{ text-align: center; padding: 8px 0 22px; margin-bottom: 10px; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 5vw, 3.25rem); line-height: 1.15; letter-spacing: -0.04em; }}
    .warning {{ background: #fff1f2; border: 1px solid #fecdd3; padding: 14px 16px; margin-bottom: 20px; }}
    .final-decisions {{ margin-bottom: 20px; }}
    .horizon-columns {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-items: start; }}
    .horizon-column {{ background: #eef6ff; border: 1px solid #bfdbfe; border-radius: 14px; padding: 14px; min-height: 160px; }}
    .horizon-column-header {{ text-align: center; margin-bottom: 12px; }}
    .horizon-column-header h2 {{ margin: 0; font-size: 1.35rem; }}
    .horizon-column-header p {{ margin: 4px 0 0; color: #57606a; }}
    .horizon-cards {{ display: grid; gap: 12px; }}
    .empty-column {{ margin: 22px 0; color: #57606a; text-align: center; }}
    .final-card {{ background: #fff; border: 1px solid #d8dee4; border-radius: 12px; padding: 18px; box-shadow: 0 1px 2px rgb(27 31 36 / 4%); }}
    .final-card h3 {{ margin: 0; font-size: 1.35rem; }}
    .final-card header p {{ margin: 4px 0 12px; color: #57606a; }}
    .final-card p {{ line-height: 1.55; color: #334155; }}
    .final-card .rank {{ min-width: 34px; color: #0969da; }}
    .theme-candidates {{ background: #f0fdf4; border: 1px solid #bbf7d0; padding: 16px; margin-bottom: 20px; border-radius: 8px; }}
    .candidate-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .candidate-card {{ background: #fff; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; }}
    .candidate-card header {{ display: flex; gap: 10px; align-items: flex-start; margin-bottom: 10px; }}
    .candidate-card h3 {{ margin: 0; font-size: 1.15rem; }}
    .candidate-card header p {{ margin: 2px 0 0; color: #57606a; }}
    .candidate-card p {{ margin: 8px 0 0; color: #57606a; line-height: 1.5; }}
    .rank {{ display: inline-block; min-width: 40px; color: #166534; font-weight: 800; }}
    .theme-momentum {{ background: #eef6ff; border: 1px solid #bfdbfe; padding: 16px; margin-bottom: 20px; border-radius: 8px; }}
    .recommendation-section {{ margin: 22px 0 8px; }}
    .recommendation-section p {{ color: #57606a; line-height: 1.55; }}
    .monitor-note {{ color: #57606a; background: #fff; border: 1px dashed #d0d7de; border-radius: 8px; padding: 12px 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ text-align: left; border-bottom: 1px solid #eaeef2; padding: 8px; vertical-align: top; }}
    .recommendation {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; padding: 18px; margin: 16px 0; }}
    .recommendation h2 {{ margin: 0; font-size: 1.25rem; }}
    .recommendation h2 span {{ font-size: .85rem; color: #57606a; font-weight: 700; margin-left: 8px; }}
    .recommendation header p {{ margin: 4px 0 14px; color: #57606a; }}
    dl {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin: 0 0 14px; }}
    dl div {{ border: 1px solid #eaeef2; border-radius: 6px; padding: 10px; }}
    dt {{ color: #57606a; font-size: .78rem; text-transform: uppercase; }}
    dd {{ margin: 4px 0 0; font-weight: 600; }}
    .horizon-note {{ line-height: 1.55; color: #57606a; }}
    h3 {{ margin: 18px 0 8px; font-size: 1rem; }}
    li {{ margin: 5px 0; }}
    a {{ color: #0969da; word-break: break-word; }}
    @media (max-width: 920px) {{
      .horizon-columns {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{html.escape(title)}</h1>
    </section>
    {final_decisions_html}
  </main>
</body>
</html>
"""


def format_horizon_summary(report: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
    decisions = report.get("final_decisions", {})
    buckets = decisions.get("horizon_buckets", {}) if isinstance(decisions, dict) else {}
    return [
        (horizon, label, window, [str(symbol) for symbol in buckets.get(horizon, [])])
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
            <p class="eyebrow">Latest briefing</p>
            <h2>{html.escape(latest['as_of'])} {html.escape(cadence_label(latest))}模型推荐</h2>
            <p class="lead">用主题动量、市场确认和事件证据生成的非个性化研究页面。</p>
            <div class="theme-line"><span>主要信号</span>{html.escape(top_themes or '无')}</div>
            <div class="symbol-strip hero-symbols">{render_symbol_tags([str(symbol) for symbol in top_symbols])}</div>
            <a class="primary-action" href="{html.escape(latest_filename)}">打开最新报告</a>
          </div>
          {render_horizon_snapshot(latest)}
        </section>
        """
    items = []
    for report in sorted_reports:
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
    archive = "".join(items) or '<p class="empty-archive">暂无报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>量化模型推荐</title>
  <link rel="alternate" type="application/rss+xml" title="量化模型推荐 RSS" href="feed.xml">
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #667085;
      --line: #d9e2ef;
      --paper: #fffaf0;
      --panel: rgba(255, 255, 255, .78);
      --blue: #1e4dd8;
      --cyan: #00a6c8;
      --gold: #d99b2b;
      --green: #0f8b62;
      font-family: "Avenir Next", "Gill Sans", ui-sans-serif, system-ui, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 8%, rgba(0,166,200,.18), transparent 28rem),
        radial-gradient(circle at 88% 0%, rgba(217,155,43,.18), transparent 24rem),
        linear-gradient(135deg, #f8fafc 0%, #eef4fb 52%, #fff7e6 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(23,32,51,.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(23,32,51,.045) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.75), transparent 78%);
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 34px 20px 64px; position: relative; }}
    .hero {{ display: grid; grid-template-columns: 1fr auto; gap: 24px; align-items: end; padding: 22px 0 28px; }}
    .eyebrow {{ margin: 0 0 10px; color: var(--blue); font-weight: 800; letter-spacing: .16em; text-transform: uppercase; font-size: .78rem; }}
    h1 {{ margin: 0; max-width: 780px; font-family: "Iowan Old Style", Georgia, ui-serif, serif; font-size: clamp(2.55rem, 7vw, 5.7rem); line-height: .92; letter-spacing: -.07em; }}
    .hero p {{ margin: 18px 0 0; max-width: 680px; color: var(--muted); font-size: 1.06rem; line-height: 1.7; }}
    .rss-card {{ justify-self: end; min-width: 170px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 18px; background: rgba(255,255,255,.66); box-shadow: 0 18px 45px rgba(31,45,61,.08); }}
    .rss-card a {{ color: var(--ink); text-decoration: none; font-weight: 800; }}
    .rss-card span {{ display: block; color: var(--muted); margin-top: 5px; font-size: .88rem; }}
    .latest-panel {{ position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr); gap: 22px; border: 1px solid rgba(30,77,216,.16); border-radius: 30px; padding: 26px; background: linear-gradient(135deg, rgba(255,255,255,.9), rgba(255,250,240,.76)); box-shadow: 0 26px 70px rgba(31,45,61,.13); }}
    .latest-panel::after {{ content: ""; position: absolute; right: -80px; top: -110px; width: 260px; height: 260px; border-radius: 999px; background: rgba(0,166,200,.16); filter: blur(2px); }}
    .latest-copy {{ position: relative; z-index: 1; }}
    h2 {{ margin: 0; font-size: clamp(1.7rem, 3vw, 2.55rem); letter-spacing: -.04em; }}
    .lead {{ color: var(--muted); line-height: 1.7; max-width: 620px; }}
    .theme-line {{ display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0 14px; color: var(--ink); }}
    .theme-line span {{ color: var(--blue); font-weight: 800; }}
    .symbol-strip {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .hero-symbols {{ margin-bottom: 20px; }}
    .symbol-tag {{ display: inline-flex; align-items: center; min-height: 30px; padding: 6px 10px; border-radius: 999px; border: 1px solid rgba(30,77,216,.22); background: #fff; color: var(--ink); font-weight: 800; box-shadow: 0 6px 16px rgba(31,45,61,.06); }}
    .symbol-tag.empty {{ color: var(--muted); font-weight: 700; }}
    .primary-action {{ display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 18px; border-radius: 999px; background: var(--ink); color: #fff; text-decoration: none; font-weight: 900; box-shadow: 0 12px 24px rgba(23,32,51,.22); }}
    .primary-action:hover {{ transform: translateY(-1px); }}
    .snapshot-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-self: stretch; position: relative; z-index: 1; }}
    .snapshot-column {{ padding: 16px; border: 1px solid var(--line); border-radius: 22px; background: rgba(255,255,255,.72); backdrop-filter: blur(10px); min-height: 168px; }}
    .snapshot-label {{ margin: 0; font-size: 1.28rem; font-weight: 900; letter-spacing: -.03em; }}
    .snapshot-window {{ margin: 4px 0 14px; color: var(--muted); font-size: .9rem; }}
    .snapshot-long {{ border-top: 4px solid var(--green); }}
    .snapshot-medium {{ border-top: 4px solid var(--blue); }}
    .snapshot-short {{ border-top: 4px solid var(--gold); }}
    .horizon-link {{ color: inherit; text-decoration: none; }}
    .section-title {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 34px 0 14px; }}
    .section-title h2 {{ font-size: 1.45rem; }}
    .section-title p {{ margin: 0; color: var(--muted); }}
    .archive-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .archive-card {{ border: 1px solid var(--line); border-radius: 24px; padding: 18px; background: var(--panel); box-shadow: 0 12px 34px rgba(31,45,61,.08); }}
    .archive-title {{ color: var(--ink); font-size: 1.08rem; font-weight: 900; text-decoration: none; }}
    .archive-card p {{ margin: 10px 0; color: var(--muted); line-height: 1.55; }}
    .archive-symbols {{ margin: 0 0 14px; }}
    .archive-card .snapshot-grid {{ grid-template-columns: 1fr; gap: 8px; }}
    .archive-card .snapshot-column {{ min-height: auto; padding: 12px; border-radius: 16px; }}
    .archive-card .snapshot-label {{ font-size: 1rem; }}
    .archive-card .snapshot-window {{ margin-bottom: 8px; }}
    .empty-archive {{ color: var(--muted); }}
    @media (max-width: 880px) {{
      .hero, .latest-panel {{ grid-template-columns: 1fr; }}
      .rss-card {{ justify-self: start; }}
      .snapshot-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <p class="eyebrow">QuantStrategyLab</p>
        <h1>量化模型推荐</h1>
        <p>把主题动量、市场确认和政策/新闻证据合成为非个性化研究结论。页面只展示推荐、周期、背景、理由和风险。</p>
      </div>
      <aside class="rss-card">
        <a href="feed.xml">RSS 订阅</a>
        <span>周度更新 · 静态页面</span>
      </aside>
    </section>
    {latest_block}
    <section class="archive">
      <div class="section-title">
        <h2>历史报告</h2>
        <p>按发布日期倒序</p>
      </div>
      <div class="archive-grid">{archive}</div>
    </section>
  </main>
</body>
</html>
"""


def render_feed_xml(reports: list[dict[str, Any]], *, site_url: str, feed_title: str) -> str:
    channel = ET.Element("channel")
    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "QuantStrategyLab 非个性化模型推荐，包含理由、周期和风险提示。"
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        filename = report_filename(report)
        link = f"{site_url.rstrip('/')}/{quote(filename)}"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{report['as_of']} {cadence_label(report)}模型推荐"
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid").text = link
        ET.SubElement(item, "pubDate").text = format_datetime(report["generated_at"])
        top_symbols = ", ".join(report["summary"].get("top_recommended_symbols", []))
        top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
        ET.SubElement(item, "description").text = (
            f"主要信号={top_themes or '无'}；推荐={top_symbols or '无'}。"
            "非个性化模型输出；不包含下单、仓位配置或账户级建议。"
        )
    rss = ET.Element("rss", {"version": "2.0"})
    rss.append(channel)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


def publish_reports(report_paths: list[str | Path], output_dir: str | Path, *, site_url: str, feed_title: str) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = [load_report(path) for path in report_paths]
    written: list[Path] = []
    for report in reports:
        path = output / report_filename(report)
        path.write_text(render_report_html(report), encoding="utf-8")
        written.append(path)
    index_path = output / "index.html"
    index_path.write_text(render_index_html(reports), encoding="utf-8")
    written.append(index_path)
    feed_path = output / "feed.xml"
    feed_path.write_text(render_feed_xml(reports, site_url=site_url, feed_title=feed_title), encoding="utf-8")
    written.append(feed_path)
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish model recommendation reports as static HTML and RSS.")
    parser.add_argument("--reports", nargs="+", required=True, help="One or more advisory report JSON files.")
    parser.add_argument("--output-dir", required=True, help="Static site output directory.")
    parser.add_argument("--site-url", default="https://quantstrategylab.github.io/QuantAdvisorResearch")
    parser.add_argument("--feed-title", default="量化模型推荐")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    publish_reports(args.reports, args.output_dir, site_url=args.site_url, feed_title=args.feed_title)


if __name__ == "__main__":
    main()

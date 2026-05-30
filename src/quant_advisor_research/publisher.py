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

from .advisory_report import display_number, display_percent


CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}


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


def render_theme_first_candidates_html(report: dict[str, Any]) -> str:
    candidates = report.get("theme_first_candidates", [])
    if not candidates:
        return ""
    cards = []
    for candidate in candidates:
        theme_ids = ", ".join(candidate.get("theme_ids", [])) or "无"
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
                <div><dt>主题</dt><dd>{html.escape(str(candidate.get('primary_theme_id', '')))}</dd></div>
                <div><dt>动量强度</dt><dd>{html.escape(display_number(candidate.get('symbol_momentum_score')))}</dd></div>
                <div><dt>近3个月</dt><dd>{html.escape(display_percent(candidate.get('return_3m')))}</dd></div>
                <div><dt>事件确认</dt><dd>{html.escape(str(candidate.get('source_confirmation', '')))}</dd></div>
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
      <h2>本期重点股票池</h2>
      <p><strong>先看这里：</strong>每期选出 5-10 个股票/公司标的，说明行业主题、入选理由、事件确认和主要风险。</p>
      <p><strong>怎么理解：</strong>这是非个性化模型股票池，不是买入清单；“待事件确认”表示稳定事件证据还不足；
      “背景跟踪”表示证据较弱，仅保留为研究背景。</p>
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
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(theme.get('rank', '')))}</td>"
            f"<td><code>{html.escape(str(theme.get('theme_id', '')))}</code><br>{html.escape(str(theme.get('theme_name', '')))}</td>"
            f"<td>{html.escape(str(theme.get('sector', '')))}</td>"
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
    source_mode = str(report["summary"].get("source_mode", "unknown"))
    data_warnings = list(report["summary"].get("data_quality_warnings", []))
    warning_html = ""
    if source_mode == "fixture" or data_warnings:
        warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in data_warnings)
        warning_html = f"""
    <section class="warning">
      <strong>来源模式：{html.escape(source_mode)}</strong>
      <ul>{warning_items}</ul>
    </section>
        """
    theme_candidates_html = render_theme_first_candidates_html(report)
    theme_momentum_html = render_theme_momentum_html(report)
    recommendation_cards = []
    background_cards = []
    for rec in report["recommendations"]:
        reasons = "\n".join(f"<li>{html.escape(reason)}</li>" for reason in rec["reasons"])
        risks = "\n".join(f"<li>{html.escape(risk)}</li>" for risk in rec["risk_notes"])
        checklist = "\n".join(f"<li>{html.escape(check)}</li>" for check in rec["review_checklist"])
        refs = "\n".join(
            f'<li><a href="{html.escape(ref)}">{html.escape(ref)}</a></li>' if ref.startswith("http") else f"<li>{html.escape(ref)}</li>"
            for ref in rec["evidence_refs"]
        )
        card_html = f"""
            <article class="recommendation">
              <header>
                <h2>{html.escape(rec['symbol'])} <span>{html.escape(rec['rating_label'])}</span></h2>
                <p>{html.escape(rec.get('name') or rec['symbol'])}</p>
              </header>
              <dl>
                <div><dt>周期</dt><dd>{html.escape(rec['primary_horizon_label'])}</dd></div>
                <div><dt>窗口</dt><dd>{html.escape(rec['primary_horizon_window'])}</dd></div>
                <div><dt>层级</dt><dd>{html.escape(rec['recommendation_tier_label'])}</dd></div>
                <div><dt>来源</dt><dd>{html.escape(rec['source_confidence_label'])}</dd></div>
                <div><dt>风格</dt><dd>{html.escape(rec['strategy_style'])}</dd></div>
                <div><dt>分数</dt><dd>{rec['score']}</dd></div>
                <div><dt>证据</dt><dd>{rec['evidence_score']}</dd></div>
                <div><dt>风险</dt><dd>{rec['risk_score']}</dd></div>
              </dl>
              <p class="horizon-note">{html.escape(rec['horizon_note'])}</p>
              <h3>推荐理由</h3>
              <ul>{reasons}</ul>
              <h3>风险提示</h3>
              <ul>{risks}</ul>
              <h3>复核清单</h3>
              <ul>{checklist}</ul>
              <h3>证据链接</h3>
              <ul>{refs}</ul>
            </article>
            """
        if rec.get("recommendation_tier") == "monitor":
            background_cards.append(card_html)
        else:
            recommendation_cards.append(card_html)
    background_html = ""
    if background_cards:
        background_html = f"""
    <details class="background-list">
      <summary>背景跟踪（非推荐，{len(background_cards)}项）</summary>
      <p>这些标的只保留为研究背景，当前证据不足，不进入推荐或观察摘要。</p>
      {''.join(background_cards)}
    </details>
        """
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
    .hero {{ border-bottom: 1px solid #d8dee4; padding-bottom: 20px; margin-bottom: 24px; }}
    h1 {{ margin: 0 0 12px; font-size: 2rem; line-height: 1.2; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; color: #57606a; }}
    .pill {{ border: 1px solid #d0d7de; border-radius: 999px; padding: 5px 10px; background: #fff; }}
    .policy {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 14px 16px; margin-bottom: 20px; }}
    .warning {{ background: #fff1f2; border: 1px solid #fecdd3; padding: 14px 16px; margin-bottom: 20px; }}
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
    .background-list {{ margin-top: 18px; background: #fff; border: 1px dashed #d0d7de; border-radius: 8px; padding: 14px 16px; }}
    .background-list summary {{ cursor: pointer; font-weight: 800; }}
    .background-list > p {{ color: #57606a; }}
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
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{html.escape(title)}</h1>
      <div class="meta">
        <span class="pill">模式：{html.escape(report['mode'])}</span>
        <span class="pill">受众：{html.escape(report['audience_scope'])}</span>
        <span class="pill">AI 状态：{html.escape(str(report['summary']['ai_regime']))}</span>
        <span class="pill">来源：{html.escape(source_mode)}</span>
        <span class="pill">主题候选：{report['summary'].get('theme_first_candidate_count', 0)}</span>
        <span class="pill">推荐数：{report['summary']['recommendation_count']}</span>
      </div>
    </section>
    <section class="policy">
      <strong>政策边界：</strong>当前只允许非个性化模型推荐；
      不允许下单、组合配置、账户适当性判断或个性化建议。
    </section>
    {warning_html}
    {theme_candidates_html}
    {theme_momentum_html}
    <section class="recommendation-section">
      <h2>事件确认推荐与观察列表</h2>
      <p>这里基于事件证据、来源置信度和 AI 长周期背景生成。“背景跟踪”表示证据不足，不进入推荐；
      “先核验来源”表示低置信来源不能直接升级。</p>
    </section>
    {''.join(recommendation_cards)}
    {background_html}
  </main>
</body>
</html>
"""


def render_index_html(reports: list[dict[str, Any]]) -> str:
    items = []
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        filename = report_filename(report)
        top_symbols = ", ".join(report["summary"].get("top_recommended_symbols", []))
        theme_candidate_symbols = ", ".join(report["summary"].get("top_theme_candidate_symbols", []))
        top_themes = ", ".join(report["summary"].get("top_theme_ids", []))
        source_mode = str(report["summary"].get("source_mode", "unknown"))
        items.append(
            f"""
            <li>
              <a href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(cadence_label(report))}复盘</a>
              <span>来源：{html.escape(source_mode)}；主题：{html.escape(top_themes or '无')}；主题候选：{html.escape(theme_candidate_symbols or '无')}；推荐：{html.escape(top_symbols or '无')}</span>
            </li>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>量化模型推荐</title>
  <link rel="alternate" type="application/rss+xml" title="量化模型推荐 RSS" href="feed.xml">
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #f6f7f9; color: #1b1f24; }}
    main {{ max-width: 900px; margin: 0 auto; padding: 40px 20px; }}
    h1 {{ margin-bottom: 8px; }}
    p {{ color: #57606a; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; padding: 14px 16px; margin: 12px 0; }}
    a {{ color: #0969da; font-weight: 700; text-decoration: none; }}
    span {{ display: block; color: #57606a; margin-top: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>量化模型推荐</h1>
    <p>展示非个性化模型推荐、理由、周期和风险提示。不包含下单、仓位配置或个性化建议。</p>
    <p><a href="feed.xml">RSS 订阅</a></p>
    <ul>{''.join(items)}</ul>
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
        theme_candidate_symbols = ", ".join(report["summary"].get("top_theme_candidate_symbols", []))
        top_themes = ", ".join(report["summary"].get("top_theme_ids", []))
        source_mode = str(report["summary"].get("source_mode", "unknown"))
        ET.SubElement(item, "description").text = (
            f"模式={report['mode']}；来源={source_mode}；主题={top_themes or '无'}；"
            f"主题候选={theme_candidate_symbols or '无'}；推荐={top_symbols or '无'}。"
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

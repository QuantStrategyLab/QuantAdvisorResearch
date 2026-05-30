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
    return f"{report['as_of']}-{slug(report['cadence'])}-research-radar.html"


def render_report_html(report: dict[str, Any]) -> str:
    title = f"Quant Research Radar {report['cadence'].title()} Review - {report['as_of']}"
    research_cards = []
    for item in report["research_items"]:
        risks = "\n".join(f"<li>{html.escape(risk)}</li>" for risk in item["risks"])
        checklist = "\n".join(f"<li>{html.escape(check)}</li>" for check in item["review_checklist"])
        refs = "\n".join(
            f'<li><a href="{html.escape(ref)}">{html.escape(ref)}</a></li>' if ref.startswith("http") else f"<li>{html.escape(ref)}</li>"
            for ref in item["evidence_refs"]
        )
        research_cards.append(
            f"""
            <article class="research-item">
              <header>
                <h2>{html.escape(item['symbol'])} <span>{html.escape(item['review_status'])}</span></h2>
                <p>{html.escape(item.get('name') or item['symbol'])}</p>
              </header>
              <dl>
                <div><dt>Research View</dt><dd>{html.escape(item['research_view'])}</dd></div>
                <div><dt>Lens</dt><dd>{html.escape(item['research_lens'])}</dd></div>
                <div><dt>Review Priority</dt><dd>{item['research_priority']}</dd></div>
                <div><dt>Evidence</dt><dd>{item['evidence_score']}</dd></div>
                <div><dt>Risk</dt><dd>{item['risk_score']}</dd></div>
              </dl>
              <p class="summary">{html.escape(item['evidence_summary'])}</p>
              <p class="rating-boundary">Not an investment rating.</p>
              <h3>Risks</h3>
              <ul>{risks}</ul>
              <h3>Review Checklist</h3>
              <ul>{checklist}</ul>
              <h3>Evidence</h3>
              <ul>{refs}</ul>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="alternate" type="application/rss+xml" title="Quant Research Radar RSS" href="feed.xml">
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #1b1f24; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 56px; }}
    .hero {{ border-bottom: 1px solid #d8dee4; padding-bottom: 20px; margin-bottom: 24px; }}
    h1 {{ margin: 0 0 12px; font-size: 2rem; line-height: 1.2; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; color: #57606a; }}
    .pill {{ border: 1px solid #d0d7de; border-radius: 999px; padding: 5px 10px; background: #fff; }}
    .policy {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 14px 16px; margin-bottom: 20px; }}
    .research-item {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; padding: 18px; margin: 16px 0; }}
    .research-item h2 {{ margin: 0; font-size: 1.25rem; }}
    .research-item h2 span {{ font-size: .85rem; color: #57606a; font-weight: 500; margin-left: 8px; }}
    .research-item header p {{ margin: 4px 0 14px; color: #57606a; }}
    dl {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin: 0 0 14px; }}
    dl div {{ border: 1px solid #eaeef2; border-radius: 6px; padding: 10px; }}
    dt {{ color: #57606a; font-size: .78rem; text-transform: uppercase; }}
    dd {{ margin: 4px 0 0; font-weight: 600; }}
    .summary {{ line-height: 1.55; }}
    .rating-boundary {{ color: #57606a; font-size: .92rem; font-weight: 600; }}
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
        <span class="pill">Mode: {html.escape(report['mode'])}</span>
        <span class="pill">Audience: {html.escape(report['audience_scope'])}</span>
        <span class="pill">AI regime: {html.escape(str(report['summary']['ai_regime']))}</span>
        <span class="pill">Items: {report['summary']['item_count']}</span>
      </div>
    </section>
    <section class="policy">
      <strong>Policy boundary:</strong> direct stock recommendations, execution, portfolio allocation,
      and personalized advice are disabled. This report is non-personalized research triage only.
    </section>
    {''.join(research_cards)}
  </main>
</body>
</html>
"""


def render_index_html(reports: list[dict[str, Any]]) -> str:
    items = []
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        filename = report_filename(report)
        top_symbols = ", ".join(report["summary"].get("top_review_symbols", []))
        items.append(
            f"""
            <li>
              <a href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(report['cadence'].title())} Review</a>
              <span>Review queue: {html.escape(top_symbols)}</span>
            </li>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Quant Research Radar</title>
  <link rel="alternate" type="application/rss+xml" title="Quant Research Radar RSS" href="feed.xml">
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
    <h1>Quant Research Radar</h1>
    <p>Non-personalized research triage reports. No buy/sell/hold ratings, execution, portfolio allocation, or personalized advice.</p>
    <p><a href="feed.xml">RSS feed</a></p>
    <ul>{''.join(items)}</ul>
  </main>
</body>
</html>
"""


def render_feed_xml(reports: list[dict[str, Any]], *, site_url: str, feed_title: str) -> str:
    channel = ET.Element("channel")
    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "QuantStrategyLab research radar reports without direct stock recommendations."
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        filename = report_filename(report)
        link = f"{site_url.rstrip('/')}/{quote(filename)}"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{report['as_of']} {report['cadence'].title()} Research Radar"
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid").text = link
        ET.SubElement(item, "pubDate").text = format_datetime(report["generated_at"])
        top_symbols = ", ".join(report["summary"].get("top_review_symbols", []))
        ET.SubElement(item, "description").text = (
            f"Mode={report['mode']}; audience={report['audience_scope']}; review queue={top_symbols}. "
            "No buy/sell/hold rating, execution, or portfolio allocation."
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
    parser = argparse.ArgumentParser(description="Publish research radar reports as static HTML and RSS.")
    parser.add_argument("--reports", nargs="+", required=True, help="One or more advisory report JSON files.")
    parser.add_argument("--output-dir", required=True, help="Static site output directory.")
    parser.add_argument("--site-url", default="https://quantstrategylab.github.io/QuantAdvisorResearch")
    parser.add_argument("--feed-title", default="Quant Research Radar")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    publish_reports(args.reports, args.output_dir, site_url=args.site_url, feed_title=args.feed_title)


if __name__ == "__main__":
    main()

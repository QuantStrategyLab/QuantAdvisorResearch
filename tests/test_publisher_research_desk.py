from __future__ import annotations

import copy
import datetime as dt
import re
from html.parser import HTMLParser

import pytest

from quant_advisor_research.publisher import (
    render_archive_html,
    render_feed_xml,
    render_index_html,
    render_report_html,
    render_reports_index_json,
    report_filename,
)

METHOD_HREF = 'https://github.com/QuantStrategyLab/QuantAdvisorResearch/blob/main/docs/system-design.zh-CN.md'


HORIZON_META = {
    "long": ("长线", "1-3年"),
    "medium": ("中线", "2-12周"),
    "short": ("短线", "1-10个交易日"),
}
NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.UTC)


def make_pick(symbol: str, horizon: str = "medium", score: float = 0.8) -> dict:
    label, window = HORIZON_META[horizon]
    return {
        "symbol": symbol,
        "name": f"{symbol} Systems",
        "primary_horizon": horizon,
        "primary_horizon_label": label,
        "primary_horizon_window": window,
        "combined_score": score,
        "source_score": 0.6,
        "momentum_score": 0.9,
        "medium_context_score": 0.7,
        "long_context_score": 0.6,
        "horizon_scores": {name: {"score": score if name == horizon else 0.1} for name in HORIZON_META},
        "horizon_actions": {
            name: ("recommend" if name == horizon else "skip") for name in HORIZON_META
        },
        "business_summary": f"{symbol} 业务背景（合成）",
        "prospect_summary": f"{symbol} 推荐理由（合成）",
        "risk_summary": f"{symbol} 主要风险（合成）",
    }


def make_report(
    *,
    as_of: str = "2026-11-03",
    picks: list[dict] | None = None,
    horizon_summary: dict | None = None,
    input_checks: list[dict] | None = None,
    sources: list[dict] | None = None,
    expires_at: str | None = "2026-11-10T00:00:00Z",
) -> dict:
    picks = [make_pick("MMED1"), make_pick("LLONG1", "long")] if picks is None else picks
    report: dict = {
        "schema_version": "6",
        "contract_version": "model_recommendations.v6",
        "mode": "model_recommendations",
        "as_of": as_of,
        "cadence": "weekly",
        "generated_at": f"{as_of}T01:00:00Z",
        "summary": {
            "top_theme_ids": ["grid_equipment"],
            "top_recommended_symbols": [pick["symbol"] for pick in picks],
            "data_quality_warnings": [],
        },
        "final_decisions": {"recommendations": picks},
        "freshness": {
            name: {"present": True, "valid": True, "reason": "fresh"}
            for name in ("ai_signal", "theme_momentum")
        },
        "input_checks": input_checks
        if input_checks is not None
        else [
            {"name": "political_events", "detail": "parsed", "status": "available", "as_of": "2026-10-31"},
            {"name": "political_watchlist", "detail": "parsed", "status": "available", "as_of": None},
        ],
        "sources": sources
        if sources is not None
        else [
            {
                "url": "https://example.invalid/evidence",
                "type": "political_event",
                "fetched_at": None,
                "status": "unverified",
            }
        ],
    }
    if horizon_summary is not None:
        report["final_decisions"]["horizon_summary"] = horizon_summary
    if expires_at is None:
        report.pop("expires_at", None)
    else:
        report["expires_at"] = expires_at
    return report


def make_legacy_report() -> dict:
    report = make_report(expires_at=None)
    report.update(schema_version="5", contract_version="model_recommendations.v5")
    for key in ("freshness", "input_checks", "sources"):
        report.pop(key, None)
    return report


def test_every_page_has_research_only_strip_and_footer_disclaimer() -> None:
    report = make_report()
    pages = {
        "index": render_index_html([report], now=NOW),
        "index-empty": render_index_html([], now=NOW),
        "report": render_report_html(report),
        "archive": render_archive_html([report]),
        "archive-empty": render_archive_html([]),
    }
    for name, page in pages.items():
        assert "仅供研究" in page, name
        assert "RESEARCH ONLY" in page, name
        assert "投资有风险。本站内容为模型研究输出" in page, name
        assert "不构成投资建议、要约或任何收益承诺" in page, name
        assert "报告在有效期后不再作为当前结论；历史报告仅供查阅。" in page, name
        assert "设计稿 · 合成示例数据" not in page, name
        assert "Design mockup · synthetic data" not in page, name


def test_report_page_states_expiry_instant_statically_and_marks_legacy_unknown() -> None:
    current = render_report_html(make_report())
    assert 'data-expires="2026-11-10T00:00:00Z"' in current
    assert "2026-11-10 00:00 UTC" in current
    assert "有效期至" in current
    assert "当前有效" in current
    assert "已过期" in current
    assert "<noscript>" in current
    assert "旧版报告格式" not in current

    legacy = render_report_html(make_legacy_report())
    assert 'data-expires="' not in legacy
    assert "旧版报告格式（v5）。" in legacy
    assert "有效期未记录" in legacy
    assert "未记录（旧版报告）" in legacy
    assert "此报告未记录有效期、输入检查和来源列表。" in legacy


def test_home_expired_latest_keeps_expired_badge_and_banner() -> None:
    expired = make_report(as_of="2026-11-02", expires_at="2020-01-01T00:00:00Z")
    page = render_index_html([expired], now=NOW)
    latest = page.split('id="latest"', 1)[1]
    assert "当前展示的报告已过期。" in page
    assert "已于 2020-01-01 过期" in page
    assert "已过期" in latest
    assert "最近一期 · 已过期" in latest
    assert 'datetime="2026-11-02"' in latest


@pytest.mark.parametrize("offset_ms", [-1000, 0, 1])
def test_home_expiry_controls_survive_static_generation(offset_ms: int) -> None:
    report = make_report()
    expiry = dt.datetime.fromisoformat(report["expires_at"])
    page = render_index_html([report], now=expiry + dt.timedelta(milliseconds=offset_ms))

    class ExpiryControls(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.controls: list[dict] = []

        def handle_starttag(self, tag: str, attrs: list) -> None:
            values = dict(attrs)
            if any(key in values for key in ("data-expires", "data-when-current", "data-when-expired")):
                self.controls.append(values)

    parser = ExpiryControls()
    parser.feed(page)
    markers = [attrs for attrs in parser.controls if "data-expires" in attrs]
    assert [attrs["data-expires"] for attrs in markers] == [report["expires_at"]]
    current = [attrs for attrs in parser.controls if "data-when-current" in attrs]
    expired = [attrs for attrs in parser.controls if "data-when-expired" in attrs]
    assert len(current) == 1
    assert len(expired) == 2  # The badge and the associated expiry notice.
    assert all("hidden" in attrs for attrs in current + expired)
    fallback = re.search(r"<noscript>(.*?)</noscript>", page, flags=re.DOTALL)
    assert fallback is not None
    assert "See validity" in fallback.group(1)
    assert "Current" not in fallback.group(1)
    assert "2026-11-10 00:00 UTC" in page


def test_home_without_expiry_keeps_unknown_status_without_timer_controls() -> None:
    page = render_index_html([make_legacy_report()], now=NOW)
    assert 'data-expires="' not in page
    assert 'data-when-current hidden' not in page
    assert 'data-when-expired hidden' not in page
    assert "Latest · expiry not recorded" in page


def test_horizon_summary_null_max_score_renders_not_evaluated_not_zero() -> None:
    summary = {name: {"max_score": None, "threshold": threshold} for name, threshold in
               (("short", 0.60), ("medium", 0.52), ("long", 0.62))}
    report = make_report(horizon_summary=summary)

    report_html = render_report_html(report)
    scorelines = re.findall(r'<div class="scoreline">.*?</div>', report_html, flags=re.DOTALL)
    assert len(scorelines) == 3
    assert all("未评估" in line for line in scorelines)
    assert "0.00" not in report_html

    index_html = render_index_html([report], now=NOW)
    assert "未评估" in index_html
    assert "0.00" not in index_html


def test_horizon_summary_absent_hides_score_column() -> None:
    report = make_report(horizon_summary=None)
    report_html = render_report_html(report)
    assert "最高分" not in report_html
    assert "分数达到门槛本身不构成推荐。" not in report_html

    index_html = render_index_html([report], now=NOW)
    assert "最高分" not in index_html
    assert "最高分 / 门槛" not in index_html


def test_threshold_is_read_from_report_not_hardcoded() -> None:
    summary = {
        "short": {"max_score": 0.41, "threshold": 0.55},
        "medium": {"max_score": 0.58, "threshold": 0.47},
        "long": {"max_score": 0.64, "threshold": 0.71},
    }
    html = render_report_html(make_report(horizon_summary=summary))
    for expected in ("0.55", "0.47", "0.71"):
        assert expected in html
    for default in ("0.60", "0.52", "0.62"):
        assert default not in html


def test_input_checks_statuses_distinct_and_null_date_not_substituted() -> None:
    checks = [
        {"name": "political_events", "detail": "parsed", "status": "available", "as_of": "2026-10-31"},
        {"name": "political_watchlist", "detail": "parsed, undated", "status": "stale", "as_of": None},
        {"name": "ai_signal", "detail": "not_provided", "status": "missing", "as_of": None},
        {"name": "theme_momentum", "detail": "rejected", "status": "invalid", "as_of": None},
        {"name": "market_confirmation", "detail": "unknown", "status": "unknown", "as_of": None},
    ]
    html = render_report_html(make_report(input_checks=checks))
    rows = re.findall(r"<tr>.*?</tr>", html, flags=re.DOTALL)
    expected = {
        "political_events": ("b-ok", "可用"),
        "political_watchlist": ("b-warn", "过期"),
        "ai_signal": ("b-bad", "缺失"),
        "theme_momentum": ("b-bad", "无效 / 不可用"),
        "market_confirmation": ("b-unk", "未知"),
    }
    for name, (badge_class, label) in expected.items():
        row = next(item for item in rows if name in item)
        assert f"badge {badge_class}" in row, name
        assert label in row, name

    watchlist_row = next(item for item in rows if "political_watchlist" in item)
    assert "2026-11-03" not in watchlist_row
    assert "未记录" in watchlist_row


def test_sources_unverified_null_fetched_at_and_safe_links() -> None:
    sources = [
        {
            "url": "https://example.invalid/evidence?a=1&b=2",
            "type": "political_event",
            "fetched_at": None,
            "status": "unverified",
        },
        {
            "url": "https://example.invalid/<script>alert(1)</script>",
            "type": "watchlist",
            "fetched_at": None,
            "status": "unverified",
        },
        {
            "url": 'javascript:alert("x")',
            "type": "watchlist",
            "fetched_at": None,
            "status": "unverified",
        },
        {
            "url": 'https://example.invalid/quote" onclick="x',
            "type": "political_event",
            "fetched_at": None,
            "status": "unverified",
        },
    ]
    html = render_report_html(make_report(sources=sources))

    assert 'href="https://example.invalid/evidence?a=1&amp;b=2"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="javascript:' not in html
    assert "javascript:alert" in html
    assert 'onclick="x' not in html
    assert html.count('rel="nofollow noopener noreferrer"') == 3
    assert "未抓取" in html
    assert "未核验" in html


def test_absent_optional_additions_hide_sections_for_v5() -> None:
    legacy = make_legacy_report()
    report_html = render_report_html(legacy)
    assert 'id="inputs"' not in report_html
    assert 'id="sources"' not in report_html
    assert 'id="inputs-h"' not in report_html
    assert 'id="sources-h"' not in report_html
    assert "来源链接" not in report_html
    assert "最高分" not in report_html
    assert "旧版报告格式（v5）。" in report_html

    index_html = render_index_html([legacy], now=NOW)
    assert "输入状态未记录（旧版报告格式）；不能视为输入完整。" in index_html


def test_watchlist_and_overflow_never_rendered_as_picks() -> None:
    report = make_report(picks=[make_pick("PICKOK")])
    report["final_decisions"]["watchlist"] = [{"symbol": "WATCHONLY", "primary_horizon": "short"}]
    report["final_decisions"]["overflow_recommendations"] = [{"symbol": "OVERFLOWX", "primary_horizon": "long"}]

    report_html = render_report_html(report)
    index_html = render_index_html([report], now=NOW)
    archive_html = render_archive_html([report])
    feed = render_feed_xml([report], site_url="https://example.invalid/advisor", feed_title="Test Feed")
    index_json = render_reports_index_json([report])

    for output in (report_html, index_html, archive_html, feed, index_json):
        assert "WATCHONLY" not in output
        assert "OVERFLOWX" not in output
    assert "PICKOK" in report_html
    assert "PICKOK" in index_html
    assert "PICKOK" in archive_html
    assert '"recommendation_count": 1' in index_json


def test_zero_pick_unverified_does_not_claim_below_gate() -> None:
    report = make_report(picks=[])
    report["freshness"] = {"ai_signal": {"present": False, "valid": False, "reason": "not_provided"}}

    index_html = render_index_html([report], now=NOW)
    assert "本期三个周期均未产生合格推荐，且输入不完整。" in index_html
    assert "此空结果不能解读为“信号未达门槛”" in index_html
    assert "空结果本身就是结论：信号未达到门槛" not in index_html
    assert "候选未达到推荐门槛" not in index_html

    report_html = render_report_html(report)
    assert "输入不完整，见下方输入状态。" in report_html
    assert "候选未达到推荐门槛。" not in report_html


def test_filenames_links_and_method_href_unchanged() -> None:
    report = make_report()
    assert report_filename(report) == "2026-11-03-weekly-model-recommendations.html"
    filename = report_filename(report)

    report_html = render_report_html(report)
    index_html = render_index_html([report], now=NOW)
    archive_html = render_archive_html([report])
    for page in (report_html, index_html, archive_html):
        assert 'href="index.html"' in page
        assert 'href="archive.html"' in page
        assert 'href="feed.xml"' in page
        assert 'href="favicon.svg"' in page
        assert f'href="{METHOD_HREF}"' in page
        assert 'rel="alternate" type="application/rss+xml"' in page
    assert f'href="{filename}"' in index_html
    assert f'href="{filename}"' in archive_html


def test_reports_index_json_and_feed_bytes_unchanged() -> None:
    report = make_report()
    report["summary"]["top_theme_ids"] = []

    expected_index = (
        "{\n"
        '  "schema_version": 1,\n'
        '  "reports": [\n'
        "    {\n"
        '      "as_of": "2026-11-03",\n'
        '      "cadence": "weekly",\n'
        '      "html": "2026-11-03-weekly-model-recommendations.html",\n'
        '      "json": "advisory_report_2026-11-03.json",\n'
        '      "recommendation_count": 2,\n'
        '      "horizon_counts": {\n'
        '        "short": 0,\n'
        '        "medium": 1,\n'
        '        "long": 1\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    assert render_reports_index_json([report]) == expected_index

    expected_feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Test Feed</title>'
        "<link>https://example.invalid/advisor</link>"
        "<description>QuantStrategyLab 智慧投顾研究系统，包含推荐理由、周期和风险提示。</description>"
        "<item><title>2026-11-03 周度智慧投顾研究</title>"
        "<link>https://example.invalid/advisor/2026-11-03-weekly-model-recommendations.html</link>"
        "<guid>https://example.invalid/advisor/2026-11-03-weekly-model-recommendations.html</guid>"
        "<pubDate>Tue, 03 Nov 2026 01:00:00 GMT</pubDate>"
        "<description>主要信号=无；系统结论=MMED1, LLONG1。"
        "智慧投顾研究输出；不包含下单、仓位配置或账户级建议。</description>"
        "</item></channel></rss>"
    )
    assert render_feed_xml([report], site_url="https://example.invalid/advisor", feed_title="Test Feed") == expected_feed


def test_home_overlapping_validity_notice_only_describes_displayed_report() -> None:
    from test_publisher import build_sample_report

    from quant_advisor_research.contracts import validate_advisory_report
    from quant_advisor_research.publisher import is_report_expired

    weekly = build_sample_report()
    weekly.update(generated_at="2026-11-03T00:00:00Z", expires_at="2026-11-10T00:00:00Z")
    monthly = copy.deepcopy(weekly)
    monthly.update(cadence="monthly", generated_at="2026-11-04T00:00:00Z", expires_at="2026-11-11T00:00:00Z")
    for report in (weekly, monthly):
        validate_advisory_report(report)
    expiry = dt.datetime.fromisoformat(weekly["expires_at"])
    after = expiry + dt.timedelta(milliseconds=1001)
    assert is_report_expired(weekly, now=after)
    assert not is_report_expired(monthly, now=after)

    page = render_index_html([weekly, monthly], now=expiry - dt.timedelta(seconds=1))
    latest = page.split('id="latest"', 1)[1].split("<aside", 1)[0]
    assert report_filename(weekly) in latest
    assert report_filename(monthly) in page
    notice = re.search(r'<div class="notice n-warn"[^>]*data-when-expired[^>]*>(.*?)</div>', page, re.DOTALL)
    assert notice is not None
    assert "No current report is available." not in notice.group(1)
    assert "当前没有有效报告。" not in notice.group(1)
    assert "The displayed report has expired." in notice.group(1)
    assert "当前展示的报告已过期。" in notice.group(1)

    fresh = render_index_html([weekly, monthly], now=after)
    assert report_filename(monthly) in fresh.split('id="latest"', 1)[1].split("<aside", 1)[0]

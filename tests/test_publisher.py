from __future__ import annotations

from pathlib import Path

from quant_advisor_research.advisory_report import build_advisory_report, write_json
from quant_advisor_research.publisher import publish_reports, render_feed_xml, render_report_html


ROOT = Path(__file__).resolve().parents[1]


def build_sample_report() -> dict:
    return build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )


def test_render_report_html_contains_policy_boundary() -> None:
    html = render_report_html(build_sample_report())

    assert "政策边界" in html
    assert "不允许下单" in html
    assert "EVT1" in html
    assert "2-12周" in html
    assert "来源模式：fixture" in html
    assert "仅监控标的未在页面展开" in html
    assert "背景跟踪（非推荐" not in html
    assert "复核清单" not in html


def test_render_feed_xml_contains_report_item() -> None:
    feed = render_feed_xml([build_sample_report()], site_url="https://example.com/advisor", feed_title="Test Feed")

    assert "<rss version=\"2.0\">" in feed
    assert "2026-05-30 周度模型推荐" in feed
    assert "来源=fixture" in feed
    assert "非个性化模型输出；不包含下单、仓位配置或账户级建议。" in feed


def test_publish_reports_writes_site_files(tmp_path: Path) -> None:
    report = build_sample_report()
    report_path = tmp_path / "report.json"
    write_json(report_path, report)

    written = publish_reports([report_path], tmp_path / "site", site_url="https://example.com/advisor", feed_title="Test")

    filenames = {path.name for path in written}
    assert "index.html" in filenames
    assert "feed.xml" in filenames
    assert "2026-05-30-weekly-model-recommendations.html" in filenames


def test_render_report_html_includes_theme_momentum_context() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/ai_long_horizon_signal.example.json",
    )
    report["summary"]["top_theme_ids"] = ["hbm_memory"]
    report["theme_momentum"] = {
        "available": True,
        "as_of": "2026-05-30",
        "taxonomy_version": "test-v1",
        "top_themes": [
            {
                "rank": 1,
                "theme_id": "hbm_memory",
                "theme_name": "HBM and memory",
                "sector": "technology",
                "momentum_score": 0.91,
                "breadth_3m": 1.0,
                "top_symbols": ["MU"],
            }
        ],
    }
    report["summary"]["theme_first_candidate_count"] = 1
    report["summary"]["top_theme_candidate_symbols"] = ["MU"]
    report["theme_first_candidates"] = [
        {
            "rank": 1,
            "symbol": "MU",
            "name": "Micron Technology",
            "primary_theme_id": "hbm_memory",
            "primary_theme_name": "HBM and memory",
            "symbol_momentum_score": 0.88,
            "return_3m": 0.28,
            "advisor_status": "主题候选",
            "source_confirmation": "暂无明确事件催化",
            "industry_background": "科技 / HBM / 存储",
            "recommendation_summary": "属于科技 / HBM / 存储，个股动量靠前。",
            "risk_summary": "需复核估值、财报、回撤和流动性；当前暂无明确事件催化。",
            "theme_ids": ["hbm_memory"],
            "themes": [{"theme_id": "hbm_memory", "theme_name": "HBM and memory"}],
            "reasons": ["主题动量排序靠前。"],
        }
    ]

    html = render_report_html(report)

    assert "本期重点股票池" in html
    assert "先看这里" in html
    assert "+28.0%" in html
    assert "为什么入选" in html
    assert "主题动量" in html
    assert "HBM / 存储" in html
    assert "事件证据" in html
    assert "暂无明确事件催化" in html
    assert "hbm_memory" not in html
    assert "MU" in html


def test_format_telegram_message_contains_themes_policy_and_link() -> None:
    from quant_advisor_research.notifications import format_telegram_message

    report = build_sample_report()
    report["summary"]["top_theme_ids"] = ["hbm_memory"]
    report["theme_momentum"] = {
        "available": True,
        "as_of": "2026-05-30",
        "top_themes": [
            {
                "rank": 1,
                "theme_id": "hbm_memory",
                "momentum_score": 0.9,
                "top_symbols": ["MU"],
            }
        ],
    }
    report["theme_first_candidates"] = [
        {
            "rank": 1,
            "symbol": "MU",
            "primary_theme_id": "hbm_memory",
            "symbol_momentum_score": 0.88,
            "return_3m": 0.28,
            "advisor_status": "主题候选",
            "source_confirmation": "暂无明确事件催化",
            "industry_background": "科技 / HBM / 存储",
            "recommendation_summary": "属于科技 / HBM / 存储，个股动量靠前。",
        }
    ]

    message = format_telegram_message(report, site_url="https://example.com/advisor")

    assert "量化模型推荐" in message
    assert "本期重点股票池" in message
    assert "不等于买入" in message
    assert "近3月" in message
    assert "事件证据" in message
    assert "为什么" in message
    assert "HBM / 存储" in message
    assert "MU" in message
    assert "不包含下单" in message
    assert "https://example.com/advisor/2026-05-30-weekly-model-recommendations.html" in message

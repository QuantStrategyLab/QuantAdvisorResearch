from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from quant_advisor_research.advisory_report import build_advisory_report, write_json
from quant_advisor_research.publisher import (
    publish_reports,
    render_archive_html,
    render_feed_xml,
    render_index_html,
    render_report_html,
    render_reports_index_json,
)


ROOT = Path(__file__).resolve().parents[1]


def build_sample_report() -> dict:
    return build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
    )


def test_render_report_html_is_direct_public_recommendation_page() -> None:
    html = render_report_html(build_sample_report())

    assert "智慧投顾研究周度复盘 - 2026-05-30" in html
    assert "text-align: center" in html
    assert "report-shell" in html
    assert "report-hero" in html
    assert "topbar" in html
    assert "--font-sans" in html
    assert "--font-display" in html
    assert "PingFang SC" in html
    assert "Songti SC" in html
    assert "返回首页" in html
    assert "RSS 订阅" in html
    assert "Report date" in html
    assert 'rel="icon" type="image/svg+xml" href="favicon.svg"' in html
    assert "site-mark" in html
    assert "2-12周" in html
    assert "来源模式：fixture" not in html
    assert "股票背景" in html
    assert "推荐理由" in html
    assert "主要风险" in html
    assert "按长线、中线、短线分栏展示系统结论" not in html
    assert "本期结论：" in html
    assert "长线：暂无稳定结论" in html
    assert "中线：MU、NVDA" in html
    assert "短线：暂无稳定结论" in html
    assert "本期较突出的方向主要在科技板块" in html
    assert "综合分" not in html
    assert "多源依据" not in html
    assert "<span class=\"pill\">模式：" not in html
    assert "受众：" not in html
    assert "AI 状态：" not in html
    assert "政策边界" not in html
    assert "不允许下单" not in html
    assert "本期最终结论" not in html
    assert "最终推荐：" not in html
    assert "合成口径" not in html
    assert "ResearchSignalContextPipelines" not in html
    assert "背景跟踪（非推荐" not in html
    assert "复核清单" not in html
    assert "主题候选（解释材料，不是最终推荐）" not in html
    assert "最终推荐" not in html


def test_render_feed_xml_contains_report_item() -> None:
    feed = render_feed_xml([build_sample_report()], site_url="https://example.com/advisor", feed_title="Test Feed")

    assert "<rss version=\"2.0\">" in feed
    assert "2026-05-30 周度智慧投顾研究" in feed
    assert "来源=fixture" not in feed
    assert "来源=" not in feed
    assert "主要信号=" in feed
    assert "最终推荐" not in feed
    assert "智慧投顾研究输出；不包含下单、仓位配置或账户级建议。" in feed


def test_publish_reports_writes_site_files(tmp_path: Path) -> None:
    report = build_sample_report()
    report_path = tmp_path / "report.json"
    write_json(report_path, report)

    written = publish_reports([report_path], tmp_path / "site", site_url="https://example.com/advisor", feed_title="Test")

    filenames = {path.name for path in written}
    assert "index.html" in filenames
    assert "feed.xml" in filenames
    assert "favicon.svg" in filenames
    assert "archive.html" in filenames
    assert "reports_index.json" in filenames
    assert "2026-05-30-weekly-model-recommendations.html" in filenames
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    archive_html = (tmp_path / "site" / "archive.html").read_text(encoding="utf-8")
    favicon = (tmp_path / "site" / "favicon.svg").read_text(encoding="utf-8")
    assert "来源：" not in index_html
    assert "主要信号" in index_html
    assert "最终推荐" not in index_html
    assert 'rel="icon" type="image/svg+xml" href="favicon.svg"' in index_html
    assert "site-mark" in index_html
    assert "<svg" in favicon
    assert "#172033" in favicon
    assert "Latest advisory" in index_html
    assert "历史归档" in index_html
    assert "投资有风险，不构成投资建议。" in index_html
    assert "周度更新 · 静态页面" not in index_html
    assert "近期历史报告" in index_html
    assert "archive.html" in index_html
    assert "历史归档" in archive_html
    assert "2026 年 05 月" in archive_html
    assert "--font-sans" in index_html
    assert "--font-display" in index_html
    assert "latest-panel" in index_html
    assert "snapshot-grid" in index_html
    assert "<p class=\"snapshot-label\">长线</p>" in index_html
    assert "<p class=\"snapshot-label\">中线</p>" in index_html
    assert "<p class=\"snapshot-label\">短线</p>" in index_html
    assert "打开最新报告" in index_html


def make_report_for_date(base_report: dict, as_of: str) -> dict:
    report = deepcopy(base_report)
    report["as_of"] = as_of
    report["generated_at"] = f"{as_of}T00:00:00+00:00"
    return report


def test_index_limits_recent_history_and_archive_keeps_all_reports() -> None:
    base = build_sample_report()
    reports = [make_report_for_date(base, f"2026-05-{day:02d}") for day in range(1, 23)]

    index_html = render_index_html(reports)
    archive_html = render_archive_html(reports)
    feed = render_feed_xml(reports, site_url="https://example.com/advisor", feed_title="Test Feed")
    report_index = render_reports_index_json(reports)

    assert "2026-05-22 周度智慧投顾研究" in index_html
    assert index_html.count('class="archive-card"') == 12
    assert "2026-05-21 周度复盘" in index_html
    assert "2026-05-10 周度复盘" in index_html
    assert "2026-05-09 周度复盘" not in index_html
    assert "查看全部" in index_html
    assert "archive.html" in index_html
    assert archive_html.count('class="archive-card"') == 22
    assert "2026-05-01 周度复盘" in archive_html
    assert feed.count("<item>") == 20
    assert "2026-05-03 周度智慧投顾研究" in feed
    assert "2026-05-02 周度智慧投顾研究" not in feed
    assert '"reports"' in report_index
    assert '"as_of": "2026-05-22"' in report_index
    assert '"json": "advisory_report_2026-05-01.json"' in report_index


def test_render_report_html_does_not_show_fixture_warning_for_live_paths(tmp_path: Path) -> None:
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    political_events = live_dir / "political_events.csv"
    political_watchlist = live_dir / "political_watchlist.csv"
    ai_signal = live_dir / "research_signal_context.json"
    theme_momentum = live_dir / "theme_momentum_snapshot.json"
    political_events.write_text((ROOT / "examples/political_events.example.csv").read_text(encoding="utf-8"), encoding="utf-8")
    political_watchlist.write_text((ROOT / "examples/political_watchlist.example.csv").read_text(encoding="utf-8"), encoding="utf-8")
    ai_signal.write_text((ROOT / "examples/research_signal_context.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    theme_momentum.write_text((ROOT / "examples/theme_momentum_snapshot.example.json").read_text(encoding="utf-8"), encoding="utf-8")

    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=political_events,
        political_watchlist_path=political_watchlist,
        ai_signal_path=ai_signal,
        theme_momentum_path=theme_momentum,
    )
    html = render_report_html(report)

    assert report["summary"]["source_mode"] == "operator_supplied"
    assert report["summary"]["data_quality_warnings"] == []
    assert "来源模式" not in html
    assert "Input artifacts include example fixture paths" not in html


def test_render_report_html_groups_final_cards_by_horizon_and_rank() -> None:
    report = build_sample_report()

    def pick(symbol: str, horizon: str, score: float) -> dict:
        labels = {"long": "长线", "medium": "中线", "short": "短线"}
        windows = {"long": "1-3年", "medium": "2-12周", "short": "1-10个交易日"}
        return {
            "symbol": symbol,
            "name": symbol,
            "primary_horizon": horizon,
            "primary_horizon_label": labels[horizon],
            "primary_horizon_window": windows[horizon],
            "combined_score": score,
            "source_score": 0.0,
            "momentum_score": score,
            "medium_context_score": score,
            "horizon_scores": {
                "long": {"score": score if horizon == "long" else 0.0},
                "medium": {"score": score if horizon == "medium" else 0.0},
                "short": {"score": score if horizon == "short" else 0.0},
            },
            "horizon_actions": {
                "long": "recommend" if horizon == "long" else "skip",
                "medium": "recommend" if horizon == "medium" else "skip",
                "short": "recommend" if horizon == "short" else "skip",
            },
            "business_summary": f"{symbol} background",
            "prospect_summary": f"{symbol} reason",
            "why_selected": ["ranked"],
            "risk_summary": "risk",
        }

    report["final_decisions"]["recommendations"] = [
        pick("MID2", "medium", 0.6),
        pick("SHORT1", "short", 0.7),
        pick("LONG1", "long", 0.8),
        pick("MID1", "medium", 0.9),
    ]

    html = render_report_html(report)

    assert "horizon-columns" in html
    assert "horizon-long" in html
    assert "horizon-medium" in html
    assert "horizon-short" in html
    assert html.index("<h2>长线</h2>") < html.index("<h2>中线</h2>") < html.index("<h2>短线</h2>")
    assert html.index("推荐 #1</span>MID1") < html.index("推荐 #2</span>MID2")
    assert "推荐 #1</span>LONG1" in html
    assert "推荐 #1</span>SHORT1" in html
    assert "最终推荐" not in html




def test_short_and_medium_columns_use_primary_horizon_only() -> None:
    report = build_sample_report()
    report["final_decisions"]["recommendations"] = [
        {
            "symbol": "MU",
            "name": "Micron",
            "primary_horizon": "medium",
            "primary_horizon_label": "中线",
            "primary_horizon_window": "2-12周",
            "combined_score": 0.9,
            "source_score": 0.6,
            "momentum_score": 1.0,
            "medium_context_score": 0.9,
            "long_context_score": 0.6,
            "horizon_scores": {
                "short": {"score": 0.88},
                "medium": {"score": 0.9},
                "long": {"score": 0.7},
            },
            "horizon_actions": {"short": "recommend", "medium": "recommend", "long": "recommend"},
            "business_summary": "MU background",
            "prospect_summary": "MU reason",
            "why_selected": ["ranked"],
            "risk_summary": "risk",
        },
        {
            "symbol": "DELL",
            "name": "Dell",
            "primary_horizon": "short",
            "primary_horizon_label": "短线",
            "primary_horizon_window": "1-10个交易日",
            "combined_score": 0.8,
            "source_score": 0.6,
            "momentum_score": 0.7,
            "medium_context_score": 0.7,
            "long_context_score": 0.6,
            "horizon_scores": {
                "short": {"score": 0.8},
                "medium": {"score": 0.7},
                "long": {"score": 0.65},
            },
            "horizon_actions": {"short": "recommend", "medium": "recommend", "long": "recommend"},
            "business_summary": "DELL background",
            "prospect_summary": "DELL reason",
            "why_selected": ["ranked"],
            "risk_summary": "risk",
        },
    ]

    html = render_report_html(report)

    assert "本期结论：长线：MU、DELL；中线：MU；短线：DELL。" in html
    assert "<h2>短线</h2>" in html
    short_start = html.index("<h2>短线</h2>")
    short_block = html[short_start:]
    assert "推荐 #1</span>DELL" in short_block
    assert "推荐 #1</span>MU" not in short_block

def test_render_report_html_renders_long_context_as_full_card_when_primary_bucket_is_medium() -> None:
    report = build_sample_report()
    report["final_decisions"]["recommendations"] = [
        {
            "symbol": "MU",
            "name": "Micron Technology",
            "primary_horizon": "medium",
            "primary_horizon_label": "中线",
            "primary_horizon_window": "2-12周",
            "combined_score": 0.9,
            "source_score": 0.1,
            "momentum_score": 0.9,
            "medium_context_score": 0.9,
            "long_context_score": 0.62,
            "horizon_scores": {
                "long": {"score": 0.66},
                "medium": {"score": 0.9},
                "short": {"score": 0.1},
            },
            "horizon_actions": {
                "long": "watch",
                "medium": "recommend",
                "short": "skip",
            },
            "business_summary": "MU background",
            "prospect_summary": "MU reason",
            "why_selected": ["ranked"],
            "risk_summary": "risk",
        }
    ]

    html = render_report_html(report)

    assert "长线观察" not in html
    assert "推荐 #1</span>MU" in html
    assert "长线 / 1-3年" in html
    assert "MU background" in html
    assert "MU reason" in html
    assert "本期结论：长线：MU；中线：MU；短线：暂无稳定结论。" in html
    assert "最终推荐" not in html


def test_render_report_html_includes_theme_momentum_context() -> None:
    report = build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        ai_signal_path=ROOT / "examples/research_signal_context.example.json",
        theme_momentum_path=ROOT / "examples/theme_momentum_snapshot.example.json",
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

    assert "本期最终结论" not in html
    assert "最终推荐：" not in html
    assert "合成口径" not in html
    assert "政策边界" not in html
    assert "<span class=\"pill\">模式：" not in html
    assert "受众：" not in html
    assert "AI 状态：" not in html
    assert "主题/背景" not in html
    assert "综合分" not in html
    assert "多源依据" not in html
    assert "AI信号仓库" not in html
    assert "ResearchSignalContextPipelines" not in html
    assert "股票背景" in html
    assert "推荐理由" in html
    assert "主要风险" in html
    assert "按长线、中线、短线分栏展示系统结论" not in html
    assert "本期结论：" in html
    assert "长线：暂无稳定结论" in html
    assert "中线：MU、NVDA" in html
    assert "短线：暂无稳定结论" in html
    assert "本期较突出的方向主要在科技板块" in html
    assert "存储周期" in html
    assert "需复核估值、财报、回撤和流动性" not in html
    assert "做什么" not in html
    assert "为什么有前景" not in html
    assert "买多少" not in html
    assert "仓位/数量" not in html
    assert "主题候选（解释材料，不是最终推荐）" not in html
    assert "最终推荐" not in html
    assert "主题动量" not in html
    assert "事件证据" not in html
    assert "hbm_memory" not in html
    assert "MU" in html


def test_format_telegram_message_is_direct_and_links_report() -> None:
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

    assert "智慧投顾研究系统" in message
    assert "本期推荐" in message
    assert "AI信号仓库" not in message
    assert "股票背景" in message
    assert "推荐理由" in message
    assert "买多少" not in message
    assert "主题候选" not in message
    assert "事件证据" not in message
    assert "模式：" not in message
    assert "来源：" not in message
    assert "不包含下单" not in message
    assert "MU" in message
    assert "https://example.com/advisor/2026-05-30-weekly-model-recommendations.html" in message

from __future__ import annotations

import datetime as dt
import re
from copy import deepcopy

from test_publisher import build_sample_report

from quant_advisor_research.contracts import validate_advisory_report
from quant_advisor_research.publisher import (
    render_archive_html,
    render_feed_xml,
    render_index_html,
    render_report_html,
    render_reports_index_json,
    report_filename,
)


def _zero_pick_report(*, verified: bool = False) -> dict:
    report = build_sample_report()
    report["final_decisions"]["recommendations"] = []
    report["final_decisions"]["horizon_buckets"] = {"long": [], "medium": [], "short": []}
    report["final_decisions"]["horizon_rankings"] = {
        horizon: [{"symbol": "CANDIDATE", "action": "watch", "score": 0.1}]
        for horizon in ("long", "medium", "short")
    }
    if verified:
        report["summary"]["data_quality_warnings"] = []
    else:
        report["summary"]["data_quality_warnings"] = ["missing_market_confirmation"]
    return report


def test_every_page_has_research_only_strip_and_footer_disclaimer() -> None:
    report = build_sample_report()
    pages = [
        render_index_html([report]),
        render_index_html([]),
        render_report_html(report),
        render_archive_html([report]),
        render_archive_html([]),
    ]
    for page in pages:
        assert "仅供研究" in page
        assert "RESEARCH ONLY" in page
        assert 'id="disclaimer"' in page
        assert "免责声明" in page
        assert "投资有风险。" in page


def test_report_page_states_expiry_instant_statically_and_marks_legacy_unknown() -> None:
    report = build_sample_report()
    report["expires_at"] = "2026-11-07T06:00:00Z"
    page = render_report_html(report)
    assert "2026-11-07 06:00 UTC" in page
    assert 'data-expires="2026-11-07T06:00:00Z"' in page
    assert "有效期至" in page

    legacy = build_sample_report()
    legacy.update(schema_version="5", contract_version="model_recommendations.v5")
    for key in ("reference_time", "expires_at", "freshness", "input_digest"):
        legacy.pop(key, None)
    legacy_page = render_report_html(legacy)
    assert "有效期未记录" in legacy_page
    assert "旧版报告格式（v5）" in legacy_page
    assert "未记录（旧版报告）" in legacy_page


def test_home_expired_latest_keeps_expired_badge_and_banner() -> None:
    report = build_sample_report()
    report["expires_at"] = "2020-01-01T00:00:00Z"
    page = render_index_html([report], now=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))
    assert "已过期" in page
    assert "当前没有有效报告。" in page
    assert 'id="latest"' in page


def test_horizon_summary_null_max_score_renders_not_evaluated_not_zero() -> None:
    report = build_sample_report()
    report["final_decisions"]["horizon_summary"] = {
        horizon: {"max_score": None, "threshold": 0.6}
        for horizon in ("short", "medium", "long")
    }
    page = render_report_html(report)
    conclusions = page.split('id="conclusions"', 1)[1]
    assert "未评估" in conclusions
    assert "0.00" not in conclusions


def test_horizon_summary_absent_hides_score_column() -> None:
    report = build_sample_report()
    report["final_decisions"].pop("horizon_summary", None)
    page = render_report_html(report)
    assert "最高分 / 门槛" not in page
    assert "Max score / gate" not in page


def test_threshold_is_read_from_report_not_hardcoded() -> None:
    report = build_sample_report()
    report["final_decisions"]["horizon_summary"] = {
        "short": {"max_score": 0.5, "threshold": 0.55},
        "medium": {"max_score": 0.5, "threshold": 0.52},
        "long": {"max_score": 0.5, "threshold": 0.62},
    }
    page = render_report_html(report)
    conclusions = page.split('id="conclusions"', 1)[1]
    assert "0.55" in conclusions
    assert "0.60" not in conclusions


def test_input_checks_statuses_distinct_and_null_date_not_substituted() -> None:
    report = build_sample_report()
    report["input_checks"] = [
        {"name": "political_events", "detail": "fresh", "status": "available", "as_of": "2026-05-29"},
        {"name": "political_watchlist", "detail": "parsed", "status": "available", "as_of": None},
        {"name": "ai_signal", "detail": "not_provided", "status": "missing", "as_of": None},
        {"name": "theme_momentum", "detail": "expired_context", "status": "stale", "as_of": "2026-05-20"},
        {"name": "market_confirmation", "detail": "context_unavailable", "status": "invalid", "as_of": None},
        {"name": "extra_input", "detail": "unknown_state", "status": "unknown", "as_of": None},
    ]
    page = render_report_html(report)
    for label in ("可用", "缺失", "过期", "无效 / 不可用", "未知"):
        assert label in page
    inputs = page.split('id="inputs"', 1)[1].split('id="sources"', 1)[0]
    assert "未记录" in inputs
    assert "2026-05-30" not in inputs


def test_sources_unverified_null_fetched_at_and_safe_links() -> None:
    report = build_sample_report()
    report["sources"] = [
        {
            "url": 'https://example.invalid/x?a=1&b=2"onmouseover="alert(1)',
            "type": "political_event",
            "fetched_at": None,
            "status": "unverified",
        }
    ]
    page = render_report_html(report)
    assert 'rel="nofollow noopener noreferrer"' in page
    assert "未核验" in page
    assert "未抓取" in page
    assert "&amp;b=2" in page
    assert "&quot;onmouseover=&quot;" in page
    assert 'onmouseover="alert' not in page


def test_absent_optional_additions_hide_sections_for_v5() -> None:
    report = build_sample_report()
    report.update(schema_version="5", contract_version="model_recommendations.v5")
    for key in ("reference_time", "expires_at", "freshness", "input_digest"):
        report.pop(key, None)
    report.pop("input_checks", None)
    report.pop("sources", None)
    report["final_decisions"].pop("horizon_summary", None)
    # With neither optional checks nor recorded blockers, keep the section hidden.
    report["summary"]["data_quality_warnings"] = []
    page = render_report_html(report)
    assert 'id="inputs"' not in page
    assert 'id="sources"' not in page
    assert "最高分 / 门槛" not in page


def test_watchlist_and_overflow_never_rendered_as_picks() -> None:
    report = build_sample_report()
    report["final_decisions"]["recommendations"] = []
    report["final_decisions"]["watchlist"] = [{"symbol": "WATCHONLY", "primary_horizon": "short"}]
    report["final_decisions"]["overflow_recommendations"] = [
        {"symbol": "OVERFLOWONLY", "primary_horizon": "short"}
    ]
    page = render_report_html(report)
    assert "WATCHONLY" not in page
    assert "OVERFLOWONLY" not in page
    assert "观察名单与溢出候选不在此列" in page


def test_zero_pick_unverified_does_not_claim_below_gate() -> None:
    report = _zero_pick_report(verified=False)
    page = render_index_html([report])
    assert "不能解读为“信号未达门槛”" in page
    assert "空结果本身就是结论" not in page
    report_page = render_report_html(report)
    assert "原因见下方输入状态。" in report_page
    assert "候选未达到推荐门槛" not in report_page


def _contract_valid_missing_ranking_report() -> dict:
    """Contract-valid empty report whose horizon rankings are absent.

    Inputs are fresh and verified, so freshness alone cannot justify a
    below-threshold conclusion; only the missing ranking evidence is unknown.
    """
    report = deepcopy(build_sample_report())
    report["final_decisions"]["recommendations"] = []
    report["final_decisions"]["horizon_buckets"] = {"long": [], "medium": [], "short": []}
    report["final_decisions"]["horizon_rankings"] = {}
    report["summary"]["data_quality_warnings"] = []
    report["generated_at"] = "2026-05-31T12:00:00Z"
    report["expires_at"] = "2026-06-07T12:00:00Z"
    report["source_artifacts"]["ai_signal"] = "synthetic/ai_signal.json"
    report["source_artifacts"]["theme_momentum"] = "synthetic/theme_momentum.json"
    report["freshness"] = {
        name: {
            "present": True,
            "valid": True,
            "reason": "fresh",
            "as_of": "2026-05-30",
            "generated_at": "2026-05-30T00:00:00Z",
            "expires_at": "2026-06-06T00:00:00Z",
        }
        for name in ("ai_signal", "theme_momentum")
    }
    report["input_checks"] = _all_input_checks_available()
    validate_advisory_report(report)
    return report


def _all_input_checks_available() -> list[dict]:
    """Producer-shaped input checks when every input was supplied and fresh."""
    return [
        {"name": "political_events", "detail": "parsed", "status": "available", "as_of": "2026-05-30"},
        {"name": "political_watchlist", "detail": "parsed", "status": "available", "as_of": None},
        {"name": "ai_signal", "detail": "fresh", "status": "available", "as_of": "2026-05-30"},
        {"name": "theme_momentum", "detail": "fresh", "status": "available", "as_of": "2026-05-30"},
        {"name": "market_confirmation", "detail": "parsed", "status": "available", "as_of": "2026-05-30"},
    ]


def test_missing_ranking_evidence_is_not_presented_as_below_threshold() -> None:
    """Regression for the r2-verify adverse case.

    Fresh inputs plus an empty ``horizon_rankings`` must not turn into
    "candidates did not meet the gate" on the report page. The homepage already
    distinguishes absent ranking evidence from an evaluated below-gate result;
    the report page must agree.
    """
    report = _contract_valid_missing_ranking_report()
    page = render_report_html(report)
    conclusions = page.split('id="conclusions"', 1)[1]
    assert conclusions.count("候选未达到推荐门槛") == 0
    assert "Candidates did not meet the gate" not in page
    assert conclusions.count("本期无推荐") == 3
    assert conclusions.count("原因见下方输入状态。") == 3
    # The homepage keeps the same honest unknown state for this fixture.
    assert "候选未达到推荐门槛" not in render_index_html([report])


def test_verified_inputs_without_rankings_keep_homepage_conclusion_unknown() -> None:
    from quant_advisor_research.publisher import index_inputs_verified

    report = _contract_valid_missing_ranking_report()
    assert index_inputs_verified(report)
    page = render_index_html([report])
    assert "Inputs were verified complete" in page
    assert "Ranking evidence is missing for one or more horizons" in page
    assert "inputs are incomplete" not in page
    assert "Some inputs are missing, stale or unavailable" not in page
    assert "signals did not meet the gate" not in page
    assert "部分周期缺少排名证据" in page


def test_filenames_links_and_method_href_unchanged() -> None:
    report = build_sample_report()
    assert report_filename(report) == "2026-05-30-weekly-model-recommendations.html"
    method_url = (
        "https://github.com/QuantStrategyLab/QuantAdvisorResearch/blob/main/"
        "docs/system-design.zh-CN.md"
    )
    for page in (render_index_html([report]), render_report_html(report), render_archive_html([report])):
        assert 'href="archive.html"' in page
        assert 'href="feed.xml"' in page
        assert 'href="favicon.svg"' in page
        assert method_url in page


def test_reports_index_json_and_feed_bytes_unchanged() -> None:
    report = {
        "as_of": "2026-05-30",
        "cadence": "weekly",
        "generated_at": "2026-05-31T12:00:00Z",
        "summary": {"top_recommended_symbols": ["ALPH", "BRVO"], "top_theme_ids": ["grid"]},
        "final_decisions": {
            "recommendations": [
                {"symbol": "ALPH", "primary_horizon": "medium"},
                {"symbol": "BRVO", "primary_horizon": "long"},
            ]
        },
    }
    expected_index = """{
  "schema_version": 1,
  "reports": [
    {
      "as_of": "2026-05-30",
      "cadence": "weekly",
      "html": "2026-05-30-weekly-model-recommendations.html",
      "json": "advisory_report_2026-05-30.json",
      "recommendation_count": 2,
      "horizon_counts": {
        "short": 0,
        "medium": 1,
        "long": 1
      }
    }
  ]
}
"""
    assert render_reports_index_json([report]) == expected_index
    assert render_reports_index_json([report]) == render_reports_index_json([report])

    feed_first = render_feed_xml([report], site_url="https://example.invalid/advisor", feed_title="Test")
    feed_second = render_feed_xml([report], site_url="https://example.invalid/advisor", feed_title="Test")
    assert feed_first == feed_second
    assert "<rss version=\"2.0\">" in feed_first
    assert "2026-05-30 周度智慧投顾研究" in feed_first


def test_multi_horizon_card_ids_and_aria_references_are_unique() -> None:
    """Regression for the r1 verify adverse duplicate-id case.

    A medium-primary pick whose long action is ``watch`` is rendered as a full
    card in both the long and the medium column. The card id and its
    ``aria-labelledby`` reference must therefore include the horizon.
    """
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
            "horizon_actions": {"long": "watch", "medium": "recommend", "short": "skip"},
            "business_summary": "MU background",
            "prospect_summary": "MU reason",
            "why_selected": ["ranked"],
            "risk_summary": "risk",
        }
    ]

    page = render_report_html(report)
    ids = re.findall(r'\bid="([^"]+)"', page)
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    assert not duplicates, f"duplicate HTML ids: {duplicates}"

    references = re.findall(r'aria-labelledby="([^"]+)"', page)
    assert set(references) <= set(ids), "aria-labelledby points at a missing id"

    assert 'id="p-long-MU"' in page
    assert 'id="p-medium-MU"' in page
    assert 'aria-labelledby="p-long-MU"' in page
    assert 'aria-labelledby="p-medium-MU"' in page


def _expiry_hooks(page: str) -> dict[str, list[str]]:
    visible = re.findall(r'<span class="badge (b-\w+)" (data-when-\w+)>', page)
    hidden = re.findall(r'<span class="badge (b-\w+)" (data-when-\w+) hidden>', page)
    return {"visible": [f"{css} {hook}" for css, hook in visible], "hidden": [f"{css} {hook}" for css, hook in hidden]}


def test_home_status_is_bound_to_the_expiry_instant_not_the_publication_run() -> None:
    """Regression: the home badge was a publication-time constant.

    A visitor who opens the home page after ``expires_at`` must not be shown
    "Current" while the report page of the same report says "Expired".
    """
    report = build_sample_report()
    report["expires_at"] = "2026-11-07T06:00:00Z"
    page = render_index_html([report], now=dt.datetime(2026, 11, 3, tzinfo=dt.UTC))

    assert '<span data-expires="2026-11-07T06:00:00Z"></span>' in page
    assert _expiry_hooks(page) == {
        "visible": ["b-ok data-when-current"],
        "hidden": ["b-warn data-when-expired"],
    }
    assert '<span data-when-current>' in page
    assert '<span data-when-expired hidden>' in page
    # The expired notice ships hidden and only the client clock can reveal it.
    assert '<div class="notice n-warn" role="note" data-when-expired hidden>' in page
    assert "以下为最近一期报告，已于 2026-11-07 过期" in page


def test_home_expired_at_publication_shows_expired_and_keeps_current_hidden() -> None:
    report = build_sample_report()
    report["expires_at"] = "2020-01-01T00:00:00Z"
    page = render_index_html([report], now=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))

    assert _expiry_hooks(page) == {
        "visible": ["b-warn data-when-expired"],
        "hidden": ["b-ok data-when-current"],
    }
    assert '<div class="notice n-warn" role="note" data-when-expired>' in page
    assert "当前没有有效报告。" in page


def test_legacy_home_status_stays_unknown_and_emits_no_expiry_hooks() -> None:
    report = build_sample_report()
    report.update(schema_version="5", contract_version="model_recommendations.v5")
    for key in ("reference_time", "expires_at", "freshness", "input_digest"):
        report.pop(key, None)
    page = render_index_html([report], now=dt.datetime(2026, 11, 3, tzinfo=dt.UTC))

    assert "<span data-expires=" not in page
    assert "data-when-current" not in page.split("<script>")[0]
    assert "最新 · 有效期未记录" in page
    assert "当前有效" not in page


def test_expiry_state_is_refreshed_while_the_page_stays_open() -> None:
    page = render_report_html(build_sample_report())
    script = re.search(r"<script>(.*)</script>", page, re.DOTALL)
    assert script is not None
    body = script.group(1)

    assert "function updateExpiry()" in body
    assert "updateExpiry();" in body
    assert re.search(r"window\.setInterval\(updateExpiry,\s*1000\)", body)
    assert 'document.addEventListener("visibilitychange", updateExpiry)' in body
    # The instant itself is still strictly exclusive: equal is not expired.
    assert "var expired = now > exp;" in body


def test_archived_report_exposes_recorded_input_blockers_without_promoting_candidates() -> None:
    report = _zero_pick_report()
    report.pop("input_checks", None)
    report["summary"]["data_quality_warnings"] = [
        "ai_signal_provenance_untrusted", "theme_momentum_stale_as_of",
    ]
    report["freshness"] = {
        "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
        "theme_momentum": {"present": True, "valid": False, "reason": "stale_as_of"},
    }
    before = deepcopy(report)
    for page in (render_index_html([report]), render_report_html(report)):
        assert "AI signal provenance was not trusted" in page
        assert "Theme momentum predates the report freshness window" in page
        assert "These recorded blockers do not establish complete input checks" in page
        assert "CANDIDATE" not in page
    full = render_report_html(report)
    assert 'id="inputs"' in full
    assert 'href="#inputs"' in full
    assert report == before


def test_archived_input_diagnostics_never_echo_unknown_warning_or_infer_health() -> None:
    report = _zero_pick_report()
    report.pop("input_checks", None)
    report["summary"]["data_quality_warnings"] = ["private-debug-example", "theme_momentum_stale_as_of"]
    report["freshness"] = {"ai_signal": {"valid": True, "reason": "fresh"}}
    for page in (render_index_html([report]), render_report_html(report)):
        assert "Theme momentum predates the report freshness window" in page
        assert "private-debug-example" not in page
        assert "These recorded blockers do not establish complete input checks" in page
        assert "inputs are complete" not in page.lower()


# --- F1: zero-pick summary must not imply complete inputs merely missed a gate ---

_HEALTHY_WAIT_ZH = "继续等待更清晰的主题和价格确认"
_HEALTHY_WAIT_EN = "wait for clearer theme and price confirmation"
_INCOMPLETE_NOTICE_ZH = "此空结果不能解读为“信号未达门槛”"
_INCOMPLETE_NOTICE_EN = "cannot be read as “signals below the gate”"


def _f1_incomplete_report() -> dict:
    return _zero_pick_report(verified=False)


def _f1_untrusted_report() -> dict:
    report = _zero_pick_report()
    report["summary"]["data_quality_warnings"] = ["ai_signal_provenance_untrusted"]
    report["freshness"]["ai_signal"] = {"present": True, "valid": False, "reason": "provenance_untrusted"}
    return report


def _f1_stale_report() -> dict:
    report = _zero_pick_report()
    report.pop("input_checks", None)
    report["summary"]["data_quality_warnings"] = ["theme_momentum_stale_as_of"]
    report["freshness"]["theme_momentum"] = {"present": True, "valid": False, "reason": "stale_as_of"}
    report["theme_momentum"] = {"available": False, "top_themes": []}
    return report


def _f1_unknown_report() -> dict:
    report = _zero_pick_report()
    report.pop("input_checks", None)
    report.pop("freshness", None)
    report["summary"]["data_quality_warnings"] = []
    return report


def _f1_healthy_report() -> dict:
    """Fresh, verified inputs whose evaluated candidates all stayed below the gate."""
    report = _contract_valid_missing_ranking_report()
    report["final_decisions"]["horizon_rankings"] = {
        horizon: [{"symbol": "CANDIDATE", "action": "watch", "score": 0.1}]
        for horizon in ("long", "medium", "short")
    }
    return report


def _lead(page: str) -> str:
    return page.split('<p class="lead">', 1)[1].split("</p>", 1)[0]


def _empty_notice(page: str) -> str:
    match = re.search(r'<div class="notice n-(?:warn|info)" role="note" style="margin:0 20px 16px">.*?</div>', page)
    assert match is not None, "empty-conclusion notice missing"
    return match.group(0)


_F1_UNVERIFIED_CASES = {
    "incomplete": _f1_incomplete_report,
    "untrusted": _f1_untrusted_report,
    "stale": _f1_stale_report,
    "unknown": _f1_unknown_report,
}


def test_f1_unverified_zero_pick_lead_does_not_imply_signals_missed_gate() -> None:
    from quant_advisor_research.publisher import index_inputs_verified

    for name, build in _F1_UNVERIFIED_CASES.items():
        report = build()
        assert not index_inputs_verified(report), name
        lead = _lead(render_report_html(report))
        assert _HEALTHY_WAIT_ZH not in lead, name
        assert _HEALTHY_WAIT_EN not in lead, name
        assert "输入不完整" in lead and "不能解读为信号未达门槛" in lead, name
        assert "inputs are incomplete" in lead and "cannot be read as signals below the gate" in lead, name


def test_f1_unverified_zero_pick_report_shows_same_warning_as_index() -> None:
    for name, build in _F1_UNVERIFIED_CASES.items():
        report = build()
        before = deepcopy(report)
        report_page = render_report_html(report)
        index_page = render_index_html([report])
        notice = _empty_notice(report_page)
        assert 'class="notice n-warn"' in notice, name
        assert _INCOMPLETE_NOTICE_ZH in notice and _INCOMPLETE_NOTICE_EN in notice, name
        assert notice == _empty_notice(index_page), name
        # The warning belongs to the summary, ahead of the horizon columns.
        summary = report_page.split('id="summary"', 1)[1].split('id="conclusions"', 1)[0]
        assert notice in summary, name
        assert "空结果本身就是结论" not in report_page, name
        assert "候选未达到推荐门槛" not in report_page, name
        assert report_page.split('id="conclusions"', 1)[1].count("本期无推荐") == 3, name
        assert "仅供研究" in report_page and "RESEARCH ONLY" in report_page, name
        assert report == before, name


def test_f1_stale_momentum_is_not_described_as_unstable_ranking() -> None:
    lead = _lead(render_report_html(_f1_stale_report()))
    assert "本期暂无足够稳定的主题排序" not in lead
    assert "No stable theme ranking is available this period" not in lead
    assert "主题动量不可用" in lead
    assert "Theme momentum could not be used" in lead


def test_f1_healthy_zero_pick_control_keeps_below_gate_conclusion() -> None:
    from quant_advisor_research.publisher import index_inputs_verified

    report = _f1_healthy_report()
    assert index_inputs_verified(report)
    report_page = render_report_html(report)
    lead = _lead(report_page)
    assert _HEALTHY_WAIT_ZH in lead and _HEALTHY_WAIT_EN in lead
    assert "输入不完整" not in lead and "inputs are incomplete" not in lead
    notice = _empty_notice(report_page)
    assert 'class="notice n-info"' in notice
    assert "空结果本身就是结论" in notice
    assert _INCOMPLETE_NOTICE_ZH not in report_page
    assert notice == _empty_notice(render_index_html([report]))
    assert report_page.split('id="conclusions"', 1)[1].count("候选未达到推荐门槛") == 3


def test_f1_verified_inputs_missing_rankings_stay_unknown_on_report() -> None:
    report = _contract_valid_missing_ranking_report()
    report_page = render_report_html(report)
    lead = _lead(report_page)
    assert _HEALTHY_WAIT_ZH not in lead and _HEALTHY_WAIT_EN not in lead
    assert "尚不能判断信号是否达到门槛" in lead
    assert "whether signals met the gate remains unknown" in lead
    assert "输入不完整" not in lead
    notice = _empty_notice(report_page)
    assert "部分周期缺少排名证据" in notice
    assert notice == _empty_notice(render_index_html([report]))


def test_f1_report_with_picks_has_no_empty_conclusion_notice() -> None:
    report = build_sample_report()
    report["summary"]["data_quality_warnings"] = ["missing_market_confirmation"]
    page = render_report_html(report)
    assert 'style="margin:0 20px 16px"' not in page
    assert _INCOMPLETE_NOTICE_ZH not in page


def test_f1_expired_unverified_report_keeps_expiry_banner_and_warning() -> None:
    report = _f1_untrusted_report()
    report["expires_at"] = "2020-01-01T00:00:00Z"
    page = render_report_html(report)
    assert '<div class="notice n-warn" role="note" data-when-expired hidden>' in page
    assert "此报告已过期。" in page
    assert _INCOMPLETE_NOTICE_ZH in _empty_notice(page)


# --- F1-R1: shared completeness predicate must honour the page's own input checks ---

_VERIFIED_NOTICE_ZH = "空结果本身就是结论"
_VERIFIED_NOTICE_EN = "this is not missing data"
_VERIFIED_INPUTS_ZH = "输入已核验完整"
_VERIFIED_INPUTS_EN = "Inputs were verified complete"


def _r1_market_confirmation_missing_report() -> dict:
    """Reviewer R1: contract-valid zero-pick report, fresh AI/theme, market confirmation not provided.

    Mirrors ``build_advisory_report`` without a market-confirmation path: the
    check row is ``missing``/``not_provided`` and no data-quality warning is added.
    """
    report = _f1_healthy_report()
    for check in report["input_checks"]:
        if check["name"] == "market_confirmation":
            check.update(status="missing", detail="not_provided", as_of=None)
    validate_advisory_report(report)
    return report


def _assert_unverified_everywhere(report: dict, label: str) -> None:
    from quant_advisor_research.publisher import index_inputs_verified

    assert not index_inputs_verified(report), label
    report_page = render_report_html(report)
    index_page = render_index_html([report])
    lead = _lead(report_page)
    assert _HEALTHY_WAIT_ZH not in lead and _HEALTHY_WAIT_EN not in lead, label
    assert "输入不完整" in lead and "不能解读为信号未达门槛" in lead, label
    assert "inputs are incomplete" in lead and "cannot be read as signals below the gate" in lead, label
    notice = _empty_notice(report_page)
    assert 'class="notice n-warn"' in notice, label
    assert _INCOMPLETE_NOTICE_ZH in notice and _INCOMPLETE_NOTICE_EN in notice, label
    assert notice == _empty_notice(index_page), label
    for page in (report_page, index_page):
        assert _VERIFIED_NOTICE_ZH not in page and _VERIFIED_NOTICE_EN not in page, label
        assert _VERIFIED_INPUTS_ZH not in page and _VERIFIED_INPUTS_EN not in page, label
        assert "候选未达到推荐门槛" not in page, label
        assert "Candidates did not meet the" not in page, label
    conclusions = report_page.split('id="conclusions"', 1)[1]
    assert conclusions.count("本期无推荐") == 3, label
    assert index_page.count("本期无推荐") == 3, label


def test_r1_missing_market_confirmation_is_not_verified_complete() -> None:
    report = _r1_market_confirmation_missing_report()
    report_page = render_report_html(report)
    inputs = report_page.split('id="inputs"', 1)[1].split("</section>", 1)[0]
    assert "缺失" in inputs and "Missing" in inputs
    _assert_unverified_everywhere(report, "market_confirmation_missing")


def _with_check(name: str, **changes) -> dict:
    report = _f1_healthy_report()
    for check in report["input_checks"]:
        if check["name"] == name:
            check.update(changes)
    return report


def _r1_adverse_cases() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    names = [check["name"] for check in _all_input_checks_available()]
    for name in names:
        for status in ("missing", "invalid", "stale", "unknown"):
            cases[f"{name}:{status}"] = _with_check(name, status=status)
        partial = _f1_healthy_report()
        partial["input_checks"] = [c for c in partial["input_checks"] if c["name"] != name]
        cases[f"{name}:absent_row"] = partial
    unrecognised = _f1_healthy_report()
    unrecognised["input_checks"][0]["status"] = "unverified"
    cases["unrecognised_status"] = unrecognised
    no_status = _f1_healthy_report()
    del no_status["input_checks"][2]["status"]
    cases["status_not_recorded"] = no_status
    duplicate = _f1_healthy_report()
    duplicate["input_checks"].append(
        {"name": "market_confirmation", "detail": "not_provided", "status": "missing", "as_of": None}
    )
    cases["conflicting_duplicate_row"] = duplicate
    extra = _f1_healthy_report()
    extra["input_checks"].append({"name": "extra_input", "detail": "x", "status": "invalid", "as_of": None})
    cases["extra_row_invalid"] = extra
    empty = _f1_healthy_report()
    empty["input_checks"] = []
    cases["empty_list"] = empty
    absent = _f1_healthy_report()
    del absent["input_checks"]
    cases["input_checks_absent"] = absent
    not_list = _f1_healthy_report()
    not_list["input_checks"] = {"market_confirmation": "available"}
    cases["input_checks_not_list"] = not_list
    non_dict = _f1_healthy_report()
    non_dict["input_checks"][4] = "available"
    cases["non_dict_row"] = non_dict
    return cases


def test_r1_missing_invalid_stale_unknown_or_partial_checks_never_verified_complete() -> None:
    for label, report in _r1_adverse_cases().items():
        before = deepcopy(report)
        _assert_unverified_everywhere(report, label)
        assert report == before, label


def test_r1_available_checks_do_not_override_untrusted_or_stale_freshness() -> None:
    untrusted = _f1_healthy_report()
    untrusted["freshness"]["ai_signal"] = {"present": True, "valid": False, "reason": "provenance_untrusted"}
    stale = _f1_healthy_report()
    stale["freshness"]["theme_momentum"] = {"present": True, "valid": False, "reason": "stale_as_of"}
    warned = _f1_healthy_report()
    warned["summary"]["data_quality_warnings"] = ["ai_signal_provenance_untrusted"]
    no_freshness = _f1_healthy_report()
    del no_freshness["freshness"]
    for label, report in {
        "untrusted": untrusted, "stale": stale, "warning": warned, "no_freshness": no_freshness,
    }.items():
        assert all(c["status"] == "available" for c in report["input_checks"]), label
        _assert_unverified_everywhere(report, label)


def test_r1_fully_healthy_zero_pick_keeps_below_gate_conclusion_everywhere() -> None:
    from quant_advisor_research.publisher import index_inputs_verified

    report = _f1_healthy_report()
    assert all(c["status"] == "available" for c in report["input_checks"])
    assert index_inputs_verified(report)
    report_page = render_report_html(report)
    index_page = render_index_html([report])
    lead = _lead(report_page)
    assert _HEALTHY_WAIT_ZH in lead and _HEALTHY_WAIT_EN in lead
    notice = _empty_notice(report_page)
    assert 'class="notice n-info"' in notice
    assert _VERIFIED_NOTICE_ZH in notice and _VERIFIED_NOTICE_EN in notice
    assert notice == _empty_notice(index_page)
    assert report_page.split('id="conclusions"', 1)[1].count("候选未达到推荐门槛") == 3
    assert index_page.count("候选未达到推荐门槛。") == 3
    for page in (report_page, index_page):
        assert _INCOMPLETE_NOTICE_ZH not in page and _INCOMPLETE_NOTICE_EN not in page


def test_r1_genuine_picks_are_unaffected_by_missing_checks() -> None:
    report = build_sample_report()
    assert any(c["status"] != "available" for c in report["input_checks"])
    page = render_report_html(report)
    assert 'style="margin:0 20px 16px"' not in page
    assert _INCOMPLETE_NOTICE_ZH not in page


def test_archive_symbols_follow_published_picks_not_stale_summary() -> None:
    # A contract-valid zero-pick report whose summary still lists earlier symbols
    # must not be advertised in the archive as having recommended them.
    report = _zero_pick_report(verified=False)
    assert report["summary"]["top_recommended_symbols"]
    validate_advisory_report(report)
    archive = render_archive_html([report])
    card = archive.split('class="archive-card"', 1)[1]
    symbols_cell = card.split('data-h="推荐标的"', 1)[1].split("</td>", 1)[0]
    assert 'class="sym"' not in symbols_cell
    assert "本期无推荐" in symbols_cell
    assert "No recommendation" in symbols_cell

    published = build_sample_report()
    expected = [pick["symbol"] for pick in published["final_decisions"]["recommendations"][:5]]
    assert expected
    published["summary"]["top_recommended_symbols"] = ["STALEONLY"]
    card = render_archive_html([published]).split('class="archive-card"', 1)[1]
    symbols_cell = card.split('data-h="推荐标的"', 1)[1].split("</td>", 1)[0]
    assert "STALEONLY" not in symbols_cell
    for symbol in expected:
        assert f'<span class="sym">{symbol}</span>' in symbols_cell

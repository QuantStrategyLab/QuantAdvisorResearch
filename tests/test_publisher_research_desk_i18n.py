from __future__ import annotations

import re

from test_publisher_research_desk import NOW, make_pick, make_report

from quant_advisor_research import publisher
from quant_advisor_research.publisher import (
    render_archive_html,
    render_index_html,
    render_report_html,
)


def _pages() -> dict[str, str]:
    report = make_report()
    return {
        "index": render_index_html([report], now=NOW),
        "report": render_report_html(report),
        "archive": render_archive_html([report]),
    }


def test_html_root_defaults_to_zh_cn_with_both_titles() -> None:
    pages = _pages()
    for name, page in pages.items():
        match = re.search(
            r'<html lang="zh-CN" data-locale="zh-CN" data-theme="auto" '
            r'data-title-zh="([^"]+)" data-title-en="([^"]+)">',
            page,
        )
        assert match, name
        title_zh, title_en = match.groups()
        assert title_zh and title_en and title_zh != title_en, name
        assert f"<title>{title_zh}</title>" in page, name


def test_every_ui_string_pair_has_zh_and_en() -> None:
    pair = re.compile(
        r'<span data-l="zh" lang="zh-CN">[^<]*</span>'
        r'<span data-l="en" lang="en">[^<]*</span>'
    )
    for name, page in _pages().items():
        zh_count = page.count('<span data-l="zh" lang="zh-CN">')
        assert zh_count > 0, name
        assert len(pair.findall(page)) == zh_count, name


def test_producer_text_keeps_zh_lang_and_source_language_tag() -> None:
    report = make_report(picks=[make_pick("PROD1")])
    html = render_report_html(report)

    assert '<p class="pick-name" lang="zh-CN">PROD1 Systems</p>' in html
    for summary in ("PROD1 业务背景（合成）", "PROD1 推荐理由（合成）", "PROD1 主要风险（合成）"):
        assert f'<span lang="zh-CN" style="display:block">{summary}</span>' in html
    assert html.count(
        '<span class="srclang" data-l="en" lang="en">Source text in Chinese</span>'
    ) == 3


def test_theme_and_locale_controls_are_buttons_with_aria_pressed_and_hidden_without_js() -> None:
    html = render_report_html(make_report())

    assert '<div class="controls" hidden>' in html
    assert html.count('data-set-locale="') == 2
    assert html.count('data-set-theme="') == 3
    controls = re.findall(r"<button[^>]*data-set-(?:locale|theme)[^>]*>", html)
    assert len(controls) == 5
    assert all(tag.startswith('<button type="button"') for tag in controls)
    assert html.count('role="group"') == 2
    assert 'data-aria-zh="语言" data-aria-en="Language"' in html
    assert 'data-aria-zh="显示主题" data-aria-en="Colour theme"' in html
    assert 'setAttribute("aria-pressed"' in html
    assert not re.search(r"<a[^>]*data-set-(?:locale|theme)", html)


def test_no_mockup_url_overrides_in_production_script() -> None:
    script = publisher.SITE_SCRIPT_JS
    assert "URLSearchParams" not in script
    assert "searchParams" not in script
    assert "?lang=" not in script
    assert "?theme=" not in script
    assert "?now=" not in script
    assert "localStorage" in script
    assert "Date.now()" in script

    for name, page in _pages().items():
        assert "URLSearchParams" not in page, name
        assert "?lang=" not in page, name
        assert "?theme=" not in page, name
        assert "?now=" not in page, name


def test_mobile_table_labels_have_english_variants() -> None:
    for name, page in _pages().items():
        tags = re.findall(r'<(?:td|th)\b[^>]*\bdata-h="[^"]*"[^>]*>', page)
        assert tags, name
        assert all('data-h-en="' in tag for tag in tags), name

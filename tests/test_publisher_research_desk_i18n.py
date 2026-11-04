from __future__ import annotations

import re

from test_publisher import build_sample_report

from quant_advisor_research.publisher import (
    render_archive_html,
    render_index_html,
    render_report_html,
)


def _pages() -> list[str]:
    report = build_sample_report()
    return [
        render_index_html([report]),
        render_report_html(report),
        render_archive_html([report]),
    ]


def test_html_root_defaults_to_zh_cn_with_both_titles() -> None:
    for page in _pages():
        assert 'lang="zh-CN" data-locale="zh-CN" data-theme="auto"' in page
        assert 'data-title-zh="' in page
        assert 'data-title-en="' in page


def test_every_ui_string_pair_has_zh_and_en() -> None:
    pair_pattern = re.compile(
        r'<span data-l="zh" lang="zh-CN">[^<]*</span>'
        r'<span data-l="en" lang="en">[^<]*</span>'
    )
    for page in _pages():
        # Count real spans only: the inlined CSS also contains the selector [data-l="zh"].
        zh_count = page.count('<span data-l="zh"')
        assert zh_count > 0
        assert len(pair_pattern.findall(page)) == zh_count


def test_producer_text_keeps_zh_lang_and_source_language_tag() -> None:
    page = render_report_html(build_sample_report())
    assert 'class="srclang" data-l="en" lang="en">Source text in Chinese' in page
    assert 'lang="zh-CN" style="display:block"' in page


def test_theme_and_locale_controls_are_buttons_with_aria_pressed_and_hidden_without_js() -> None:
    page = render_index_html([build_sample_report()])
    assert '<div class="controls" hidden>' in page
    assert 'type="button"' in page
    assert 'data-set-locale="zh-CN"' in page
    assert 'data-set-locale="en"' in page
    assert 'data-set-theme="auto"' in page
    assert 'data-set-theme="light"' in page
    assert 'data-set-theme="dark"' in page
    assert 'aria-pressed="false"' in page
    assert 'role="group"' in page


def test_no_mockup_url_overrides_in_production_script() -> None:
    page = render_index_html([build_sample_report()])
    assert "URLSearchParams" not in page
    assert "?now=" not in page
    assert "?lang=" not in page
    assert "?theme=" not in page
    assert "qar.locale" in page
    assert "qar.theme" in page
    assert "Date.now()" in page

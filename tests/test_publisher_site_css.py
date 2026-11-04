"""Stylesheet invariants of the published site: cascade order, badge wrapping and AA contrast.

These check the emitted <style> block rather than the Python constants, because what the
browser applies is the order of the concatenation, not the order in the source file.
"""
from __future__ import annotations

import re

from test_publisher import build_sample_report

from quant_advisor_research.publisher import render_archive_html, render_index_html, render_report_html

AA_SMALL_TEXT_RATIO = 4.5


def _legacy_report() -> dict:
    report = build_sample_report()
    report.update(schema_version="5", contract_version="model_recommendations.v5")
    for key in ("reference_time", "expires_at", "freshness", "input_digest"):
        report.pop(key, None)
    return report


def _style(page: str) -> str:
    match = re.search(r"<style>(.*)</style>", page, re.DOTALL)
    assert match is not None, "page emits no inline stylesheet"
    return match.group(1)


def _css_block(style: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n    \}", style, re.DOTALL)
    assert match is not None, f"missing CSS block for {selector}"
    return match.group(1)


def _token(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{3,6}})\s*;", block)
    assert match is not None, f"missing token {name}"
    return match.group(1)


def _channel(value: int) -> float:
    scaled = value / 255
    return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4


def _luminance(hex_value: str) -> float:
    digits = hex_value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    red, green, blue = (int(digits[offset : offset + 2], 16) for offset in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def test_media_overrides_are_emitted_after_the_page_rules_they_must_win() -> None:
    report = build_sample_report()
    index = _style(render_index_html([report]))
    page = _style(render_report_html(report))

    narrow = index.index("@media (max-width: 960px)")
    assert index.index(".home-grid {") < narrow
    assert page.index(".report-grid {") < page.index("@media (max-width: 960px)")
    assert page.index(".toc {") < page.index("@media (max-width: 960px)")
    assert page.index(".cols {") < page.index("@media (max-width: 640px)")


def test_narrow_viewports_collapse_every_multi_column_grid() -> None:
    style = _style(render_report_html(build_sample_report()))
    wide_block = _css_block(style, "@media (max-width: 960px)")
    phone_block = _css_block(style, "@media (max-width: 640px)")

    assert ".home-grid, .report-grid { grid-template-columns: minmax(0, 1fr); }" in wide_block
    assert ".toc { position: static; }" in wide_block
    assert ".cols { grid-template-columns: minmax(0, 1fr); }" in phone_block


def test_light_and_dark_muted_ink_meets_aa_contrast_on_every_surface() -> None:
    style = _style(render_index_html([build_sample_report()]))
    for selector in (":root", 'html[data-theme="dark"]'):
        block = _css_block(style, selector)
        ink_3 = _token(block, "--ink-3")
        for surface in ("--canvas", "--surface", "--surface-2"):
            ratio = _contrast(ink_3, _token(block, surface))
            assert ratio >= AA_SMALL_TEXT_RATIO, f"{selector} {surface}: {ratio:.3f} < 4.5 with {ink_3}"


def test_facts_status_badge_wraps_inside_its_cell_instead_of_clipping() -> None:
    style = _style(render_index_html([_legacy_report()]))
    facts_badge = re.search(r"\.facts \.badge\s*\{([^}]*)\}", style)
    assert facts_badge is not None, "the facts badge has no wrapping override"
    assert "white-space: normal" in facts_badge.group(1)
    # Two lines at 12px must stay readable without growing the single-line badge.
    assert "line-height: 1.3" in facts_badge.group(1)
    assert "min-height: 24px" in facts_badge.group(1)

    base_badge = re.search(r"\n\s*\.badge\s*\{([^}]*)\}", style)
    assert base_badge is not None
    assert "white-space: nowrap" in base_badge.group(1)

    glyph = re.search(r"\.badge::before\s*\{([^}]*)\}", style)
    assert glyph is not None
    assert "flex: none" in glyph.group(1)
    assert "width: 7px" in glyph.group(1) and "height: 7px" in glyph.group(1)


def test_archive_horizon_muting_targets_label_spans_only_never_nested_symbols() -> None:
    style = _style(render_archive_html([build_sample_report(), _legacy_report()]))
    assert ".hz-mini > span:nth-child(odd)" in style
    assert ".hz-mini span:nth-child(odd)" not in style

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

    assert "Policy boundary" in html
    assert "execution" in html
    assert "EVT1" in html
    assert "2-12周" in html
    assert "Source mode: fixture" in html


def test_render_feed_xml_contains_report_item() -> None:
    feed = render_feed_xml([build_sample_report()], site_url="https://example.com/advisor", feed_title="Test Feed")

    assert "<rss version=\"2.0\">" in feed
    assert "2026-05-30 Weekly Model Recommendations" in feed
    assert "source=fixture" in feed
    assert "Non-personalized model output; no execution, allocation, or account-specific advice." in feed


def test_publish_reports_writes_site_files(tmp_path: Path) -> None:
    report = build_sample_report()
    report_path = tmp_path / "report.json"
    write_json(report_path, report)

    written = publish_reports([report_path], tmp_path / "site", site_url="https://example.com/advisor", feed_title="Test")

    filenames = {path.name for path in written}
    assert "index.html" in filenames
    assert "feed.xml" in filenames
    assert "2026-05-30-weekly-model-recommendations.html" in filenames

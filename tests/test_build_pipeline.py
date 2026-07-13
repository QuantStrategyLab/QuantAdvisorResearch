from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from quant_advisor_research.archive_backfill import backfill_site_archive, discover_report_paths
from quant_advisor_research.build_pipeline import build_advisory_artifacts, default_weekly_as_of
from quant_advisor_research.cross_repo_smoke import run_cross_repo_smoke


ROOT = Path(__file__).resolve().parents[1]


def example_path(name: str) -> Path:
    return ROOT / "examples" / name


def build_fixture_report(tmp_path: Path, as_of: dt.date) -> Path:
    ai_signal = json.loads(example_path("research_signal_context.example.json").read_text(encoding="utf-8"))
    ai_signal["as_of"] = as_of.isoformat()
    ai_signal["generated_at"] = f"{as_of.isoformat()}T00:00:00Z"
    ai_signal["expires_at"] = (as_of + dt.timedelta(days=7)).isoformat()
    ai_signal_path = tmp_path / "ai_signal.json"
    ai_signal_path.parent.mkdir(parents=True, exist_ok=True)
    ai_signal_path.write_text(json.dumps(ai_signal), encoding="utf-8")
    theme_momentum = json.loads(example_path("theme_momentum_snapshot.example.json").read_text(encoding="utf-8"))
    theme_momentum["as_of"] = as_of.isoformat()
    theme_momentum["generated_at"] = f"{as_of.isoformat()}T00:00:00Z"
    theme_momentum_path = tmp_path / "theme_momentum.json"
    theme_momentum_path.write_text(json.dumps(theme_momentum), encoding="utf-8")
    result = build_advisory_artifacts(
        as_of=as_of,
        cadence="weekly",
        political_events_path=example_path("political_events.example.csv"),
        political_watchlist_path=example_path("political_watchlist.example.csv"),
        ai_signal_path=ai_signal_path,
        theme_momentum_path=theme_momentum_path,
        market_confirmation_path=None,
        output_dir=tmp_path / as_of.isoformat(),
        max_candidates=12,
        market_benchmark="SPY",
        market_max_symbols=80,
        market_request_pause_seconds=0,
        market_proxy_list=None,
        market_proxy_urls="",
        market_proxy_pool_url="",
        market_use_network=False,
        market_cache_dir=None,
        market_cache_max_age_days=14,
    )
    return result.report_json


def test_default_weekly_as_of_uses_most_recent_saturday() -> None:
    assert default_weekly_as_of(dt.date(2026, 6, 20)) == dt.date(2026, 6, 20)
    assert default_weekly_as_of(dt.date(2026, 6, 21)) == dt.date(2026, 6, 20)
    assert default_weekly_as_of(dt.date(2026, 6, 24)) == dt.date(2026, 6, 20)


def test_build_advisory_artifacts_builds_market_report_and_site(tmp_path: Path) -> None:
    result = build_advisory_artifacts(
        as_of=dt.date(2026, 5, 31),
        cadence="weekly",
        political_events_path=example_path("political_events.example.csv"),
        political_watchlist_path=example_path("political_watchlist.example.csv"),
        ai_signal_path=example_path("research_signal_context.example.json"),
        theme_momentum_path=example_path("theme_momentum_snapshot.example.json"),
        market_confirmation_path=None,
        output_dir=tmp_path / "artifacts",
        max_candidates=12,
        market_benchmark="SPY",
        market_max_symbols=80,
        market_request_pause_seconds=0,
        market_proxy_list=None,
        market_proxy_urls="",
        market_proxy_pool_url="",
        market_use_network=False,
        market_cache_dir=tmp_path / "market-cache",
        market_cache_max_age_days=14,
        recommendation_review=True,
        site_output_dir=tmp_path / "site",
        site_url="https://example.invalid/advisor",
        feed_title="智慧投顾研究系统",
    )

    assert result.report_json.exists()
    assert result.report_md.exists()
    assert result.report_manifest.exists()
    assert result.market_confirmation is not None
    assert result.market_confirmation.exists()
    assert result.recommendation_review_json is not None
    assert result.recommendation_review_json.exists()
    assert result.recommendation_review_md is not None
    assert result.recommendation_review_md.exists()
    assert "confirmation_quality" in result.market_confirmation.read_text(encoding="utf-8")
    assert (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / result.report_json.name).exists()
    assert (tmp_path / "site" / result.recommendation_review_json.name).exists()

    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert report["summary"]["top_recommended_symbols"]


def test_missing_optional_theme_momentum_does_not_block_build(tmp_path: Path) -> None:
    result = build_advisory_artifacts(
        as_of=dt.date(2026, 5, 30),
        cadence="weekly",
        political_events_path=example_path("political_events.example.csv"),
        political_watchlist_path=example_path("political_watchlist.example.csv"),
        ai_signal_path=example_path("research_signal_context.example.json"),
        theme_momentum_path=tmp_path / "missing-theme.json",
        market_confirmation_path=example_path("market_confirmation.example.csv"),
        output_dir=tmp_path / "artifacts",
        max_candidates=12,
        market_benchmark="SPY",
        market_max_symbols=80,
        market_request_pause_seconds=0,
        market_proxy_list=None,
        market_proxy_urls="",
        market_proxy_pool_url="",
        market_use_network=False,
        market_cache_dir=None,
        market_cache_max_age_days=14,
    )

    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert report["summary"]["theme_momentum_available"] is False


def test_archive_backfill_discovers_dedupes_and_publishes_reports(tmp_path: Path) -> None:
    first = build_fixture_report(tmp_path / "artifacts-a", dt.date(2026, 5, 31))
    duplicate = build_fixture_report(tmp_path / "artifacts-b", dt.date(2026, 5, 31))
    second = build_fixture_report(tmp_path / "artifacts-c", dt.date(2026, 5, 24))

    reports = discover_report_paths([tmp_path], [duplicate])

    assert reports == [duplicate, second]
    written = backfill_site_archive(
        report_paths=reports,
        output_dir=tmp_path / "site",
        site_url="https://example.invalid/advisor",
        feed_title="智慧投顾研究系统",
    )
    assert written
    assert (tmp_path / "site" / "archive.html").exists()
    assert (tmp_path / "site" / duplicate.name).exists()
    assert (tmp_path / "site" / second.name).exists()
    assert first.name == duplicate.name


def test_cross_repo_smoke_uses_fixture_artifacts_without_network(tmp_path: Path) -> None:
    summary = run_cross_repo_smoke(
        as_of="2026-05-31",
        political_events=example_path("political_events.example.csv"),
        political_watchlist=example_path("political_watchlist.example.csv"),
        ai_signal=example_path("research_signal_context.example.json"),
        theme_momentum=example_path("theme_momentum_snapshot.example.json"),
        work_dir=tmp_path / "smoke",
        site_url="https://example.invalid/advisor",
    )

    assert summary["recommendation_count"] >= 1
    assert (tmp_path / "smoke" / "site" / "index.html").exists()

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from .build_pipeline import DEFAULT_FEED_TITLE, DEFAULT_SITE_URL, build_advisory_artifacts, parse_date


REQUIRED_HORIZONS = ("long", "medium", "short")


def assert_report_shape(report: dict[str, Any]) -> None:
    decisions = report.get("final_decisions")
    if not isinstance(decisions, dict):
        raise RuntimeError("report_missing_final_decisions")
    recommendations = decisions.get("recommendations")
    if not isinstance(recommendations, list):
        raise RuntimeError("report_missing_recommendations")
    buckets = decisions.get("horizon_buckets")
    if not isinstance(buckets, dict):
        raise RuntimeError("report_missing_horizon_buckets")
    for horizon in REQUIRED_HORIZONS:
        if horizon not in buckets:
            raise RuntimeError(f"report_missing_horizon_bucket:{horizon}")


def assert_site_shape(site_dir: Path, report_json: Path) -> None:
    expected = ["index.html", "archive.html", "feed.xml", "reports_index.json", report_json.name]
    missing = [name for name in expected if not (site_dir / name).exists()]
    if missing:
        raise RuntimeError(f"site_missing_files:{','.join(missing)}")
    index_html = (site_dir / "index.html").read_text(encoding="utf-8")
    report_pages = sorted(site_dir.glob("*-model-recommendations.html"))
    if not report_pages:
        raise RuntimeError("site_missing_report_html")
    report_html = report_pages[0].read_text(encoding="utf-8")
    for label in ("长线", "中线", "短线"):
        if label not in index_html or label not in report_html:
            raise RuntimeError(f"site_missing_horizon_label:{label}")


def run_cross_repo_smoke(
    *,
    as_of: str,
    political_events: str | Path,
    political_watchlist: str | Path,
    ai_signal: str | Path,
    theme_momentum: str | Path | None,
    work_dir: str | Path | None,
    site_url: str,
) -> dict[str, Any]:
    cleanup_tmp = None
    if work_dir:
        root = Path(work_dir)
        root.mkdir(parents=True, exist_ok=True)
    else:
        cleanup_tmp = tempfile.TemporaryDirectory(prefix="qar-cross-repo-smoke-")
        root = Path(cleanup_tmp.name)
    output_dir = root / "artifacts"
    site_dir = root / "site"
    result = build_advisory_artifacts(
        as_of=parse_date(as_of),
        cadence="weekly",
        political_events_path=political_events,
        political_watchlist_path=political_watchlist,
        ai_signal_path=ai_signal,
        theme_momentum_path=theme_momentum,
        market_confirmation_path=None,
        output_dir=output_dir,
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
        site_output_dir=site_dir,
        site_url=site_url,
        feed_title=DEFAULT_FEED_TITLE,
        recover_site_archive=False,
    )
    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert_report_shape(report)
    assert_site_shape(site_dir, result.report_json)
    summary = {
        "as_of": result.as_of.isoformat(),
        "report": str(result.report_json),
        "site": str(site_dir),
        "recommendation_count": len(report.get("final_decisions", {}).get("recommendations", [])),
        "top_recommended_symbols": report.get("summary", {}).get("top_recommended_symbols", []),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if cleanup_tmp:
        cleanup_tmp.cleanup()
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a deterministic cross-repository smoke test for advisory publishing.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--political-events", required=True)
    parser.add_argument("--political-watchlist", required=True)
    parser.add_argument("--ai-signal", required=True)
    parser.add_argument("--theme-momentum")
    parser.add_argument("--work-dir", help="Optional directory to keep smoke artifacts.")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    run_cross_repo_smoke(
        as_of=args.as_of,
        political_events=args.political_events,
        political_watchlist=args.political_watchlist,
        ai_signal=args.ai_signal,
        theme_momentum=args.theme_momentum,
        work_dir=args.work_dir,
        site_url=args.site_url,
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from .advisory_report import build_advisory_report, render_markdown, write_json, write_text
from .artifacts import write_report_manifest
from .market_confirmation import (
    build_market_confirmation_rows,
    collect_symbols,
    load_proxy_urls,
    load_theme_momentum,
    write_market_confirmation_csv,
)
from .monthly_review import build_monthly_review, render_monthly_review_markdown
from .publisher import publish_reports, unique_report_paths_by_content
from .recommendation_review import build_recommendation_review, render_recommendation_review_markdown


DEFAULT_SITE_URL = "https://quantstrategylab.github.io/QuantAdvisorResearch"
DEFAULT_FEED_TITLE = "智慧投顾研究系统"
REPORT_JSON_PATTERN = re.compile(r"advisory_report_\d{4}-\d{2}-\d{2}\.json")


@dataclass(frozen=True)
class BuildPipelineResult:
    as_of: dt.date
    output_dir: Path
    report_json: Path
    report_md: Path
    report_manifest: Path
    market_confirmation: Path | None
    monthly_review_json: Path | None = None
    monthly_review_md: Path | None = None
    recommendation_review_json: Path | None = None
    recommendation_review_md: Path | None = None
    site_output_dir: Path | None = None
    recovered_report_count: int = 0


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def default_weekly_as_of(today: dt.date | None = None) -> dt.date:
    current = today or dt.datetime.now(dt.UTC).date()
    days_since_saturday = (current.weekday() - 5) % 7
    return current - dt.timedelta(days=days_since_saturday)


def existing_optional_path(value: str | Path | None) -> Path | None:
    if value in {None, ""}:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def required_path(value: str | Path, *, label: str) -> Path:
    path = Path(str(value))
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def write_github_output(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def copy_if_different(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and source.resolve() == destination.resolve():
        return
    shutil.copyfile(source, destination)


def build_market_confirmation_artifact(
    *,
    as_of: dt.date,
    political_watchlist_path: str | Path | None,
    ai_signal_path: str | Path | None,
    theme_momentum_path: str | Path | None,
    output_path: Path,
    benchmark: str,
    max_symbols: int,
    request_pause_seconds: float,
    proxy_list: str | Path | None,
    proxy_urls_text: str,
    proxy_pool_url: str,
    use_network: bool,
    cache_dir: str | Path | None,
    cache_max_age_days: int,
) -> Path:
    theme_momentum = load_theme_momentum(theme_momentum_path) if theme_momentum_path else None
    symbols = collect_symbols(
        political_watchlist_path=political_watchlist_path,
        ai_signal_path=ai_signal_path,
        theme_momentum=theme_momentum,
        max_symbols=max_symbols,
    )
    proxy_urls = load_proxy_urls(
        proxy_list_path=proxy_list,
        proxy_urls_text=proxy_urls_text,
        proxy_pool_url=proxy_pool_url,
    )
    if proxy_urls:
        print(f"market_data_notice: proxy_pool_loaded count={len(proxy_urls)}")
    rows = build_market_confirmation_rows(
        symbols=symbols,
        as_of=as_of,
        benchmark=benchmark,
        theme_momentum=theme_momentum,
        use_network=use_network,
        request_pause_seconds=request_pause_seconds,
        proxy_urls=proxy_urls,
        cache_dir=cache_dir,
        cache_max_age_days=cache_max_age_days,
    )
    write_market_confirmation_csv(output_path, rows)
    print(f"market_confirmation_rows={len(rows)} symbols_requested={len(symbols)} output={output_path}")
    return output_path


def recover_published_reports(
    *,
    site_url: str,
    history_dir: Path,
    current_as_of: dt.date,
    timeout: int = 20,
) -> list[Path]:
    history_dir.mkdir(parents=True, exist_ok=True)
    index_url = f"{site_url.rstrip('/')}/reports_index.json"
    try:
        with urlopen(index_url, timeout=timeout) as response:  # noqa: S310 - public GitHub Pages archive URL.
            index = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - best-effort archive recovery.
        print(f"archive_recovery_notice: unavailable reason={type(exc).__name__}")
        return []

    paths: list[Path] = []
    seen_as_of = {current_as_of.isoformat()}
    for item in index.get("reports", []):
        if not isinstance(item, dict):
            continue
        as_of = str(item.get("as_of", "")).strip()
        json_name = Path(str(item.get("json", ""))).name
        if not as_of or as_of in seen_as_of or not REPORT_JSON_PATTERN.fullmatch(json_name):
            continue
        seen_as_of.add(as_of)
        url = f"{site_url.rstrip('/')}/{quote(json_name)}"
        destination = history_dir / json_name
        try:
            with urlopen(url, timeout=timeout) as response:  # noqa: S310 - public GitHub Pages report JSON URL.
                destination.write_bytes(response.read())
            payload = json.loads(destination.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - best-effort archive recovery.
            print(f"archive_recovery_notice: skipped={json_name} reason={type(exc).__name__}")
            continue
        if str(payload.get("as_of", "")) != as_of:
            print(f"archive_recovery_notice: skipped={json_name} reason=as_of_mismatch")
            continue
        paths.append(destination)
    print(f"archive_recovery_count={len(paths)}")
    return paths


def build_advisory_artifacts(
    *,
    as_of: dt.date,
    cadence: str,
    political_events_path: str | Path,
    political_watchlist_path: str | Path,
    ai_signal_path: str | Path | None,
    theme_momentum_path: str | Path | None,
    market_confirmation_path: str | Path | None,
    output_dir: str | Path,
    max_candidates: int,
    market_benchmark: str,
    market_max_symbols: int,
    market_request_pause_seconds: float,
    market_proxy_list: str | Path | None,
    market_proxy_urls: str,
    market_proxy_pool_url: str,
    market_use_network: bool,
    market_cache_dir: str | Path | None,
    market_cache_max_age_days: int,
    monthly_review: bool = False,
    previous_report_path: str | Path | None = None,
    recommendation_review: bool = False,
    site_output_dir: str | Path | None = None,
    site_url: str = DEFAULT_SITE_URL,
    feed_title: str = DEFAULT_FEED_TITLE,
    recover_site_archive: bool = False,
    upstream_repo_shas: dict[str, str] | None = None,
    market_compatibility_mode: bool = False,
) -> BuildPipelineResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    resolved_theme_momentum = existing_optional_path(theme_momentum_path)
    resolved_ai_signal = required_path(ai_signal_path, label="ai signal") if ai_signal_path else None

    market_path = existing_optional_path(market_confirmation_path)
    if market_path is None:
        generated_market_path = output / f"market_confirmation_{as_of.isoformat()}.csv"
        market_path = build_market_confirmation_artifact(
            as_of=as_of,
            political_watchlist_path=political_watchlist_path,
            ai_signal_path=resolved_ai_signal,
            theme_momentum_path=resolved_theme_momentum,
            output_path=generated_market_path,
            benchmark=market_benchmark,
            max_symbols=market_max_symbols,
            request_pause_seconds=market_request_pause_seconds,
            proxy_list=market_proxy_list,
            proxy_urls_text=market_proxy_urls,
            proxy_pool_url=market_proxy_pool_url,
            use_network=market_use_network,
            cache_dir=market_cache_dir,
            cache_max_age_days=market_cache_max_age_days,
        )

    report_json = output / f"advisory_report_{as_of.isoformat()}.json"
    report_md = output / f"advisory_report_{as_of.isoformat()}.md"
    report_manifest = Path(f"{report_json}.manifest.json")
    report = build_advisory_report(
        as_of=as_of.isoformat(),
        cadence=cadence,
        political_events_path=political_events_path,
        political_watchlist_path=political_watchlist_path,
        ai_signal_path=resolved_ai_signal,
        theme_momentum_path=resolved_theme_momentum,
        market_confirmation_path=market_path,
        max_candidates=max_candidates,
        market_compatibility_mode=market_compatibility_mode,
    )
    write_json(report_json, report)
    write_text(report_md, render_markdown(report))
    write_report_manifest(
        report=report,
        report_path=report_json,
        markdown_path=report_md,
        manifest_path=report_manifest,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        git_sha=os.environ.get("GITHUB_SHA"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        upstream_repo_shas=upstream_repo_shas,
        input_paths={
            "political_events": political_events_path,
            "political_watchlist": political_watchlist_path,
            "ai_signal": resolved_ai_signal,
            "theme_momentum": resolved_theme_momentum,
            "market_confirmation": market_path,
        },
    )

    monthly_review_json: Path | None = None
    monthly_review_md: Path | None = None
    if monthly_review:
        previous = None
        resolved_previous = existing_optional_path(previous_report_path)
        if resolved_previous:
            previous = json.loads(resolved_previous.read_text(encoding="utf-8"))
        review = build_monthly_review(
            current_report=report,
            previous_report=previous,
            current_report_path=report_json,
            previous_report_path=resolved_previous or "",
        )
        monthly_review_json = output / f"monthly_review_{as_of.isoformat()}.json"
        monthly_review_md = output / f"monthly_review_{as_of.isoformat()}.md"
        write_json(monthly_review_json, review)
        write_text(monthly_review_md, render_monthly_review_markdown(review))

    recovered_report_paths: list[Path] = []
    site_output: Path | None = Path(site_output_dir) if site_output_dir else None
    if site_output:
        if recover_site_archive:
            recovered_report_paths = recover_published_reports(
                site_url=site_url,
                history_dir=output / "history",
                current_as_of=as_of,
            )
        report_paths = [report_json, *recovered_report_paths]
    else:
        report_paths = [report_json]
    report_paths = unique_report_paths_by_content(report_paths)

    recommendation_review_json: Path | None = None
    recommendation_review_md: Path | None = None
    if recommendation_review:
        review = build_recommendation_review(
            report_paths=report_paths,
            as_of=as_of,
            benchmark=market_benchmark,
            cache_dir=market_cache_dir,
            cache_max_age_days=market_cache_max_age_days,
            use_network=False,
        )
        recommendation_review_json = output / f"recommendation_review_{as_of.isoformat()}.json"
        recommendation_review_md = output / f"recommendation_review_{as_of.isoformat()}.md"
        write_json(recommendation_review_json, review)
        write_text(recommendation_review_md, render_recommendation_review_markdown(review))

    if site_output:
        publish_reports(report_paths, site_output, site_url=site_url, feed_title=feed_title)
        for path in report_paths:
            copy_if_different(Path(path), site_output / Path(path).name)
        copy_if_different(report_md, site_output / report_md.name)
        copy_if_different(report_manifest, site_output / report_manifest.name)
        if recommendation_review_json and recommendation_review_md:
            copy_if_different(recommendation_review_json, site_output / recommendation_review_json.name)
            copy_if_different(recommendation_review_md, site_output / recommendation_review_md.name)

    write_github_output({"as_of": as_of.isoformat(), "report_path": str(report_json)})
    return BuildPipelineResult(
        as_of=as_of,
        output_dir=output,
        report_json=report_json,
        report_md=report_md,
        report_manifest=report_manifest,
        market_confirmation=market_path,
        monthly_review_json=monthly_review_json,
        monthly_review_md=monthly_review_md,
        recommendation_review_json=recommendation_review_json,
        recommendation_review_md=recommendation_review_md,
        site_output_dir=site_output,
        recovered_report_count=len(recovered_report_paths),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build advisory report, market confirmation, optional review, and optional site.")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--cadence", required=True, choices=("daily", "weekly", "monthly"))
    parser.add_argument("--political-events", required=True, help="Political event CSV.")
    parser.add_argument("--political-watchlist", required=True, help="Political watchlist CSV.")
    parser.add_argument("--ai-signal", help="Research signal context JSON.")
    parser.add_argument("--theme-momentum", help="Theme momentum snapshot JSON. Missing files are skipped.")
    parser.add_argument("--market-confirmation", help="Optional prebuilt market confirmation CSV.")
    parser.add_argument("--market-compatibility-mode", action="store_true", help="Explicit historical/replay mode for legacy market CSVs.")
    parser.add_argument("--output-dir", required=True, help="Output artifact directory.")
    parser.add_argument("--max-items", "--max-candidates", dest="max_candidates", type=int, default=12)
    parser.add_argument("--market-benchmark", default="SPY")
    parser.add_argument("--market-max-symbols", type=int, default=80)
    parser.add_argument("--market-request-pause-seconds", type=float, default=0.2)
    parser.add_argument("--market-proxy-list")
    parser.add_argument("--market-proxy-urls", default="")
    parser.add_argument("--market-proxy-pool-url", default="")
    parser.add_argument("--market-cache-dir")
    parser.add_argument("--market-cache-max-age-days", type=int, default=14)
    parser.add_argument("--market-no-network", action="store_true", help="Use theme momentum fallback only.")
    parser.add_argument("--monthly-review", action="store_true", help="Also write monthly review artifacts.")
    parser.add_argument("--previous-report", help="Optional previous advisory report JSON for monthly review.")
    parser.add_argument("--recommendation-review", action="store_true", help="Also write recommendation follow-up review artifacts.")
    parser.add_argument("--site-output-dir", help="Optional static site output directory.")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--feed-title", default=DEFAULT_FEED_TITLE)
    parser.add_argument("--recover-site-archive", action="store_true", help="Recover prior report JSONs from published site index.")
    parser.add_argument("--upstream-repo-sha", action="append", default=[], metavar="REPO=SHA")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    result = build_advisory_artifacts(
        as_of=parse_date(args.as_of),
        cadence=args.cadence,
        political_events_path=args.political_events,
        political_watchlist_path=args.political_watchlist,
        ai_signal_path=args.ai_signal,
        theme_momentum_path=args.theme_momentum,
        market_confirmation_path=args.market_confirmation,
        output_dir=args.output_dir,
        max_candidates=args.max_candidates,
        market_benchmark=args.market_benchmark,
        market_max_symbols=args.market_max_symbols,
        market_request_pause_seconds=args.market_request_pause_seconds,
        market_proxy_list=args.market_proxy_list,
        market_proxy_urls=args.market_proxy_urls,
        market_proxy_pool_url=args.market_proxy_pool_url,
        market_use_network=not args.market_no_network,
        market_cache_dir=args.market_cache_dir,
        market_cache_max_age_days=args.market_cache_max_age_days,
        monthly_review=args.monthly_review,
        previous_report_path=args.previous_report,
        recommendation_review=args.recommendation_review,
        site_output_dir=args.site_output_dir,
        site_url=args.site_url,
        feed_title=args.feed_title,
        recover_site_archive=args.recover_site_archive,
        upstream_repo_shas={key: value for item in args.upstream_repo_sha for key, value in [item.split("=", 1)] if key and value},
        market_compatibility_mode=args.market_compatibility_mode,
    )
    print(
        "advisory_artifacts_built "
        f"as_of={result.as_of.isoformat()} report={result.report_json} site={result.site_output_dir or ''}"
    )


if __name__ == "__main__":
    main()

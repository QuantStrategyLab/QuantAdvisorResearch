from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .build_pipeline import DEFAULT_FEED_TITLE, DEFAULT_SITE_URL, copy_if_different
from .publisher import publish_reports, unique_report_paths_by_content


REPORT_JSON_PATTERN = re.compile(r"advisory_report_\d{4}-\d{2}-\d{2}\.json")


def load_report(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("as_of") or not payload.get("cadence"):
        return None
    return payload


def discover_report_paths(artifact_roots: list[str | Path], explicit_reports: list[str | Path]) -> list[Path]:
    candidates: list[Path] = []
    for report in explicit_reports:
        path = Path(report)
        if path.exists() and path.name.startswith("advisory_report_") and path.suffix == ".json":
            candidates.append(path)
    for root in artifact_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        candidates.extend(
            path
            for path in root_path.rglob("advisory_report_*.json")
            if path.is_file() and REPORT_JSON_PATTERN.fullmatch(path.name)
        )

    by_as_of: dict[str, Path] = {}
    for path in sorted(candidates, key=lambda item: (item.name, str(item))):
        payload = load_report(path)
        if not payload:
            continue
        as_of = str(payload.get("as_of", ""))
        by_as_of[as_of] = path
    return [by_as_of[key] for key in sorted(by_as_of, reverse=True)]


def backfill_site_archive(
    *,
    report_paths: list[Path],
    output_dir: str | Path,
    site_url: str,
    feed_title: str,
) -> list[Path]:
    if not report_paths:
        raise ValueError("No advisory_report_YYYY-MM-DD.json files found for backfill.")
    report_paths = unique_report_paths_by_content(report_paths)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written = publish_reports(report_paths, output, site_url=site_url, feed_title=feed_title)
    for report_path in report_paths:
        copy_if_different(report_path, output / report_path.name)
        markdown_path = report_path.with_suffix(".md")
        manifest_path = Path(f"{report_path}.manifest.json")
        if markdown_path.exists():
            copy_if_different(markdown_path, output / markdown_path.name)
        if manifest_path.exists():
            copy_if_different(manifest_path, output / manifest_path.name)
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill advisory site archive from local workflow artifacts.")
    parser.add_argument("--artifact-root", action="append", default=[], help="Directory to recursively scan for advisory reports.")
    parser.add_argument("--report", action="append", default=[], help="Explicit advisory report JSON path.")
    parser.add_argument("--output-dir", required=True, help="Static site output directory.")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--feed-title", default=DEFAULT_FEED_TITLE)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    reports = discover_report_paths(args.artifact_root, args.report)
    backfill_site_archive(report_paths=reports, output_dir=args.output_dir, site_url=args.site_url, feed_title=args.feed_title)
    print(f"archive_backfill_reports={len(reports)} output={args.output_dir}")


if __name__ == "__main__":
    main()

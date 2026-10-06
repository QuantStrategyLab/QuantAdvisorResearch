from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from quant_advisor_research.identity_lifecycle import parse_v1_index
from quant_advisor_research.publisher import (
    SITE_ICON_FILENAME,
    SITE_ICON_SVG,
    classify_report_path,
    render_archive_html,
    render_feed_xml,
    render_index_html,
    render_report_html,
    render_reports_index_json,
    report_filename,
)


DEFAULT_SITE_URL = "https://quantstrategylab.github.io/QuantAdvisorResearch"
DEFAULT_FEED_TITLE = "智慧投顾研究系统"
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_REPORT_BYTES = 64 * 1024 * 1024
MAX_REPORTS = 1000
REQUEST_TIMEOUT_SECONDS = 20
REPORT_NAME_PATTERN = re.compile(r"^advisory_report_\d{4}-\d{2}-\d{2}\.json$")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError("site_redirect_rejected")


def _read_url(url: str, *, max_bytes: int) -> bytes:
    opener = build_opener(_RejectRedirects())
    with opener.open(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("site_artifact_too_large")
    return data


def _site_origin(site_url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(site_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_site_url")
    if parsed.query or parsed.fragment:
        raise ValueError("invalid_site_url")
    return parsed.scheme, parsed.hostname.lower(), parsed.port


def _artifact_url(site_url: str, filename: str) -> str:
    if not REPORT_NAME_PATTERN.fullmatch(filename) or "/" in filename or "\\" in filename:
        raise ValueError("invalid_report_filename")
    base = site_url.rstrip("/")
    url = f"{base}/{quote(filename, safe='')}"
    if _site_origin(url) != _site_origin(site_url):
        raise ValueError("cross_origin_artifact_url")
    return url


def republish_existing_site(
    *, site_url: str = DEFAULT_SITE_URL, output_dir: str | Path = "site", feed_title: str = DEFAULT_FEED_TITLE,
) -> list[Path]:
    """Fetch and validate the published archive, then render it with current templates."""
    _site_origin(site_url)
    index_bytes = _read_url(f"{site_url.rstrip('/')}/reports_index.json", max_bytes=MAX_INDEX_BYTES)
    try:
        index_payload = json.loads(index_bytes.decode("utf-8"))
        index = parse_v1_index(index_payload)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("invalid_published_reports_index") from None
    if not index.bindings or len(index.bindings) > MAX_REPORTS:
        raise ValueError("published_report_count_out_of_range")

    reports: list[dict[str, object]] = []
    original_json: dict[str, bytes] = {}
    total_bytes = 0
    with tempfile.TemporaryDirectory(prefix="qar-republish-check-") as temp_dir:
        for binding in index.bindings:
            filename = binding.json_name
            if not REPORT_NAME_PATTERN.fullmatch(filename):
                raise ValueError("invalid_report_filename")
            raw = _read_url(_artifact_url(site_url, filename), max_bytes=MAX_REPORT_BYTES)
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_REPORT_BYTES:
                raise ValueError("published_archive_too_large")
            try:
                report = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise ValueError("invalid_published_report_json") from None
            if not isinstance(report, dict):
                raise ValueError("invalid_published_report")
            if report.get("as_of") != binding.as_of or report.get("cadence") != binding.cadence:
                raise ValueError("published_report_index_mismatch")
            if filename != f"advisory_report_{report.get('as_of')}.json":
                raise ValueError("published_report_filename_mismatch")
            # Reuse the publisher's full report contract validator before rendering.
            candidate = Path(temp_dir) / filename
            candidate.write_bytes(raw)
            classification = classify_report_path(candidate)
            candidate.unlink()
            if classification.status != "VALID":
                raise ValueError("unverified_published_report")
            reports.append(report)
            original_json[filename] = raw

    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("site_output_directory_not_empty")
    output.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for report in reports:
        filename = report_filename(report)
        path = output / filename
        path.write_text(render_report_html(report), encoding="utf-8")
        written.append(path)
    icon_path = output / SITE_ICON_FILENAME
    icon_path.write_text(SITE_ICON_SVG, encoding="utf-8")
    written.append(icon_path)
    index_path = output / "index.html"
    index_path.write_text(render_index_html(reports), encoding="utf-8")
    written.append(index_path)
    archive_path = output / "archive.html"
    archive_path.write_text(render_archive_html(reports), encoding="utf-8")
    written.append(archive_path)
    reports_index_path = output / "reports_index.json"
    reports_index_path.write_text(render_reports_index_json(reports), encoding="utf-8")
    written.append(reports_index_path)
    feed_path = output / "feed.xml"
    feed_path.write_text(render_feed_xml(reports, site_url=site_url, feed_title=feed_title), encoding="utf-8")
    written.append(feed_path)
    for filename, raw in original_json.items():
        report_path = output / filename
        report_path.write_bytes(raw)
        written.append(report_path)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Re-render the existing published advisory archive.")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    parser.add_argument("--output-dir", default="site")
    args = parser.parse_args(argv)
    written = republish_existing_site(site_url=args.site_url, output_dir=args.output_dir)
    report_count = sum(path.name.startswith("advisory_report_") and path.suffix == ".json" for path in written)
    print(f"republished_existing_reports={report_count}")
    print(f"republished_site_files={len(written)} output={args.output_dir}")


if __name__ == "__main__":
    main()

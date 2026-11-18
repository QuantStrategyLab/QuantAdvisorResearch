from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._html_renderer import (
    ARCHIVE_PAGE_CSS,
    CADENCE_LABELS_EN,
    CADENCE_LABELS_ZH,
    HORIZON_COLUMNS,
    INDEX_HISTORY_LIMIT,
    INDEX_PAGE_CSS,
    METHOD_DOC_URL,
    REPORT_PAGE_CSS,
    RSS_ITEM_LIMIT,
    SITE_BASE_CSS,
    SITE_ICON_FILENAME,
    SITE_ICON_SVG,
    SITE_MEDIA_CSS,
    SITE_SCRIPT_JS,
    as_sortable_float,
    cadence_label,
    displayed_horizon_symbols,
    format_candidate_theme_ids,
    format_datetime,
    format_horizon_conclusion,
    format_horizon_conclusion_en,
    format_horizon_summary,
    format_momentum_factor_summary,
    format_momentum_factor_summary_en,
    format_report_takeaway,
    format_report_takeaway_en,
    format_theme_ids,
    horizon_display_meta,
    horizon_pick_score,
    horizon_summary_symbols,
    index_inputs_verified,
    index_threshold_unmet,
    join_zh_items,
    ranked_horizon_picks,
    render_archive_card,
    render_archive_html,
    render_feed_xml,
    render_final_card,
    render_final_decisions_html,
    render_horizon_snapshot,
    render_index_empty_conclusion,
    render_index_horizons,
    render_index_html,
    render_report_html,
    render_report_lead,
    render_reports_index_json,
    render_site_mark,
    render_symbol_tags,
    render_theme_first_candidates_html,
    render_theme_momentum_html,
    report_filename,
    slug,
)
from .contracts import AdvisoryValidationError, validate_advisory_report
from .period_contract import CanonicalPeriod, PeriodContractError, canonical_period_identity

__all__ = [
    "ARCHIVE_PAGE_CSS",
    "CADENCE_LABELS_EN",
    "CADENCE_LABELS_ZH",
    "HORIZON_COLUMNS",
    "INDEX_HISTORY_LIMIT",
    "INDEX_PAGE_CSS",
    "METHOD_DOC_URL",
    "REPORT_PAGE_CSS",
    "RSS_ITEM_LIMIT",
    "SITE_BASE_CSS",
    "SITE_ICON_FILENAME",
    "SITE_ICON_SVG",
    "SITE_MEDIA_CSS",
    "SITE_SCRIPT_JS",
    "CandidateClassification",
    "CandidateSelection",
    "as_sortable_float",
    "build_arg_parser",
    "cadence_label",
    "classify_report_path",
    "displayed_horizon_symbols",
    "format_candidate_theme_ids",
    "format_datetime",
    "format_horizon_conclusion",
    "format_horizon_conclusion_en",
    "format_horizon_summary",
    "format_momentum_factor_summary",
    "format_momentum_factor_summary_en",
    "format_report_takeaway",
    "format_report_takeaway_en",
    "format_theme_ids",
    "horizon_display_meta",
    "horizon_pick_score",
    "horizon_summary_symbols",
    "index_inputs_verified",
    "index_threshold_unmet",
    "is_same_period_duplicate",
    "join_zh_items",
    "load_report",
    "main",
    "preflight_publish_destinations",
    "publish_reports",
    "ranked_horizon_picks",
    "render_archive_card",
    "render_archive_html",
    "render_feed_xml",
    "render_final_card",
    "render_final_decisions_html",
    "render_horizon_snapshot",
    "render_index_empty_conclusion",
    "render_index_horizons",
    "render_index_html",
    "render_report_html",
    "render_report_lead",
    "render_reports_index_json",
    "render_site_mark",
    "render_symbol_tags",
    "render_theme_first_candidates_html",
    "render_theme_momentum_html",
    "report_as_of_date",
    "report_content_fingerprint",
    "report_filename",
    "require_publish_candidates",
    "select_publish_candidates",
    "slug",
    "unique_report_paths_by_content",
]


def load_report(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class CandidateClassification:
    artifact_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class CandidateSelection:
    selected_paths: tuple[Path, ...]
    quarantined: tuple[CandidateClassification, ...]
    mandatory_current_status: str = "NOT_REQUIRED"


@dataclass(frozen=True)
class _ReportCandidate:
    path: Path
    artifact_id: str
    report: dict[str, Any] | None
    classification: CandidateClassification
    period: CanonicalPeriod | None = None
    fingerprint: str | None = None
    as_of: dt.date | None = None
    generated_at: dt.datetime | None = None
    schema_version: str | None = None
    input_index: int = 0


def _relative_artifact_ids(paths: list[Path]) -> dict[Path, str]:
    resolved = {path: path.resolve() for path in paths}
    if not resolved:
        return {}
    common_root = Path(os.path.commonpath([str(path.parent) for path in resolved.values()]))
    return {
        path: resolved_path.relative_to(common_root).as_posix()
        for path, resolved_path in resolved.items()
    }


def _is_compatibility_warning(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(
        ("compatibility:", "compatibility_", "schema_compatibility:", "schema_compatibility_")
    )


def report_content_fingerprint(report: dict[str, Any]) -> str:
    ignored_top_level_keys = {
        "as_of", "generated_at", "reference_time", "expires_at", "schema_version",
        "contract_version", "source_artifacts", "input_digest",
    }
    normalized = {key: value for key, value in report.items() if key not in ignored_top_level_keys}
    freshness = normalized.get("freshness")
    if isinstance(freshness, dict):
        normalized["freshness"] = {
            name: {
                key: entry[key]
                for key in ("present", "valid", "reason")
                if key in entry
            }
            for name, entry in freshness.items()
            if isinstance(entry, dict)
        }
    elif "freshness" not in normalized:
        normalized["freshness"] = {
            "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
            "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
        }
    summary = normalized.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("data_quality_warnings"), list):
        summary = dict(summary)
        summary["data_quality_warnings"] = [
            warning for warning in summary["data_quality_warnings"]
            if not _is_compatibility_warning(warning)
        ]
        normalized["summary"] = summary
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def report_as_of_date(report: dict[str, Any]) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(report.get("as_of", "")))
    except ValueError:
        return None


def is_same_period_duplicate(report: dict[str, Any], previous_report: dict[str, Any]) -> bool:
    """Compatibility helper using canonical period equality, never proximity."""
    try:
        return canonical_period_identity(report["cadence"], report["as_of"]) == canonical_period_identity(
            previous_report["cadence"], previous_report["as_of"]
        )
    except (KeyError, PeriodContractError, TypeError):
        return False


def _invalid_candidate(path: Path, artifact_id: str, reason: str, index: int) -> _ReportCandidate:
    return _ReportCandidate(path, artifact_id, None, CandidateClassification(artifact_id, "INVALID", reason), input_index=index)


def _load_candidate(path: Path, artifact_id: str, index: int) -> _ReportCandidate:
    try:
        report = load_report(path)
    except (OSError, UnicodeError):
        return _ReportCandidate(path, artifact_id, None, CandidateClassification(artifact_id, "IO_INVALID", "io_invalid"), input_index=index)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _ReportCandidate(path, artifact_id, None, CandidateClassification(artifact_id, "IO_INVALID", "json_invalid"), input_index=index)
    if not isinstance(report, dict):
        return _invalid_candidate(path, artifact_id, "report_object_invalid", index)
    schema_version = report.get("schema_version") if isinstance(report.get("schema_version"), str) else None
    try:
        validate_advisory_report(report)
    except (AdvisoryValidationError, AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return _invalid_candidate(path, artifact_id, "contract_invalid", index)
    try:
        cadence = report["cadence"]
        as_of = report["as_of"]
        period = canonical_period_identity(cadence, as_of)
        generated_text = report["generated_at"]
        normalized = generated_text[:-1] + "+00:00" if generated_text.endswith("Z") else generated_text
        generated_at = dt.datetime.fromisoformat(normalized)
        if generated_at.tzinfo is None:
            if schema_version != "5":
                return _invalid_candidate(path, artifact_id, "generated_at_invalid", index)
            generated_at = generated_at.replace(tzinfo=dt.UTC)
        generated_at = generated_at.astimezone(dt.UTC)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, PeriodContractError):
        return _invalid_candidate(path, artifact_id, "period_or_generated_at_invalid", index)
    classification = CandidateClassification(artifact_id, "VALID", "valid")
    return _ReportCandidate(
        path=path,
        artifact_id=artifact_id,
        report=report,
        classification=classification,
        period=period,
        fingerprint=report_content_fingerprint(report),
        as_of=report_as_of_date(report),
        generated_at=generated_at,
        schema_version=schema_version,
        input_index=index,
    )


def classify_report_path(path: str | Path) -> CandidateClassification:
    candidate = _load_candidate(Path(path), Path(path).name, 0)
    return candidate.classification


def _canonical_paths(paths: list[str | Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _schema_rank(candidate: _ReportCandidate) -> int:
    return {"5": 5, "6": 6}.get(candidate.schema_version, -1)


def _rank_candidates(candidates: list[_ReportCandidate]) -> list[_ReportCandidate]:
    ranked = sorted(candidates, key=lambda candidate: candidate.artifact_id)
    ranked.sort(
        key=lambda candidate: candidate.generated_at or dt.datetime.min.replace(tzinfo=dt.UTC),
        reverse=True,
    )
    ranked.sort(key=_schema_rank, reverse=True)
    ranked.sort(key=lambda candidate: candidate.as_of or dt.date.min, reverse=True)
    return ranked


def select_publish_candidates(
    mandatory_current: str | Path | None,
    recovered_history: list[str | Path],
) -> CandidateSelection:
    if mandatory_current is not None and not Path(mandatory_current).exists():
        raise ValueError("mandatory_current_missing")
    raw_paths = ([mandatory_current] if mandatory_current is not None else []) + list(recovered_history)
    paths = _canonical_paths([path for path in raw_paths if path is not None])
    artifact_ids = _relative_artifact_ids(paths)
    candidates = [_load_candidate(path, artifact_ids[path], index) for index, path in enumerate(paths)]
    quarantined = tuple(candidate.classification for candidate in candidates if candidate.report is None)
    mandatory_resolved = Path(mandatory_current).resolve() if mandatory_current is not None else None
    mandatory_candidate = next(
        (candidate for candidate in candidates if candidate.path.resolve() == mandatory_resolved), None
    )
    if mandatory_current is not None and mandatory_candidate is None:
        raise ValueError("mandatory_current_missing")
    if mandatory_candidate is not None and mandatory_candidate.report is None:
        return CandidateSelection(tuple(), quarantined, "INVALID")
    if mandatory_candidate is not None:
        expected_name = f"advisory_report_{mandatory_candidate.as_of.isoformat()}.json"
        if mandatory_candidate.path.name != expected_name:
            return CandidateSelection(tuple(), quarantined, "INVALID_FILENAME")

    valid_candidates = [candidate for candidate in candidates if candidate.report is not None]
    grouped: dict[tuple[str, str], list[_ReportCandidate]] = {}
    for candidate in valid_candidates:
        assert candidate.period is not None and candidate.fingerprint is not None
        grouped.setdefault((candidate.period.key, candidate.fingerprint), []).append(candidate)
    selected: list[_ReportCandidate] = []
    for group in grouped.values():
        if mandatory_candidate in group:
            selected.append(mandatory_candidate)
        else:
            selected.append(_rank_candidates(group)[0])
    selected.sort(key=lambda candidate: candidate.input_index)
    status = "VALID_SELECTED" if mandatory_current is not None else "NOT_REQUIRED"
    return CandidateSelection(tuple(candidate.path for candidate in selected), quarantined, status)


def require_publish_candidates(
    mandatory_current: str | Path | None,
    recovered_history: list[str | Path],
) -> CandidateSelection:
    selection = select_publish_candidates(mandatory_current, recovered_history)
    if mandatory_current is not None and selection.mandatory_current_status == "INVALID_FILENAME":
        raise ValueError("mandatory_current_filename_invalid")
    if mandatory_current is not None and selection.mandatory_current_status != "VALID_SELECTED":
        raise ValueError("mandatory_current_invalid")
    if mandatory_current is None and recovered_history and not selection.selected_paths:
        raise ValueError("no_valid_report_candidates")
    return selection


def unique_report_paths_by_content(report_paths: list[str | Path]) -> list[Path]:
    return list(require_publish_candidates(None, report_paths).selected_paths)


def preflight_publish_destinations(report_paths: list[str | Path]) -> None:
    destinations: dict[tuple[str, str], tuple[Path, str]] = {}
    for raw_path in report_paths:
        path = Path(raw_path)
        report = load_report(path)
        fingerprint = report_content_fingerprint(report)
        names = (
            ("html", report_filename(report)),
            ("json", path.name),
            ("markdown", path.with_suffix(".md").name),
            ("manifest", f"{path.name}.manifest.json"),
        )
        for kind, name in names:
            identity = (kind, name)
            previous = destinations.get(identity)
            if previous is not None and (previous[0] != path.resolve() or previous[1] != fingerprint):
                raise ValueError("archive_destination_collision")
            destinations[identity] = (path.resolve(), fingerprint)


def publish_reports(
    report_paths: list[str | Path],
    output_dir: str | Path,
    *,
    site_url: str,
    feed_title: str,
    mandatory_current: str | Path | None = None,
    recovered_history: list[str | Path] | None = None,
    reject_invalid: bool = False,
) -> list[Path]:
    if mandatory_current is None:
        selection = require_publish_candidates(None, report_paths)
    else:
        history = list(recovered_history) if recovered_history is not None else [
            path for path in report_paths if Path(path).resolve() != Path(mandatory_current).resolve()
        ]
        selection = require_publish_candidates(mandatory_current, history)
    if reject_invalid and selection.quarantined:
        raise ValueError("invalid_report_candidate")
    preflight_publish_destinations(list(selection.selected_paths))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_paths = list(selection.selected_paths)
    reports = [load_report(path) for path in report_paths]
    written: list[Path] = []
    for report in reports:
        path = output / report_filename(report)
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
    return written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish intelligent advisory research reports as static HTML and RSS.")
    parser.add_argument("--reports", nargs="+", required=True, help="One or more advisory report JSON files.")
    parser.add_argument("--output-dir", required=True, help="Static site output directory.")
    parser.add_argument("--site-url", default="https://quantstrategylab.github.io/QuantAdvisorResearch")
    parser.add_argument("--feed-title", default="智慧投顾研究系统")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    publish_reports(
        args.reports,
        args.output_dir,
        site_url=args.site_url,
        feed_title=args.feed_title,
        reject_invalid=True,
    )


if __name__ == "__main__":
    main()

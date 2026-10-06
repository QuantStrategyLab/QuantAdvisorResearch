from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .advisory_report import display_number, display_percent, sector_label, theme_label
from .contracts import AdvisoryValidationError, validate_advisory_report
from .time_contract import is_report_expired
from .period_contract import CanonicalPeriod, PeriodContractError, canonical_period_identity


CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}

HORIZON_COLUMNS = (
    ("long", "长线", "1-3年"),
    ("medium", "中线", "2-12周"),
    ("short", "短线", "1-10个交易日"),
)
INDEX_HISTORY_LIMIT = 12
RSS_ITEM_LIMIT = 20

SITE_ICON_FILENAME = "favicon.svg"
SITE_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="4" y="4" width="56" height="56" rx="12" fill="#172033"/>
  <rect x="15" y="17" width="34" height="7" rx="1.5" fill="#f3f4f1"/>
  <rect x="15" y="29" width="24" height="7" rx="1.5" fill="#f3f4f1"/>
  <rect x="15" y="41" width="14" height="7" rx="1.5" fill="#4fb3a7"/>
</svg>
"""


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "report"


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


def format_datetime(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def report_filename(report: dict[str, Any]) -> str:
    return f"{report['as_of']}-{slug(report['cadence'])}-model-recommendations.html"


def cadence_label(report: dict[str, Any]) -> str:
    cadence = str(report.get("cadence", ""))
    return CADENCE_LABELS_ZH.get(cadence, cadence.title())


def format_theme_ids(theme_ids: Any) -> str:
    if isinstance(theme_ids, str):
        theme_ids = [theme_ids]
    if not isinstance(theme_ids, list):
        theme_ids = []
    return ", ".join(theme_label(theme_id) for theme_id in theme_ids) or "无"


def format_candidate_theme_ids(candidate: dict[str, Any]) -> str:
    theme_name_by_id = {
        str(theme.get("theme_id", "")): str(theme.get("theme_name", ""))
        for theme in candidate.get("themes", [])
        if isinstance(theme, dict)
    }
    labels = [
        theme_label(theme_id, theme_name_by_id.get(str(theme_id), ""))
        for theme_id in candidate.get("theme_ids", [])
    ]
    return ", ".join(labels) or "无"


SITE_BASE_CSS = """
    :root {
      color-scheme: light dark;
      --paper: #f3f4f1;
      --sheet: #fbfbf9;
      --well: #e8eae6;
      --ink: #172033;
      --ink-soft: #343d4f;
      --muted: #5b6372;
      --rule: #d5d8d6;
      --rule-strong: #172033;
      --accent: #0b5d57;
      --accent-wash: #dcebe8;
      --mark-bg: #172033;
      --mark-fg: #f3f4f1;
      --radius-s: 3px;
      --radius-m: 6px;
      --measure: 38em;
      --container: 1180px;
      --gutter: clamp(16px, 4vw, 40px);
      --font-sans: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", ui-sans-serif, system-ui, sans-serif;
      --font-display: "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", "STSong", "SimSun", ui-serif, serif;
      --font-figures: "SF Mono", ui-monospace, "Menlo", "Consolas", monospace;
      font-family: var(--font-sans);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --paper: #11151b;
        --sheet: #171c23;
        --well: #1e242d;
        --ink: #e5e7ea;
        --ink-soft: #c5cad2;
        --muted: #98a0ad;
        --rule: #2b323c;
        --rule-strong: #c5cad2;
        --accent: #6cc3b8;
        --accent-wash: #16302e;
        --mark-bg: #e5e7ea;
        --mark-fg: #11151b;
      }
    }
    * { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      min-height: 100dvh;
      background: var(--paper);
      color: var(--ink);
      font-size: 16px;
      line-height: 1.75;
      font-variant-numeric: tabular-nums;
      text-rendering: optimizeLegibility;
      overflow-x: hidden;
    }
    a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 4px; word-break: break-word; transition: color .15s ease, border-color .15s ease, background-color .15s ease; }
    a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: var(--radius-s); }
    h1, h2, h3 { color: var(--ink); text-wrap: balance; }
    p { text-wrap: pretty; }

    /* Masthead: a periodical nameplate, heavy rule above, hairline below. */
    .site-header { padding: 0 var(--gutter); }
    .site-header-inner, .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 60px;
      border-top: 4px solid var(--rule-strong);
      border-bottom: 1px solid var(--rule);
    }
    .site-header-inner { max-width: calc(var(--container) - 2 * var(--gutter)); margin: 0 auto; }
    .brand-link {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--ink);
      text-decoration: none;
      font-family: var(--font-display);
      font-size: 1.0625rem;
      font-weight: 700;
      letter-spacing: .01em;
    }
    .site-mark { flex: 0 0 auto; display: inline-flex; width: 26px; height: 26px; }
    .site-mark svg { width: 100%; height: 100%; }
    .site-mark rect.mark-plate { fill: var(--mark-bg); }
    .site-mark rect.mark-bar { fill: var(--mark-fg); }
    .site-mark rect.mark-bar-accent { fill: var(--accent); }
    .site-nav, .topbar-actions { display: flex; flex-wrap: wrap; gap: 0 22px; justify-content: flex-end; }
    .site-nav a, .topbar-actions a {
      display: inline-flex;
      align-items: center;
      min-height: 44px;
      color: var(--ink-soft);
      font-size: .9375rem;
      text-decoration: none;
      border-bottom: 1px solid transparent;
    }
    .site-nav a:hover, .topbar-actions a:hover { color: var(--ink); text-decoration: underline; }

    .eyebrow { margin: 0 0 14px; color: var(--muted); font-size: .875rem; font-weight: 500; letter-spacing: .02em; }

    /* Ticker tags: typeset like figures in a table, not pills. */
    .symbol-strip { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; }
    .symbol-tag {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 0 8px;
      border: 1px solid var(--rule);
      border-radius: var(--radius-s);
      background: var(--sheet);
      color: var(--ink);
      font-family: var(--font-figures);
      font-size: .8125rem;
      font-weight: 600;
      letter-spacing: .04em;
      font-variant-numeric: tabular-nums;
    }
    .symbol-tag.empty { font-family: var(--font-sans); background: transparent; border-color: transparent; padding-left: 0; color: var(--muted); font-weight: 400; letter-spacing: 0; }

    /* Horizon snapshot: a three-row ledger (label | window | tickers), never three columns. */
    .snapshot-grid { display: grid; grid-template-columns: 1fr; margin: 0; border-top: 1px solid var(--rule-strong); }
    .snapshot-column {
      display: grid;
      grid-template-columns: 3.5em 7.5em minmax(0, 1fr);
      gap: 4px 16px;
      align-items: baseline;
      padding: 12px 0;
      border-bottom: 1px solid var(--rule);
    }
    .snapshot-label { margin: 0; font-family: var(--font-display); font-size: 1.0625rem; font-weight: 700; line-height: 1.4; }
    .snapshot-window { margin: 0; color: var(--muted); font-size: .8125rem; white-space: nowrap; }
    .horizon-link { display: flex; flex-wrap: wrap; gap: 6px 8px; color: inherit; text-decoration: none; border-radius: var(--radius-s); }
    .horizon-link:hover .symbol-tag:not(.empty) { border-color: var(--accent); }

    /* History: a dated ledger of issues, one row per issue. */
    .archive-grid { display: grid; grid-template-columns: 1fr; border-top: 1px solid var(--rule-strong); }
    .archive-card {
      display: grid;
      grid-template-columns: minmax(11em, 15em) minmax(0, 1fr) minmax(0, 1.25fr);
      grid-template-areas: "title signal snap" "title tags snap";
      grid-template-rows: auto 1fr;
      gap: 6px 32px;
      align-items: start;
      padding: 20px 0;
      border-bottom: 1px solid var(--rule);
    }
    .archive-title {
      grid-area: title;
      color: var(--ink);
      font-family: var(--font-display);
      font-size: 1.125rem;
      font-weight: 700;
      line-height: 1.45;
      text-decoration: none;
    }
    .archive-title:hover { color: var(--accent); text-decoration: underline; }
    .archive-card > p { grid-area: signal; margin: 0; color: var(--ink-soft); font-size: .9375rem; line-height: 1.65; }
    .archive-symbols { grid-area: tags; display: flex; flex-wrap: wrap; gap: 6px 8px; }
    .archive-card .snapshot-grid { grid-area: snap; border-top: 0; }
    .archive-card .snapshot-column { grid-template-columns: 3em minmax(0, 1fr); padding: 3px 0; border-bottom: 0; }
    .archive-card .snapshot-label { font-family: var(--font-sans); font-size: .875rem; font-weight: 600; color: var(--muted); }
    .archive-card .snapshot-window { display: none; }
    .empty-archive { margin: 0; padding: 28px 0; color: var(--muted); text-align: center; }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
    }
    @media (max-width: 900px) {
      .archive-card { grid-template-columns: minmax(0, 1fr); grid-template-areas: "title" "signal" "tags" "snap"; grid-template-rows: none; gap: 8px; }
      .archive-card .snapshot-grid { margin-top: 4px; }
    }
    @media (max-width: 720px) {
      .site-header-inner, .topbar { flex-direction: column; align-items: flex-start; justify-content: center; gap: 0; padding-top: 10px; }
      .site-nav, .topbar-actions { justify-content: flex-start; }
      .snapshot-column { grid-template-columns: 3em minmax(0, 1fr); }
      .snapshot-window { grid-column: 2; grid-row: 1; }
      .snapshot-column .symbol-strip { grid-column: 1 / -1; }
      .archive-card .snapshot-column .symbol-strip { grid-column: 2; grid-row: 1; }
    }
"""

REPORT_PAGE_CSS = """
    .report-shell { max-width: var(--container); margin: 0 auto; padding: 0 var(--gutter) 96px; }
    .report-hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 15em;
      gap: clamp(28px, 5vw, 64px);
      align-items: start;
      padding: clamp(36px, 6vw, 64px) 0 36px;
      border-bottom: 1px solid var(--rule-strong);
    }
    .report-hero-copy { max-width: 46em; }
    h1 { margin: 0; font-family: var(--font-display); font-size: clamp(2rem, 4.4vw, 3.25rem); font-weight: 700; line-height: 1.18; letter-spacing: .005em; }
    .report-lead { margin: 22px 0 0; max-width: var(--measure); color: var(--ink-soft); font-size: 1.0625rem; line-height: 1.9; }
    .date-card {
      display: grid;
      gap: 4px;
      align-content: start;
      padding: 14px 0 0;
      border-top: 1px solid var(--rule-strong);
    }
    .date-card .date-label { margin: 0; color: var(--muted); font-size: .8125rem; }
    .date-card .date-value { margin: 0; font-family: var(--font-figures); font-size: clamp(1.375rem, 2.2vw, 1.75rem); font-weight: 600; line-height: 1.25; letter-spacing: -.01em; white-space: nowrap; }
    .date-card .cadence-value { margin: 10px 0 0; justify-self: start; padding: 1px 8px; border-radius: var(--radius-s); background: var(--accent-wash); color: var(--accent); font-size: .8125rem; font-weight: 600; }

    /* Decisions: each horizon is a section with a sticky left rail and a stack of notes. */
    .final-decisions { margin-top: 8px; }
    .horizon-columns { display: grid; grid-template-columns: 1fr; }
    .horizon-column {
      display: grid;
      grid-template-columns: 12em minmax(0, 1fr);
      gap: 0 clamp(24px, 4vw, 56px);
      padding: 32px 0;
      border-bottom: 1px solid var(--rule);
    }
    .horizon-column-header { align-self: start; position: sticky; top: 16px; }
    .horizon-column-header h2 { margin: 0; font-family: var(--font-display); font-size: 1.75rem; font-weight: 700; line-height: 1.2; }
    .horizon-column-header p { margin: 6px 0 0; color: var(--muted); font-size: .875rem; }
    .horizon-cards { display: grid; gap: 0; }
    .empty-column { margin: 0; padding: 6px 0; color: var(--muted); }

    .final-card {
      display: grid;
      grid-template-columns: 9em minmax(0, 1fr);
      gap: 0 28px;
      padding: 0 0 24px;
      margin-bottom: 24px;
      border-bottom: 1px dashed var(--rule);
    }
    .final-card:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: 0; }
    .final-card header { grid-column: 1; grid-row: 1 / span 4; }
    .final-card h3 { margin: 0; display: flex; flex-direction: column; gap: 2px; font-family: var(--font-figures); font-size: 1.5rem; font-weight: 600; line-height: 1.2; letter-spacing: .02em; }
    .final-card .rank { color: var(--accent); font-family: var(--font-sans); font-size: .8125rem; font-weight: 600; letter-spacing: 0; }
    .final-card header p { margin: 6px 0 0; color: var(--muted); font-size: .875rem; line-height: 1.5; }
    .final-card dl { grid-column: 2; margin: 0; }
    .final-card dl div { display: flex; gap: 10px; align-items: baseline; }
    .final-card dt { color: var(--muted); font-size: .8125rem; }
    .final-card dd { margin: 0; font-size: .875rem; font-weight: 600; }
    .final-card > p { grid-column: 2; margin: 10px 0 0; max-width: var(--measure); color: var(--ink-soft); font-size: .9688rem; line-height: 1.85; }
    .final-card strong { color: var(--ink); font-weight: 600; }

    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; border-bottom: 1px solid var(--rule); padding: 8px; vertical-align: top; }
    .theme-candidates, .theme-momentum, .recommendation-section, .recommendation, .monitor-note, .horizon-note { display: none; }
    @media (max-width: 960px) {
      .report-hero { grid-template-columns: minmax(0, 1fr); gap: 24px; }
      .date-card { grid-template-columns: auto auto 1fr; align-items: baseline; column-gap: 14px; }
      .date-card .cadence-value { margin: 0; }
      .horizon-column { grid-template-columns: minmax(0, 1fr); gap: 20px; }
      .horizon-column-header { position: static; display: flex; align-items: baseline; gap: 14px; }
      .horizon-column-header p { margin: 0; }
    }
    @media (max-width: 600px) {
      .final-card { grid-template-columns: minmax(0, 1fr); }
      .final-card header, .final-card dl, .final-card > p { grid-column: 1; grid-row: auto; }
      .final-card header { margin-bottom: 10px; }
      .final-card h3 { flex-direction: row; align-items: baseline; gap: 12px; }
    }
"""

INDEX_PAGE_CSS = """
    main { max-width: var(--container); margin: 0 auto; padding: 0 var(--gutter) 96px; }
    .hero { padding: clamp(40px, 7vw, 80px) 0 clamp(28px, 4vw, 44px); }
    .hero-copy { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px clamp(28px, 5vw, 72px); align-items: end; }
    h1 { margin: 0; font-family: var(--font-display); font-size: clamp(2.375rem, 5.6vw, 4rem); font-weight: 700; line-height: 1.08; letter-spacing: .005em; }
    .hero p { margin: 0; max-width: 30em; padding-left: 18px; border-left: 2px solid var(--accent); color: var(--ink-soft); font-size: 1rem; line-height: 1.85; }

    /* Latest issue: lead story set against the paper, not a boxed card. */
    .latest-panel {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
      gap: clamp(28px, 5vw, 72px);
      padding: 28px 0 36px;
      border-top: 4px solid var(--rule-strong);
      border-bottom: 1px solid var(--rule);
    }
    h2 { margin: 0; font-family: var(--font-display); font-size: clamp(1.5rem, 2.8vw, 2.125rem); font-weight: 700; line-height: 1.28; }
    .lead { margin: 14px 0 0; max-width: 32em; color: var(--ink-soft); line-height: 1.85; }
    .theme-line { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 14px; align-items: baseline; margin: 22px 0 10px; color: var(--ink); line-height: 1.6; }
    .theme-line span { color: var(--muted); font-size: .8125rem; }
    .hero-symbols { margin-bottom: 26px; }
    .primary-action {
      display: inline-flex;
      align-items: center;
      min-height: 44px;
      padding: 0 2px;
      color: var(--ink);
      font-family: var(--font-display);
      font-size: 1.0625rem;
      font-weight: 700;
      text-decoration: none;
      border-bottom: 2px solid var(--accent);
      white-space: nowrap;
    }
    .primary-action:hover { color: var(--accent); }
    .latest-panel > .snapshot-grid { align-self: start; }

    .archive { margin-top: clamp(48px, 7vw, 80px); }
    .section-title { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 0; padding-bottom: 14px; }
    .section-title h2 { font-size: 1.5rem; }
    .section-title p { margin: 4px 0 0; color: var(--muted); font-size: .875rem; }
    .archive-action { display: inline-flex; align-items: center; min-height: 44px; font-weight: 600; white-space: nowrap; text-decoration: underline; }
    @media (max-width: 960px) {
      .hero-copy, .latest-panel { grid-template-columns: minmax(0, 1fr); }
    }
    @media (max-width: 640px) {
      .section-title { flex-direction: column; align-items: flex-start; gap: 4px; }
    }
"""

ARCHIVE_PAGE_CSS = """
    main { max-width: var(--container); margin: 0 auto; padding: 0 var(--gutter) 96px; }
    .hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px clamp(28px, 5vw, 72px); align-items: end; padding: clamp(36px, 6vw, 64px) 0 12px; }
    h1 { margin: 0; font-family: var(--font-display); font-size: clamp(2rem, 4.6vw, 3.25rem); font-weight: 700; line-height: 1.15; }
    .hero p { margin: 0; max-width: 32em; padding-left: 18px; border-left: 2px solid var(--accent); color: var(--ink-soft); font-size: 1rem; line-height: 1.85; }
    .month-group { display: grid; grid-template-columns: 9em minmax(0, 1fr); gap: 0 clamp(20px, 3vw, 40px); margin-top: 44px; }
    .month-group h2 { margin: 0; padding-top: 18px; border-top: 4px solid var(--rule-strong); font-family: var(--font-display); font-size: 1.25rem; font-weight: 700; line-height: 1.35; }
    @media (max-width: 900px) {
      .hero, .month-group { grid-template-columns: minmax(0, 1fr); }
      .month-group h2 { padding: 12px 0; }
    }
"""


def render_site_mark() -> str:
    return """
    <span class="site-mark" aria-hidden="true">
      <svg viewBox="0 0 64 64" focusable="false">
        <rect class="mark-plate" x="4" y="4" width="56" height="56" rx="12"></rect>
        <rect class="mark-bar" x="15" y="17" width="34" height="7" rx="1.5"></rect>
        <rect class="mark-bar" x="15" y="29" width="24" height="7" rx="1.5"></rect>
        <rect class="mark-bar-accent" x="15" y="41" width="14" height="7" rx="1.5"></rect>
      </svg>
    </span>
    """


def horizon_pick_score(pick: dict[str, Any], horizon: str) -> float:
    score = pick.get("horizon_scores", {}).get(horizon, {}).get("score")
    return float(score) if isinstance(score, (int, float)) else as_sortable_float(pick.get("combined_score"))


def as_sortable_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def ranked_horizon_picks(final_picks: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    primary_picks = [pick for pick in final_picks if pick.get("primary_horizon") == horizon]
    if horizon == "long" and not primary_picks:
        picks = [
            pick
            for pick in final_picks
            if pick.get("horizon_actions", {}).get(horizon) in {"recommend", "watch"}
        ]
    else:
        picks = primary_picks
    return sorted(picks, key=lambda pick: (-horizon_pick_score(pick, horizon), str(pick.get("symbol", ""))))


def horizon_display_meta(pick: dict[str, Any], horizon: str) -> tuple[str, str, float]:
    labels = {"short": "短线", "medium": "中线", "long": "长线"}
    windows = {"short": "1-10个交易日", "medium": "2-12周", "long": "1-3年"}
    if pick.get("primary_horizon") == horizon:
        label = str(pick.get("primary_horizon_label") or labels.get(horizon, ""))
        window = str(pick.get("primary_horizon_window") or windows.get(horizon, ""))
        score = as_sortable_float(pick.get("combined_score"))
        return label, window, score
    score = horizon_pick_score(pick, horizon)
    return labels.get(horizon, ""), windows.get(horizon, ""), score


def render_final_card(pick: dict[str, Any], *, rank: int, horizon: str) -> str:
    horizon_label, horizon_window, _score = horizon_display_meta(pick, horizon)
    return f"""
    <article class="final-card">
      <header>
        <h3><span class="rank">推荐 #{rank}</span>{html.escape(str(pick.get('symbol', '')))}</h3>
        <p>{html.escape(str(pick.get('name', '')))}</p>
      </header>
      <dl>
        <div><dt>周期</dt><dd>{html.escape(horizon_label)} / {html.escape(horizon_window)}</dd></div>
      </dl>
      <p><strong>股票背景：</strong>{html.escape(str(pick.get('business_summary', '')))}</p>
      <p><strong>推荐理由：</strong>{html.escape(str(pick.get('prospect_summary', '')))}</p>
      <p><strong>主要风险：</strong>{html.escape(str(pick.get('risk_summary', '')))}</p>
    </article>
    """


def join_zh_items(items: list[str], *, limit: int = 5, empty: str = "暂无") -> str:
    cleaned = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    if not cleaned:
        return empty
    visible = cleaned[:limit]
    suffix = "等" if len(cleaned) > limit else ""
    return "、".join(visible) + suffix


def displayed_horizon_symbols(report: dict[str, Any], horizon: str) -> list[str]:
    decisions = report.get("final_decisions", {})
    if not isinstance(decisions, dict):
        return []
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    return [
        str(pick.get("symbol", "")).strip()
        for pick in ranked_horizon_picks(final_picks, horizon)
        if str(pick.get("symbol", "")).strip()
    ]


def format_horizon_conclusion(report: dict[str, Any]) -> str:
    parts = []
    for horizon, label, _window in HORIZON_COLUMNS:
        symbols = displayed_horizon_symbols(report, horizon)
        value = join_zh_items(symbols, empty="暂无稳定结论")
        parts.append(f"{label}：{value}")
    return "；".join(parts)


def format_momentum_factor_summary(report: dict[str, Any]) -> str:
    theme_momentum = report.get("theme_momentum", {})
    if not isinstance(theme_momentum, dict) or not theme_momentum.get("available"):
        return "本期暂无足够稳定的主题排序。"

    themes = [theme for theme in theme_momentum.get("top_themes", []) if isinstance(theme, dict)]
    theme_names = [theme_label(theme.get("theme_id"), theme.get("theme_name")) for theme in themes[:4]]
    sectors = [sector_label(theme.get("sector")) for theme in themes[:4]]
    sector_text = join_zh_items(sectors, limit=3, empty="暂无明确板块")
    theme_text = join_zh_items(theme_names, limit=4, empty="暂无明确主题")
    if sector_text == "暂无明确板块":
        return f"本期较突出的方向包括 {theme_text}。"
    return f"本期较突出的方向主要在{sector_text}板块，代表主题包括 {theme_text}。"


def format_report_takeaway(report: dict[str, Any]) -> str:
    has_long = bool(displayed_horizon_symbols(report, "long"))
    has_medium = bool(displayed_horizon_symbols(report, "medium"))
    has_short = bool(displayed_horizon_symbols(report, "short"))
    if has_long and has_medium and has_short:
        return "整体看，当前结论存在跨周期共振，后续重点观察趋势能否延续和风险事件变化。"
    if has_long and has_medium:
        return "整体看，当前结论更偏中长线，短线暂不强调，后续重点观察趋势能否延续和基本面兑现。"
    if has_medium:
        return "整体看，当前结论更偏中线，短线暂不强调，后续重点观察趋势能否延续和基本面兑现。"
    if has_long:
        return "整体看，当前信号更偏长线观察，短线和中线暂未形成稳定排序。"
    if has_short:
        return "整体看，当前只出现短线机会，持续性仍需要后续数据确认。"
    return "整体看，当前暂未形成稳定系统结论，继续等待更清晰的主题和价格确认。"


def render_report_lead(report: dict[str, Any]) -> str:
    return " ".join(
        [
            f"本期结论：{format_horizon_conclusion(report)}。",
            format_momentum_factor_summary(report),
            format_report_takeaway(report),
        ]
    )


def render_final_decisions_html(report: dict[str, Any]) -> str:
    decisions = report.get("final_decisions", {})
    if not decisions:
        return ""
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    columns = []
    for horizon, label, window in HORIZON_COLUMNS:
        cards = [
            render_final_card(pick, rank=index, horizon=horizon)
            for index, pick in enumerate(ranked_horizon_picks(final_picks, horizon), start=1)
        ]
        body = "".join(cards)
        if not body:
            body = '<p class="empty-column">暂无</p>'
        columns.append(
            f"""
            <section class="horizon-column horizon-{html.escape(horizon)}">
              <header class="horizon-column-header">
                <h2>{html.escape(label)}</h2>
                <p>{html.escape(window)}</p>
              </header>
              <div class="horizon-cards">{body}</div>
            </section>
            """
        )
    return f"""
    <section class="final-decisions">
      <div class="horizon-columns">{''.join(columns)}</div>
    </section>
    """


def render_theme_first_candidates_html(report: dict[str, Any]) -> str:
    candidates = report.get("theme_first_candidates", [])
    if not candidates:
        return ""
    cards = []
    for candidate in candidates:
        theme_ids = format_candidate_theme_ids(candidate)
        primary_theme = theme_label(candidate.get("primary_theme_id"), candidate.get("primary_theme_name"))
        reasons = candidate.get("reasons", [])
        reason = reasons[0] if reasons else ""
        cards.append(
            f"""
            <article class="candidate-card">
              <header>
                <span class="rank">#{html.escape(str(candidate.get('rank', '')))}</span>
                <div>
                  <h3>{html.escape(str(candidate.get('symbol', '')))}</h3>
                  <p>{html.escape(str(candidate.get('industry_background', '')))}</p>
                </div>
              </header>
              <dl>
                <div><dt>主题</dt><dd>{html.escape(primary_theme)}</dd></div>
                <div><dt>动量强度</dt><dd>{html.escape(display_number(candidate.get('symbol_momentum_score')))}</dd></div>
                <div><dt>近3个月</dt><dd>{html.escape(display_percent(candidate.get('return_3m')))}</dd></div>
                <div><dt>事件证据</dt><dd>{html.escape(str(candidate.get('source_confirmation', '')))}</dd></div>
                <div><dt>当前结论</dt><dd>{html.escape(str(candidate.get('advisor_status', '')))}</dd></div>
              </dl>
              <p><strong>为什么入选：</strong>{html.escape(str(candidate.get('recommendation_summary') or reason))}</p>
              <p><strong>主要风险：</strong>{html.escape(str(candidate.get('risk_summary', '')))}</p>
              <p><strong>相关主题：</strong>{html.escape(theme_ids)}</p>
            </article>
            """
        )
    return f"""
    <section class="theme-candidates">
      <h2>主题候选（解释材料，不是最终推荐）</h2>
      <p><strong>用途：</strong>这里只解释哪些股票进入主题/动量候选池，公开页面默认只显示最终推荐。</p>
      <p><strong>怎么理解：</strong>这是非个性化模型股票池，不是买入清单；“暂无明确事件催化”表示该标的主要来自主题/动量排序，
      还没有足够稳定的新闻、政策或公司事件证据。</p>
      <div class="candidate-grid">{''.join(cards)}</div>
    </section>
    """


def render_theme_momentum_html(report: dict[str, Any]) -> str:
    theme_momentum = report.get("theme_momentum", {})
    if not theme_momentum.get("available"):
        return ""
    rows = []
    for theme in theme_momentum.get("top_themes", []):
        symbols = ", ".join(theme.get("top_symbols", [])) or "无"
        theme_name = theme_label(theme.get("theme_id"), theme.get("theme_name"))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(theme.get('rank', '')))}</td>"
            f"<td>{html.escape(theme_name)}</td>"
            f"<td>{html.escape(sector_label(theme.get('sector', '')))}</td>"
            f"<td>{html.escape(display_number(theme.get('momentum_score')))}</td>"
            f"<td>{html.escape(display_percent(theme.get('breadth_3m')))}</td>"
            f"<td>{html.escape(symbols)}</td>"
            "</tr>"
        )
    return f"""
    <section class="theme-momentum">
      <h2>主题动量</h2>
      <p>研究用途主题排序，快照日期：{html.escape(str(theme_momentum.get('as_of', '')))}。
      主题动量只提示强主题和候选标的，不直接改变推荐评级。</p>
      <table>
        <thead><tr><th>排名</th><th>主题</th><th>板块</th><th>分数</th><th>3个月广度</th><th>代表标的</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>
    """

def render_report_html(report: dict[str, Any]) -> str:
    title = f"智慧投顾研究{cadence_label(report)}复盘 - {report['as_of']}"
    display_title = f"智慧投顾研究{cadence_label(report)}复盘"
    final_decisions_html = render_final_decisions_html(report)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>{SITE_BASE_CSS}{REPORT_PAGE_CSS}  </style>
</head>
<body>
  <main class="report-shell">
    <nav class="topbar" aria-label="站点导航">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <div class="topbar-actions">
        <a href="index.html">返回首页</a>
        <a href="archive.html">历史归档</a>
        <a href="feed.xml">RSS 订阅</a>
      </div>
    </nav>
    <section class="report-hero">
      <div class="report-hero-copy">
        <h1>{html.escape(display_title)}</h1>
        <p class="report-lead">{html.escape(render_report_lead(report))}</p>
      </div>
      <aside class="date-card" aria-label="报告日期">
        <p class="date-label">报告日期</p>
        <p class="date-value">{html.escape(str(report['as_of']))}</p>
        <p class="cadence-value">{html.escape(cadence_label(report))}更新</p>
      </aside>
    </section>
    {final_decisions_html}
  </main>
</body>
</html>
"""


def horizon_summary_symbols(report: dict[str, Any], horizon: str) -> list[str]:
    decisions = report.get("final_decisions", {})
    buckets = decisions.get("horizon_buckets", {}) if isinstance(decisions, dict) else {}
    primary_symbols = [str(symbol) for symbol in buckets.get(horizon, [])]
    if primary_symbols:
        return primary_symbols

    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    secondary_picks = [
        pick
        for pick in final_picks
        if pick.get("horizon_actions", {}).get(horizon) in {"recommend", "watch"}
    ]
    return [
        str(pick.get("symbol", ""))
        for pick in sorted(
            secondary_picks,
            key=lambda item: (-horizon_pick_score(item, horizon), str(item.get("symbol", ""))),
        )
        if str(pick.get("symbol", ""))
    ]


def format_horizon_summary(report: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
    return [
        (horizon, label, window, horizon_summary_symbols(report, horizon))
        for horizon, label, window in HORIZON_COLUMNS
    ]


def render_symbol_tags(symbols: list[str], *, empty_label: str = "暂无") -> str:
    if not symbols:
        return f'<span class="symbol-tag empty">{html.escape(empty_label)}</span>'
    return "".join(f'<span class="symbol-tag">{html.escape(symbol)}</span>' for symbol in symbols)


def render_horizon_snapshot(report: dict[str, Any], *, linked: bool = False) -> str:
    columns = []
    href = report_filename(report)
    for horizon, label, window, symbols in format_horizon_summary(report):
        tags = render_symbol_tags(symbols)
        body = f'<a class="horizon-link" href="{html.escape(href)}">{tags}</a>' if linked else tags
        columns.append(
            f"""
            <section class="snapshot-column snapshot-{html.escape(horizon)}">
              <p class="snapshot-label">{html.escape(label)}</p>
              <p class="snapshot-window">{html.escape(window)}</p>
              <div class="symbol-strip">{body}</div>
            </section>
            """
        )
    return f'<div class="snapshot-grid">{"".join(columns)}</div>'


def render_index_html(reports: list[dict[str, Any]], *, now: dt.datetime | None = None) -> str:
    sorted_reports = sorted(reports, key=lambda item: item["as_of"], reverse=True)
    reference_now = now or dt.datetime.now(dt.UTC)
    latest = next((item for item in sorted_reports if not is_report_expired(item, now=reference_now)), None)
    if latest is None and sorted_reports:
        latest = sorted_reports[0]
    latest_block = ""
    if latest:
        latest_filename = report_filename(latest)
        top_themes = format_theme_ids(latest["summary"].get("top_theme_ids", []))
        top_symbols = latest["summary"].get("top_recommended_symbols", [])
        latest_block = f"""
        <section class="latest-panel">
          <div class="latest-copy">
            {'<p class="eyebrow">已过期报告</p>' if is_report_expired(latest, now=reference_now) else ""}
            <h2>{html.escape(latest['as_of'])} {html.escape(cadence_label(latest))}智慧投顾研究{"（已过期）" if is_report_expired(latest, now=reference_now) else ""}</h2>
            <p class="lead">{"该报告已过期，不再作为当前公开推荐。" if is_report_expired(latest, now=reference_now) else "结合主题动量、市场确认和事件证据，生成普通投资者更容易阅读的研究结论。"}</p>
            <div class="theme-line"><span>主要信号</span>{html.escape(top_themes or '无')}</div>
            <div class="symbol-strip hero-symbols">{render_symbol_tags([str(symbol) for symbol in top_symbols])}</div>
            <a class="primary-action" href="{html.escape(latest_filename)}">打开最新报告</a>
          </div>
          {render_horizon_snapshot(latest)}
        </section>
        """
    items = []
    recent_reports = [item for item in sorted_reports if item is not latest][:INDEX_HISTORY_LIMIT]
    for report in recent_reports:
        filename = report_filename(report)
        top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
        top_symbols = [str(symbol) for symbol in report["summary"].get("top_recommended_symbols", [])]
        items.append(
            f"""
            <article class="archive-card">
              <a class="archive-title" href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(cadence_label(report))}复盘</a>
              <p>主要信号：{html.escape(top_themes or '无')}</p>
              <div class="archive-symbols">{render_symbol_tags(top_symbols)}</div>
              {render_horizon_snapshot(report, linked=True)}
            </article>
            """
        )
    archive = "".join(items) or '<p class="empty-archive">暂无更多历史报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>智慧投顾研究系统</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>{SITE_BASE_CSS}{INDEX_PAGE_CSS}  </style>
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <nav class="site-nav" aria-label="站点导航">
        <a href="archive.html">历史归档</a>
        <a href="feed.xml">RSS 订阅</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero">
      <div class="hero-copy">
        <h1>智慧投顾研究系统</h1>
        <p>把主题动量、市场确认和政策/新闻证据整理成普通投资者能读懂的研究结论。投资有风险，不构成投资建议。</p>
      </div>
    </section>
    {latest_block}
    <section class="archive">
      <div class="section-title">
        <div>
          <h2>近期历史报告</h2>
          <p>首页最多显示最近 {INDEX_HISTORY_LIMIT} 期，完整记录保留在归档页</p>
        </div>
        <a class="archive-action" href="archive.html">查看全部</a>
      </div>
      <div class="archive-grid">{archive}</div>
    </section>
  </main>
</body>
</html>
"""


def render_archive_card(report: dict[str, Any]) -> str:
    filename = report_filename(report)
    top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
    top_symbols = [str(symbol) for symbol in report["summary"].get("top_recommended_symbols", [])]
    return f"""
    <article class="archive-card">
      <a class="archive-title" href="{html.escape(filename)}">{html.escape(report['as_of'])} {html.escape(cadence_label(report))}复盘</a>
      <p>主要信号：{html.escape(top_themes or '无')}</p>
      <div class="archive-symbols">{render_symbol_tags(top_symbols)}</div>
      {render_horizon_snapshot(report, linked=True)}
    </article>
    """


def render_archive_html(reports: list[dict[str, Any]]) -> str:
    sorted_reports = sorted(reports, key=lambda item: item["as_of"], reverse=True)
    groups: dict[str, list[dict[str, Any]]] = {}
    for report in sorted_reports:
        key = str(report.get("as_of", ""))[:7] or "unknown"
        groups.setdefault(key, []).append(report)

    sections = []
    for key, group_reports in groups.items():
        year, _, month = key.partition("-")
        title = f"{year} 年 {month} 月" if month else key
        cards = "".join(render_archive_card(report) for report in group_reports)
        sections.append(
            f"""
            <section class="month-group">
              <h2>{html.escape(title)}</h2>
              <div class="archive-grid">{cards}</div>
            </section>
            """
        )
    archive = "".join(sections) or '<p class="empty-archive">暂无报告。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>历史归档 - 智慧投顾研究系统</title>
  <link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
  <link rel="alternate" type="application/rss+xml" title="智慧投顾研究 RSS" href="feed.xml">
  <style>{SITE_BASE_CSS}{ARCHIVE_PAGE_CSS}  </style>
</head>
<body>
  <main>
    <nav class="topbar" aria-label="站点导航">
      <a class="brand-link" href="index.html">
        {render_site_mark()}
        <span>QuantStrategyLab</span>
      </a>
      <div class="topbar-actions">
        <a href="index.html">返回首页</a>
        <a href="feed.xml">RSS 订阅</a>
      </div>
    </nav>
    <section class="hero">
      <h1>历史归档</h1>
      <p>按月份列出全部历史报告。</p>
    </section>
    {archive}
  </main>
</body>
</html>
"""


def render_reports_index_json(reports: list[dict[str, Any]]) -> str:
    items = []
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        as_of = str(report.get("as_of", ""))
        items.append(
            {
                "as_of": as_of,
                "cadence": str(report.get("cadence", "")),
                "html": report_filename(report),
                "json": f"advisory_report_{as_of}.json",
            }
        )
    return json.dumps({"schema_version": 1, "reports": items}, ensure_ascii=False, indent=2) + "\n"


def render_feed_xml(reports: list[dict[str, Any]], *, site_url: str, feed_title: str) -> str:
    channel = ET.Element("channel")
    ET.SubElement(channel, "title").text = feed_title
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = "QuantStrategyLab 智慧投顾研究系统，包含推荐理由、周期和风险提示。"
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True)[:RSS_ITEM_LIMIT]:
        filename = report_filename(report)
        link = f"{site_url.rstrip('/')}/{quote(filename)}"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{report['as_of']} {cadence_label(report)}智慧投顾研究"
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid").text = link
        ET.SubElement(item, "pubDate").text = format_datetime(report["generated_at"])
        top_symbols = ", ".join(report["summary"].get("top_recommended_symbols", []))
        top_themes = format_theme_ids(report["summary"].get("top_theme_ids", []))
        ET.SubElement(item, "description").text = (
            f"主要信号={top_themes or '无'}；系统结论={top_symbols or '无'}。"
            "智慧投顾研究输出；不包含下单、仓位配置或账户级建议。"
        )
    rss = ET.Element("rss", {"version": "2.0"})
    rss.append(channel)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


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

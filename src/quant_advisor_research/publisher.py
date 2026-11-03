from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .advisory_report import display_number, display_percent, sector_label, theme_label
from .contracts import AdvisoryValidationError, validate_advisory_report
from .time_contract import is_report_expired
from .period_contract import CanonicalPeriod, PeriodContractError, canonical_period_identity


CADENCE_LABELS_ZH = {
    "daily": "日度",
    "weekly": "周度",
    "monthly": "月度",
}
CADENCE_LABELS_EN = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
}

HORIZON_COLUMNS = (
    ("long", "长线", "1-3年"),
    ("medium", "中线", "2-12周"),
    ("short", "短线", "1-10个交易日"),
)
HORIZON_LABELS_EN = {"long": "Long", "medium": "Medium", "short": "Short"}
HORIZON_WINDOWS_I18N = {
    "long": ("1–3 年", "1–3 years"),
    "medium": ("2–12 周", "2–12 weeks"),
    "short": ("1–10 个交易日", "1–10 trading days"),
}
INDEX_HISTORY_LIMIT = 5
RSS_ITEM_LIMIT = 20
METHOD_HREF = "https://github.com/QuantStrategyLab/QuantAdvisorResearch/blob/main/docs/system-design.zh-CN.md"
RSS_TITLE = "智慧投顾研究 RSS"
MONTH_LABELS_EN = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
INPUT_CHECK_LABELS = {
    "political_events": ("政策 / 新闻事件", "Political events"),
    "political_watchlist": ("政策观察名单", "Political watchlist"),
    "ai_signal": ("AI 研究信号", "AI research signal"),
    "theme_momentum": ("主题动量快照", "Theme momentum snapshot"),
    "market_confirmation": ("市场确认", "Market confirmation"),
}
INPUT_STATUS_BADGES = {
    "available": ("b-ok", "可用", "Available"),
    "missing": ("b-bad", "缺失", "Missing"),
    "stale": ("b-warn", "过期", "Stale"),
    "invalid": ("b-bad", "无效 / 不可用", "Invalid / unavailable"),
    "unknown": ("b-unk", "未知", "Unknown"),
}
SOURCE_STATUS_BADGES = {
    "unverified": ("b-info", "未核验", "Unverified"),
    "available": ("b-ok", "可用", "Available"),
    "missing": ("b-bad", "缺失", "Missing"),
    "stale": ("b-warn", "过期", "Stale"),
    "invalid": ("b-bad", "无效 / 不可用", "Invalid / unavailable"),
    "unknown": ("b-unk", "未知", "Unknown"),
}

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
      color-scheme: light;
      --canvas: #f4f5f7;
      --surface: #ffffff;
      --surface-2: #f8f9fa;
      --ink: #14181f;
      --ink-2: #444c58;
      --ink-3: #68707d;
      --rule: #d8dce2;
      --rule-strong: #b7bec8;
      --accent: #1d3f66;
      --accent-ink: #ffffff;
      --accent-soft: #e8eef5;
      --focus: #2b6cb0;
      --ok: #2c6a4c;       --ok-bg: #eaf3ee;
      --warn: #8a5600;     --warn-bg: #fbf3e2;
      --bad: #9a2d2d;      --bad-bg: #f8eaea;
      --unk: #545c69;      --unk-bg: #eef0f3;
      --info: #35567d;     --info-bg: #ebf0f6;
      --serif: "Source Serif 4", "Source Serif Pro", "IBM Plex Serif", Georgia, "Noto Serif SC", "Songti SC", serif;
      --sans: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, "SFMono-Regular", "IBM Plex Mono", Menlo, Consolas, "Noto Sans Mono CJK SC", monospace;
      --measure: 72ch;
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --canvas: #0d1015;
      --surface: #141920;
      --surface-2: #19202a;
      --ink: #e5e8ec;
      --ink-2: #b3bac5;
      --ink-3: #8b94a2;
      --rule: #29313c;
      --rule-strong: #3c4654;
      --accent: #9dbbe0;
      --accent-ink: #0d1015;
      --accent-soft: #1b2635;
      --focus: #9dc1f0;
      --ok: #7fc4a0;       --ok-bg: #15261e;
      --warn: #e3b25c;     --warn-bg: #2a2214;
      --bad: #ec9a9a;      --bad-bg: #2d1919;
      --unk: #a9b1bd;      --unk-bg: #1c222b;
      --info: #a6c0e2;     --info-bg: #17212e;
    }
    @media (prefers-color-scheme: dark) {
      html[data-theme="auto"] {
        color-scheme: dark;
        --canvas: #0d1015; --surface: #141920; --surface-2: #19202a;
        --ink: #e5e8ec; --ink-2: #b3bac5; --ink-3: #8b94a2;
        --rule: #29313c; --rule-strong: #3c4654;
        --accent: #9dbbe0; --accent-ink: #0d1015; --accent-soft: #1b2635; --focus: #9dc1f0;
        --ok: #7fc4a0; --ok-bg: #15261e; --warn: #e3b25c; --warn-bg: #2a2214;
        --bad: #ec9a9a; --bad-bg: #2d1919; --unk: #a9b1bd; --unk-bg: #1c222b;
        --info: #a6c0e2; --info-bg: #17212e;
      }
    }
    html[data-locale="zh-CN"] [data-l="en"],
    html[data-locale="en"] [data-l="zh"] { display: none !important; }

    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0; background: var(--canvas); color: var(--ink);
      font: 15px/1.6 var(--sans); font-feature-settings: "tnum" 1;
    }
    a { color: var(--accent); text-underline-offset: 2px; }
    a:hover { text-decoration-thickness: 2px; }
    :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 2px; }
    .skip-link { position: absolute; left: 12px; top: -48px; background: var(--accent); color: var(--accent-ink);
      padding: 8px 12px; z-index: 10; text-decoration: none; font-weight: 600; }
    .skip-link:focus { top: 8px; }
    .num, time, .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: .93em; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 0 32px; }

    /* Header */
    .utility { background: var(--surface); border-bottom: 1px solid var(--rule); }
    .utility .wrap { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 56px; }
    .brand { display: flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none; }
    .brand svg { width: 26px; height: 26px; display: block; }
    .mark-plate { fill: var(--accent); } .mark-bar { fill: var(--surface); } .mark-bar-accent { fill: #4fb3a7; }
    .brand-name { font-weight: 650; letter-spacing: .01em; }
    .brand-sep { width: 1px; height: 18px; background: var(--rule-strong); }
    .brand-unit { color: var(--ink-2); font-size: 14px; }
    .controls { display: flex; gap: 10px; align-items: center; }
    .seg { display: inline-flex; border: 1px solid var(--rule-strong); border-radius: 4px; overflow: hidden; }
    .seg button { font: 500 13px/1 var(--sans); color: var(--ink-2); background: transparent; border: 0;
      padding: 7px 10px; cursor: pointer; min-height: 32px; }
    .seg button + button { border-left: 1px solid var(--rule-strong); }
    .seg button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
    .seg-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    .primary-nav { background: var(--surface); border-bottom: 1px solid var(--rule); }
    .primary-nav ul { list-style: none; display: flex; gap: 4px; margin: 0; padding: 0; }
    .primary-nav a { display: inline-block; padding: 11px 12px; color: var(--ink-2); text-decoration: none; font-size: 14px;
      border-bottom: 2px solid transparent; }
    .primary-nav a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
    .primary-nav a:hover { color: var(--ink); }
    .ext { font-size: 11px; color: var(--ink-3); margin-left: 2px; }
    .research-strip { background: var(--surface-2); border-bottom: 1px solid var(--rule); color: var(--ink-2); font-size: 12.5px; }
    .research-strip .wrap { padding-top: 7px; padding-bottom: 7px; display: flex; gap: 14px; flex-wrap: wrap; }
    .research-strip b { color: var(--ink); font-weight: 600; letter-spacing: .04em; }

    /* Page sections */
    main { padding: 28px 0 48px; }
    .overline { font: 600 12px/1.4 var(--sans); letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3); margin: 0 0 6px; }
    h1 { font: 600 30px/1.25 var(--serif); margin: 0 0 10px; letter-spacing: -.005em; }
    h2 { font: 600 19px/1.35 var(--serif); margin: 0; }
    h3 { font: 600 15px/1.4 var(--sans); margin: 0; }
    .panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; }
    .panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 16px 20px;
      border-bottom: 1px solid var(--rule); }
    .panel-head .aside { color: var(--ink-3); font-size: 13px; }
    .panel-body { padding: 18px 20px; }
    .section { margin-top: 22px; }
    .muted { color: var(--ink-2); }
    .small { font-size: 13px; }
    .lead { font-size: 16px; line-height: 1.7; color: var(--ink); max-width: var(--measure); margin: 0; }

    /* Key facts grid */
    .facts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 0; border-top: 1px solid var(--rule); }
    .facts div { padding: 12px 20px; border-right: 1px solid var(--rule); }
    .facts div:last-child { border-right: 0; }
    .facts dt { font-size: 12px; color: var(--ink-3); letter-spacing: .02em; }
    .facts dd { margin: 3px 0 0; font-size: 14px; color: var(--ink); }

    /* Status badges: always text + glyph, never colour alone */
    .badge { display: inline-flex; align-items: center; gap: 6px; font: 600 12px/1 var(--sans); letter-spacing: .02em;
      padding: 5px 8px; border-radius: 3px; border: 1px solid currentColor; white-space: nowrap; }
    .facts .badge { white-space: normal; line-height: 1.3; padding-block: 3.2px; min-height: 24px; }
    .badge::before { content: ""; width: 7px; height: 7px; display: inline-block; flex: none; }
    .b-ok { color: var(--ok); background: var(--ok-bg); } .b-ok::before { background: currentColor; border-radius: 50%; }
    .b-warn { color: var(--warn); background: var(--warn-bg); } .b-warn::before { border: 1.5px solid currentColor; transform: rotate(45deg); width: 6px; height: 6px; }
    .b-bad { color: var(--bad); background: var(--bad-bg); } .b-bad::before { background: currentColor; width: 8px; height: 2px; }
    .b-unk { color: var(--unk); background: var(--unk-bg); } .b-unk::before { border: 1.5px dashed currentColor; border-radius: 50%; }
    .b-info { color: var(--info); background: var(--info-bg); } .b-info::before { border: 1.5px solid currentColor; border-radius: 50%; }

    /* Notices */
    .notice { border: 1px solid var(--rule); border-left: 4px solid var(--unk); background: var(--surface); padding: 12px 16px;
      border-radius: 2px; margin: 0 0 18px; }
    .notice p { margin: 0; } .notice p + p { margin-top: 4px; }
    .notice strong { font-weight: 650; }
    .n-warn { border-left-color: var(--warn); background: var(--warn-bg); }
    .n-bad { border-left-color: var(--bad); background: var(--bad-bg); }
    .n-info { border-left-color: var(--info); background: var(--info-bg); }
    .n-ok { border-left-color: var(--ok); background: var(--ok-bg); }

    /* Horizon conclusions table */
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; vertical-align: top; padding: 11px 14px; border-bottom: 1px solid var(--rule); }
    thead th { font: 600 12px/1.3 var(--sans); color: var(--ink-3); letter-spacing: .04em; background: var(--surface-2); }
    tbody tr:last-child td, tbody tr:last-child th { border-bottom: 0; }
    td.num, th.num { text-align: right; white-space: nowrap; }
    .hz-name { font-weight: 650; }
    .hz-window { color: var(--ink-3); font-size: 13px; display: block; }
    .sym { font: 600 13.5px/1 var(--mono); padding: 4px 7px; border: 1px solid var(--rule-strong); border-radius: 3px;
      display: inline-block; margin: 0 6px 6px 0; color: var(--ink); background: var(--surface-2); }
    .none { color: var(--ink-2); }
    .reason { display: block; color: var(--ink-3); font-size: 13px; margin-top: 2px; }
    .gate { color: var(--ink-3); }
    .footnote { color: var(--ink-3); font-size: 12.5px; padding: 10px 20px 14px; margin: 0; border-top: 1px solid var(--rule); }

    /* Actions */
    .actions { display: flex; gap: 12px; align-items: center; padding: 14px 20px; border-top: 1px solid var(--rule); flex-wrap: wrap; }
    .btn { display: inline-flex; align-items: center; gap: 8px; background: var(--accent); color: var(--accent-ink);
      text-decoration: none; padding: 9px 14px; border-radius: 3px; font-weight: 600; font-size: 14px; min-height: 40px; }
    .btn-ghost { background: transparent; color: var(--accent); border: 1px solid var(--rule-strong); }
    .check-summary { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .disclaimer { font-size: 13.5px; color: var(--ink-2); max-width: var(--measure); }
    .disclaimer p { margin: 0 0 8px; }

    /* Footer */
    footer { border-top: 1px solid var(--rule); background: var(--surface); color: var(--ink-2); font-size: 13px; }
    footer .wrap { padding-top: 22px; padding-bottom: 28px; display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 24px; }
    footer p { margin: 0 0 6px; }
    footer ul { list-style: none; margin: 0; padding: 0; }
    footer li { margin-bottom: 4px; }
"""

SITE_RESPONSIVE_CSS = """
    @media (max-width: 960px) {
      .home-grid, .report-grid { grid-template-columns: minmax(0, 1fr); }
      .toc { position: static; }
      .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .facts div { border-bottom: 1px solid var(--rule); }
    }
    @media (max-width: 640px) {
      body { font-size: 15px; }
      .wrap { padding: 0 16px; }
      h1 { font-size: 24px; }
      .utility .wrap { flex-wrap: wrap; padding-top: 10px; padding-bottom: 10px; }
      .brand-unit, .brand-sep { display: none; }
      .primary-nav ul { overflow-x: auto; }
      .primary-nav a { padding: 11px 10px; }
      .panel-head, .panel-body { padding-left: 16px; padding-right: 16px; }
      .panel-head { flex-direction: column; align-items: flex-start; gap: 4px; }
      .facts div { padding: 10px 16px; }
      .cols { grid-template-columns: minmax(0, 1fr); }
      .col { border-right: 0; border-bottom: 1px solid var(--rule); }
      .col:last-child { border-bottom: 0; }
      .toc { display: none; }
      table.stack thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
      table.stack, table.stack tbody, table.stack tr, table.stack td, table.stack th { display: block; width: 100%; }
      table.stack tr { border-bottom: 1px solid var(--rule); padding: 8px 0; }
      table.stack tbody tr:last-child { border-bottom: 0; }
      table.stack td, table.stack th { border: 0; padding: 4px 16px; text-align: left; }
      table.stack td[data-h]::before { content: attr(data-h); display: block; font-size: 11.5px; color: var(--ink-3); letter-spacing: .03em; }
      html[data-locale="en"] table.stack td[data-h-en]::before { content: attr(data-h-en); }
      td.num { text-align: left; }
      footer .wrap { grid-template-columns: minmax(0, 1fr); }
      .actions .btn { width: 100%; justify-content: center; }
    }
    @media print {
      .utility .controls, .primary-nav, .skip-link, .toc { display: none; }
      body { background: #fff; }
    }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

REPORT_PAGE_CSS = """
    .crumbs { font-size: 13px; color: var(--ink-3); margin: 0 0 14px; }
    .crumbs a { color: var(--ink-2); }
    .toc { position: sticky; top: 16px; font-size: 13.5px; }
    .toc ol { margin: 0; padding: 14px 20px 14px 36px; }
    .toc li { margin: 4px 0; }
    .report-grid { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 22px; align-items: start; }
    .cols { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .col { border-right: 1px solid var(--rule); min-width: 0; }
    .col:last-child { border-right: 0; }
    .col-head { padding: 14px 18px; border-bottom: 1px solid var(--rule); background: var(--surface-2); }
    .col-head .scoreline { margin-top: 6px; font-size: 12.5px; color: var(--ink-3); }
    .col-body { padding: 4px 18px 16px; }
    .pick { padding: 14px 0; border-bottom: 1px solid var(--rule); }
    .pick:last-child { border-bottom: 0; }
    .pick-head { display: flex; align-items: baseline; gap: 10px; }
    .rank { font: 600 12px/1 var(--mono); color: var(--ink-3); }
    .pick-sym { font: 650 16px/1.2 var(--mono); }
    .pick-name { color: var(--ink-2); font-size: 13.5px; margin: 2px 0 8px; }
    .pick dl { margin: 0; }
    .pick dt { font-size: 12px; color: var(--ink-3); margin-top: 8px; }
    .pick dd { margin: 2px 0 0; font-size: 14px; }
    .srclang { display: inline-block; font-size: 11.5px; color: var(--ink-3); border: 1px solid var(--rule); border-radius: 2px;
      padding: 1px 5px; margin-bottom: 4px; }
    .empty-col { color: var(--ink-2); padding: 16px 0; margin: 0; }
    .status-cell { white-space: nowrap; }
    code, .code { font-family: var(--mono); font-size: 12.5px; color: var(--ink-2); word-break: break-word; }
    .src-url { font-family: var(--mono); font-size: 13px; word-break: break-all; }
    .legend { display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 20px; border-top: 1px solid var(--rule); align-items: center; }
"""

INDEX_PAGE_CSS = """
    .home-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 22px; align-items: start; }
    .recent table td { padding: 10px 16px; }
    .recent a.rowlink { text-decoration: none; color: var(--ink); font-family: var(--mono); }
    .recent a.rowlink:hover { text-decoration: underline; }
"""

ARCHIVE_PAGE_CSS = """
    .month { margin-top: 22px; }
    .month h2 { display: flex; align-items: baseline; gap: 10px; }
    .month h2 .count { font: 500 13px/1 var(--sans); color: var(--ink-3); }
    .arch td { font-size: 14px; }
    .hz-mini { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; font-size: 13px; }
    .hz-mini > span:nth-child(odd) { color: var(--ink-3); }
"""

SITE_SCRIPT_JS = """
(function () {
  var root = document.documentElement;
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  var locale = store("qar.locale") || (/^en(?:-|$)/i.test(navigator.language || "") ? "en" : "zh-CN");
  var theme = store("qar.theme") || "auto";
  if (locale !== "en") locale = "zh-CN";
  if (["auto", "light", "dark"].indexOf(theme) < 0) theme = "auto";

  function apply() {
    root.setAttribute("data-locale", locale);
    root.setAttribute("lang", locale);
    root.setAttribute("data-theme", theme);
    var key = locale === "en" ? "en" : "zh";
    var t = root.getAttribute("data-title-" + key); if (t) document.title = t;
    document.querySelectorAll("[data-aria-zh]").forEach(function (el) {
      el.setAttribute("aria-label", el.getAttribute("data-aria-" + key));
    });
    document.querySelectorAll("[data-set-locale]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-locale") === locale));
    });
    document.querySelectorAll("[data-set-theme]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-theme") === theme));
    });
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-set-locale],[data-set-theme]");
    if (!b) return;
    if (b.hasAttribute("data-set-locale")) { locale = b.getAttribute("data-set-locale"); store("qar.locale", locale); }
    else { theme = b.getAttribute("data-set-theme"); store("qar.theme", theme); }
    apply();
  });
  apply();
  document.querySelectorAll(".controls[hidden]").forEach(function (c) { c.hidden = false; });

  /* Static text states the expiry instant; refresh status and notices on home and report pages. */
  function updateExpiry() {
  var now = Date.now();
  document.querySelectorAll("[data-expires]").forEach(function (el) {
    var exp = Date.parse(el.getAttribute("data-expires"));
    if (isNaN(exp)) return;
    var expired = now > exp;
    document.querySelectorAll("[data-when-expired]").forEach(function (n) { n.hidden = !expired; });
    document.querySelectorAll("[data-when-current]").forEach(function (n) { n.hidden = expired; });
  });
  }
  updateExpiry();
  window.setInterval(updateExpiry, 1000);
  document.addEventListener("visibilitychange", updateExpiry);
})();
"""


def _t(zh: str, en: str) -> str:
    return (
        f'<span data-l="zh" lang="zh-CN">{html.escape(zh)}</span>'
        f'<span data-l="en" lang="en">{html.escape(en)}</span>'
    )


def _status_badge(badge_class: str, zh: str, en: str) -> str:
    return f'<span class="badge {badge_class}">{_t(zh, en)}</span>'


def _input_status_badge(status: Any) -> str:
    badge_class, zh, en = INPUT_STATUS_BADGES.get(str(status), ("b-unk", "未知", "Unknown"))
    return _status_badge(badge_class, zh, en)


def _source_status_badge(status: Any) -> str:
    badge_class, zh, en = SOURCE_STATUS_BADGES.get(str(status), ("b-unk", "未知", "Unknown"))
    return _status_badge(badge_class, zh, en)


def _format_utc_minute(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _iso_date(value: Any) -> str:
    text = str(value or "")
    try:
        return dt.datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text


def _score_text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return f"{number:.2f}"


def _cadence_en(report: dict[str, Any]) -> str:
    cadence = str(report.get("cadence", ""))
    return CADENCE_LABELS_EN.get(cadence, cadence.title() or cadence)


def _pluck(report: dict[str, Any], key: str) -> list[Any]:
    value = report.get(key)
    return value if isinstance(value, list) else []


def _none_label(zh: str, en: str) -> str:
    return f'<span class="none">{_t(zh, en)}</span>'


def _source_lang_tag() -> str:
    return '<span class="srclang" data-l="en" lang="en">Source text in Chinese</span>'


def _facts_strip(report: dict[str, Any], *, status_html: str) -> str:
    as_of = html.escape(str(report.get("as_of", "")))
    generated = _format_utc_minute(report.get("generated_at"))
    expires = _format_utc_minute(report.get("expires_at"))
    generated_html = f'<span class="num">{html.escape(generated)}</span>' if generated else _none_label("未记录", "Not recorded")
    expires_html = (
        f'<span class="num">{html.escape(expires)}</span>'
        if expires
        else _none_label("未记录（旧版报告）", "Not recorded (legacy report)")
    )
    return f"""<dl class="facts">
      <div><dt>{_t("报告日期", "Report date")}</dt><dd><time datetime="{as_of}">{as_of}</time></dd></div>
      <div><dt>{_t("频率", "Cadence")}</dt><dd>{_t(cadence_label(report), _cadence_en(report))}</dd></div>
      <div><dt>{_t("生成时间", "Generated")}</dt><dd>{generated_html}</dd></div>
      <div><dt>{_t("有效期至", "Valid until")}</dt><dd>{expires_html}</dd></div>
      <div><dt>{_t("状态", "Status")}</dt><dd>{status_html}</dd></div>
    </dl>"""


def _page_chrome(*, title_zh: str, title_en: str, page_css: str, content: str, active: str = "") -> str:
    def nav_link(href: str, zh: str, en: str, key: str = "", external: bool = False) -> str:
        current = ' aria-current="page"' if key and key == active else ""
        ext = '<span class="ext" aria-hidden="true">↗</span>' if external else ""
        return f'<li><a href="{href}"{current}>{_t(zh, en)}{ext}</a></li>'

    nav = "".join(
        [
            nav_link("index.html", "最新", "Latest", key="index"),
            nav_link("archive.html", "归档", "Archive", key="archive"),
            nav_link(METHOD_HREF, "方法说明", "Method", external=True),
            '<li><a href="feed.xml">RSS</a></li>',
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN" data-locale="zh-CN" data-theme="auto" data-title-zh="{html.escape(title_zh)}" data-title-en="{html.escape(title_en)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title_zh)}</title>
<link rel="icon" type="image/svg+xml" href="{SITE_ICON_FILENAME}">
<link rel="alternate" type="application/rss+xml" title="{html.escape(RSS_TITLE)}" href="feed.xml">
<style>{SITE_BASE_CSS}{page_css}{SITE_RESPONSIVE_CSS}</style>
</head>
<body>
<a class="skip-link" href="#content">{_t("跳至正文", "Skip to content")}</a>
<header>
  <div class="utility"><div class="wrap">
    <a class="brand" href="index.html">
      {render_site_mark()}
      <span class="brand-name">QuantStrategyLab</span><span class="brand-sep"></span>
      <span class="brand-unit">{_t("智慧投顾研究", "Advisory Research")}</span>
    </a>
    <div class="controls" hidden>
      <div class="seg" role="group" data-aria-zh="语言" data-aria-en="Language" aria-label="语言">
        <button type="button" data-set-locale="zh-CN" lang="zh-CN">中文</button><button type="button" data-set-locale="en" lang="en">EN</button>
      </div>
      <div class="seg" role="group" data-aria-zh="显示主题" data-aria-en="Colour theme" aria-label="显示主题">
        <button type="button" data-set-theme="auto">{_t("自动", "Auto")}</button><button type="button" data-set-theme="light">{_t("浅色", "Light")}</button><button type="button" data-set-theme="dark">{_t("深色", "Dark")}</button>
      </div>
    </div>
  </div></div>
  <nav class="primary-nav" data-aria-zh="站点导航" data-aria-en="Site navigation" aria-label="站点导航"><div class="wrap"><ul>{nav}</ul></div></nav>
  <div class="research-strip"><div class="wrap">
    <span><b>{_t("仅供研究", "RESEARCH ONLY")}</b></span>
    <span>{_t("非个性化模型研究输出，不构成投资建议，不提供交易或账户服务。", "Non-personalised model research output. Not investment advice. No trading or account services.")}</span>
  </div></div>
</header>
<main id="content" tabindex="-1"><div class="wrap">
{content}
</div></main>
<footer><div class="wrap">
  <div class="disclaimer" id="disclaimer">
    <p><strong>{_t("免责声明", "Disclaimer")}</strong></p>
    <p>{_t("投资有风险。本站内容为模型研究输出，面向公众、非个性化，不构成投资建议、要约或任何收益承诺。过往研究结论不代表未来表现。", "Investing involves risk. Content on this site is model research output for a general audience. It is not personalised, and it is not investment advice, an offer, or a promise of returns. Past research conclusions do not indicate future results.")}</p>
    <p>{_t("报告在有效期后不再作为当前结论；历史报告仅供查阅。", "A report is no longer a current conclusion after its expiry time; past reports are kept for reference only.")}</p>
  </div>
  <ul>
    <li><a href="index.html">{_t("最新报告", "Latest report")}</a></li>
    <li><a href="archive.html">{_t("历史归档", "Archive")}</a></li>
    <li><a href="{METHOD_HREF}">{_t("方法说明（系统设计文档，中文）", "Method (system design document, in Chinese)")}</a></li>
    <li><a href="feed.xml">{_t("RSS 订阅", "RSS feed")}</a></li>
  </ul>
</div></footer>
<script>{SITE_SCRIPT_JS}</script>
</body>
</html>
"""


def render_site_mark() -> str:
    return (
        '<svg class="site-mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
        '<rect class="mark-plate" x="4" y="4" width="56" height="56" rx="12"/>'
        '<rect class="mark-bar" x="15" y="17" width="34" height="7" rx="1.5"/>'
        '<rect class="mark-bar" x="15" y="29" width="24" height="7" rx="1.5"/>'
        '<rect class="mark-bar-accent" x="15" y="41" width="14" height="7" rx="1.5"/>'
        "</svg>"
    )


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
    symbol = str(pick.get("symbol", ""))
    anchor = f"p-{horizon}-{slug(symbol)}"
    source_tag = _source_lang_tag()
    return f"""
    <article class="pick" aria-labelledby="{anchor}">
      <div class="pick-head"><span class="rank">{_t(f"推荐 #{rank}", f"Pick #{rank}")}</span><h3 class="pick-sym" id="{anchor}">{html.escape(symbol)}</h3></div>
      <p class="pick-name" lang="zh-CN">{html.escape(str(pick.get("name", "")))}</p>
      <dl>
        <dt>{_t("公司背景", "Background")}</dt><dd>{source_tag}<span lang="zh-CN" style="display:block">{html.escape(str(pick.get("business_summary", "")))}</span></dd>
        <dt>{_t("推荐理由", "Rationale")}</dt><dd>{source_tag}<span lang="zh-CN" style="display:block">{html.escape(str(pick.get("prospect_summary", "")))}</span></dd>
        <dt>{_t("主要风险", "Key risks")}</dt><dd>{source_tag}<span lang="zh-CN" style="display:block">{html.escape(str(pick.get("risk_summary", "")))}</span></dd>
      </dl>
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
        return "整体看，当前结论更偏中长线，短线暂不强调。"
    if has_medium:
        return "整体看，当前结论更偏中线，短线暂不强调，后续重点观察趋势能否延续和基本面兑现。"
    if has_long:
        return "整体看，当前信号更偏长线观察，短线和中线暂未形成稳定排序。"
    if has_short:
        return "整体看，当前只出现短线机会，持续性仍需要后续数据确认。"
    return "整体看，当前暂未形成稳定系统结论。"


def format_horizon_conclusion_en(report: dict[str, Any]) -> str:
    parts = []
    for horizon, _label, _window in HORIZON_COLUMNS:
        symbols = displayed_horizon_symbols(report, horizon)
        if symbols:
            visible = ", ".join(symbols[:5]) + ("…" if len(symbols) > 5 else "")
        else:
            visible = "no stable conclusion"
        parts.append(f"{HORIZON_LABELS_EN[horizon]}: {visible}")
    return "; ".join(parts)


def format_report_takeaway_en(report: dict[str, Any]) -> str:
    has_long = bool(displayed_horizon_symbols(report, "long"))
    has_medium = bool(displayed_horizon_symbols(report, "medium"))
    has_short = bool(displayed_horizon_symbols(report, "short"))
    if has_long and has_medium and has_short:
        return "Overall, the conclusions show cross-horizon alignment; watch whether the trend persists and how risk events evolve."
    if has_long and has_medium:
        return "Overall, conclusions lean medium-to-long term; the short horizon is not emphasised."
    if has_medium:
        return "Overall, conclusions lean medium term; the short horizon is not emphasised."
    if has_long:
        return "Overall, the signal leans long term; no stable short- or medium-term ranking has formed."
    if has_short:
        return "Overall, only a short-term opportunity appears; persistence still needs confirmation from later data."
    return "Overall, the system has not formed a stable conclusion this period."


def render_report_lead(report: dict[str, Any]) -> str:
    return f"本期结论：{format_horizon_conclusion(report)}。{format_report_takeaway(report)}"


def render_report_lead_en(report: dict[str, Any]) -> str:
    return f"This period: {format_horizon_conclusion_en(report)}. {format_report_takeaway_en(report)}"


def _horizon_summary_html(report: dict[str, Any], horizon: str) -> str | None:
    decisions = report.get("final_decisions", {})
    summary = decisions.get("horizon_summary") if isinstance(decisions, dict) else None
    if not isinstance(summary, dict):
        return None
    entry = summary.get(horizon)
    entry = entry if isinstance(entry, dict) else {}
    max_text = _score_text(entry.get("max_score"))
    max_html = f'<span class="num">{html.escape(max_text)}</span>' if max_text else _t("未评估", "Not evaluated")
    threshold = _score_text(entry.get("threshold"))
    if not threshold:
        return max_html
    gate = f'<span class="gate">/ {_t("门槛", "gate")} <span class="num">{html.escape(threshold)}</span></span>'
    return f"{max_html} {gate}"


def render_final_decisions_html(report: dict[str, Any]) -> str:
    decisions = report.get("final_decisions", {})
    if not isinstance(decisions, dict) or not decisions:
        return ""
    final_picks = [pick for pick in decisions.get("recommendations", []) if isinstance(pick, dict)]
    summary = decisions.get("horizon_summary")
    has_summary = isinstance(summary, dict)
    columns = []
    for horizon, label, _window in HORIZON_COLUMNS:
        cards = "".join(
            render_final_card(pick, rank=index, horizon=horizon)
            for index, pick in enumerate(ranked_horizon_picks(final_picks, horizon), start=1)
        )
        if not cards:
            if index_threshold_unmet(report, horizon):
                reason = _t("候选未达到推荐门槛。", "Candidates did not meet the gate.")
            elif index_inputs_verified(report):
                reason = _t("本期未产生推荐。", "No recommendation was produced this period.")
            else:
                reason = _t("输入不完整，见下方输入状态。", "Inputs incomplete; see input status below.")
            cards = (
                f'<p class="empty-col">{_t("本期无推荐", "No recommendation this period")}'
                f'<span class="reason">{reason}</span></p>'
            )
        scoreline = ""
        if has_summary:
            score = _horizon_summary_html(report, horizon)
            scoreline = f'<div class="scoreline">{_t("最高分：", "Max score: ")}{score}</div>'
        zh_window, en_window = HORIZON_WINDOWS_I18N[horizon]
        columns.append(
            f"""
        <section class="col" aria-labelledby="h-{horizon}">
          <div class="col-head"><h3 id="h-{horizon}">{_t(label, HORIZON_LABELS_EN[horizon])} <span class="hz-window" style="display:inline">· {_t(zh_window, en_window)}</span></h3>{scoreline}</div>
          <div class="col-body">{cards}</div>
        </section>"""
        )
    footnote = ""
    if has_summary:
        footnote = (
            f'<p class="footnote">{_t("分数达到门槛本身不构成推荐。“未评估”不等于 0。", "Meeting the score gate alone is not a recommendation. “Not evaluated” is not zero.")}</p>'
        )
    return f"""
    <section class="panel section" id="conclusions" aria-labelledby="conclusions-h">
      <div class="panel-head"><h2 id="conclusions-h">{_t("按周期的最终结论", "Final conclusions by horizon")}</h2>
        <span class="aside">{_t("仅列出最终公开推荐；观察名单与溢出候选不在此列", "Final public picks only; watchlist and overflow candidates are excluded")}</span></div>
      <div class="cols">{''.join(columns)}</div>
      {footnote}
    </section>
    """


def _input_checks_section(report: dict[str, Any]) -> str:
    if not isinstance(report.get("input_checks"), list):
        return ""
    rows = []
    for check in report["input_checks"]:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name", ""))
        label_zh, label_en = INPUT_CHECK_LABELS.get(name, (name, name))
        as_of = _iso_date(check.get("as_of")) if check.get("as_of") else ""
        date_html = (
            f'<time datetime="{html.escape(as_of)}">{html.escape(as_of)}</time>'
            if as_of
            else _none_label("未记录", "Not recorded")
        )
        detail = str(check.get("detail") or "")
        detail_html = f"<code>{html.escape(detail)}</code>" if detail else ""
        rows.append(
            "<tr>"
            f'<th scope="row" data-h="输入" data-h-en="Input"><span>{_t(label_zh, label_en)}</span> <code>{html.escape(name)}</code></th>'
            f'<td class="status-cell" data-h="状态" data-h-en="Status">{_input_status_badge(check.get("status"))}</td>'
            f'<td data-h="数据日期" data-h-en="Data as of">{date_html}</td>'
            f'<td data-h="说明（来源原文）" data-h-en="Detail (source code)">{detail_html}</td>'
            "</tr>"
        )
    return f"""
        <section class="panel section" id="inputs" aria-labelledby="inputs-h">
          <div class="panel-head"><h2 id="inputs-h">{_t("输入状态", "Input status")}</h2></div>
          <table class="stack"><thead><tr><th scope="col">{_t("输入", "Input")}</th><th scope="col">{_t("状态", "Status")}</th><th scope="col">{_t("数据日期", "Data as of")}</th><th scope="col">{_t("说明", "Detail")}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
          <div class="legend small muted">{_t("“可用”对 CSV 输入表示已成功解析，不代表已核验新鲜度。未记录的日期不会用报告日期代替。", "“Available” for CSV inputs means parsed, not freshness-verified. Unrecorded dates are never replaced with the report date.")}</div>
        </section>"""


def _source_href(url: str) -> str:
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:
        return ""
    return html.escape(url) if scheme in {"http", "https"} else ""


def _sources_section(report: dict[str, Any]) -> str:
    if not isinstance(report.get("sources"), list):
        return ""
    rows = []
    for source in report["sources"]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        href = _source_href(url)
        if href:
            link_html = f'<a class="src-url" href="{href}" rel="nofollow noopener noreferrer">{html.escape(url)}</a>'
        else:
            link_html = f'<span class="src-url">{html.escape(url)}</span>'
        fetched = _format_utc_minute(source.get("fetched_at"))
        fetched_html = (
            f'<span class="num">{html.escape(fetched)}</span>'
            if fetched
            else _none_label("未抓取", "Not fetched")
        )
        rows.append(
            "<tr>"
            f'<td data-h="链接" data-h-en="Link">{link_html}</td>'
            f'<td data-h="类型" data-h-en="Type"><code>{html.escape(str(source.get("type") or ""))}</code></td>'
            f'<td class="status-cell" data-h="状态" data-h-en="Status">{_source_status_badge(source.get("status"))}</td>'
            f'<td data-h="抓取时间" data-h-en="Fetched">{fetched_html}</td>'
            "</tr>"
        )
    if rows:
        body = (
            f'<table class="stack"><thead><tr><th scope="col">{_t("链接", "Link")}</th><th scope="col">{_t("类型", "Type")}</th>'
            f'<th scope="col">{_t("状态", "Status")}</th><th scope="col">{_t("抓取时间", "Fetched")}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )
    else:
        body = f'<div class="panel-body"><p class="muted" style="margin:0">{_t("未声明来源链接。", "No source links declared.")}</p></div>'
    return f"""
        <section class="panel section" id="sources" aria-labelledby="sources-h">
          <div class="panel-head"><h2 id="sources-h">{_t("来源链接", "Source links")}</h2></div>
          {body}
          <div class="legend small muted">{_t("链接由输入数据声明；列出链接不代表已抓取或核验其内容，也不代表穷尽全部上游证据。", "Links are declared by input data. Listing a link does not mean it was retrieved or verified, nor that the list covers all upstream evidence.")}</div>
        </section>"""


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
    as_of = str(report.get("as_of", ""))
    cadence_zh = cadence_label(report)
    cadence_en = _cadence_en(report)
    title_zh = f"智慧投顾研究{cadence_zh}复盘 - {as_of}"
    title_en = f"Advisory Research {cadence_en} Review - {as_of}"
    expires_text = str(report.get("expires_at") or "")
    expires_date = _iso_date(expires_text) if expires_text else ""
    has_inputs = isinstance(report.get("input_checks"), list)
    has_sources = isinstance(report.get("sources"), list)

    if expires_text:
        status_html = (
            f'<span data-expires="{html.escape(expires_text)}"></span>'
            f'<span class="badge b-ok" data-when-current hidden>{_t("当前有效", "Current")}</span>'
            f'<span class="badge b-warn" data-when-expired hidden>{_t("已过期", "Expired")}</span>'
            f'<noscript><span class="badge b-unk">{_t("见有效期", "See validity")}</span></noscript>'
        )
        notice = (
            '<div class="notice n-warn" role="note" data-when-expired hidden>'
            f'<p><strong>{_t("此报告已过期。", "This report has expired.")}</strong></p>'
            f'<p>{_t(f"有效期至 {expires_date}；此后不再作为当前公开结论，仅供历史查阅。", f"It was valid until {expires_date}. It is no longer a current public conclusion and is kept for reference only.")} '
            f'<a href="index.html">{_t("查看最新报告", "See the latest report")}</a></p></div>'
        )
    else:
        version = str(report.get("schema_version") or "").strip()
        version_zh = f"（v{version}）" if version else ""
        version_en = f" (v{version})" if version else ""
        status_html = _status_badge("b-unk", "有效期未记录", "Expiry not recorded")
        notice = (
            '<div class="notice" role="note">'
            f'<p><strong>{_t(f"旧版报告格式{version_zh}。", f"Legacy report format{version_en}.")}</strong></p>'
            f'<p>{_t("此报告未记录有效期、输入检查和来源列表。缺少这些字段不代表输入完整或报告仍然有效。", "This report does not record an expiry time, input checks or a source list. Their absence does not mean inputs were complete or that the report is still current.")}</p></div>'
        )

    toc_items = [
        f'<li><a href="#summary">{_t("摘要", "Summary")}</a></li>',
        f'<li><a href="#conclusions">{_t("按周期的最终结论", "Final conclusions by horizon")}</a></li>',
    ]
    if has_inputs:
        toc_items.append(f'<li><a href="#inputs">{_t("输入状态", "Input status")}</a></li>')
    if has_sources:
        toc_items.append(f'<li><a href="#sources">{_t("来源链接", "Source links")}</a></li>')
    toc_items.append(f'<li><a href="#disclaimer-sec">{_t("方法与免责声明", "Method and disclaimer")}</a></li>')

    lead_html = _t(render_report_lead(report), render_report_lead_en(report))
    contract_version = html.escape(str(report.get("contract_version", "")))
    method_link = f'<a href="{html.escape(METHOD_HREF)}">{_t("方法说明", "method documentation")}</a>'
    content = f"""
<nav class="crumbs" data-aria-zh="页面路径" data-aria-en="Breadcrumb" aria-label="页面路径"><a href="index.html">{_t("首页", "Home")}</a> / <a href="archive.html">{_t("归档", "Archive")}</a> / <span aria-current="page">{html.escape(as_of)} {_t(cadence_zh, cadence_en)}</span></nav>
<div class="report-grid">
  <nav class="panel toc" data-aria-zh="本页目录" data-aria-en="On this page" aria-label="本页目录"><div class="panel-head"><h2 style="font-size:15px">{_t("本页目录", "On this page")}</h2></div><ol>{''.join(toc_items)}</ol></nav>
  <article>
    <p class="overline">{_t(cadence_zh, cadence_en)} {_t("研究复盘", "research review")}</p>
    <h1>{_t(f"智慧投顾研究{cadence_zh}复盘", f"Advisory Research — {cadence_en} Review")}</h1>
    {notice}
    <section class="panel" id="summary" aria-labelledby="summary-h">
      <div class="panel-head" style="border-bottom:0"><h2 id="summary-h">{_t("摘要", "Summary")}</h2><span class="aside mono">{contract_version}</span></div>
      <div class="panel-body" style="padding-top:0"><p class="lead">{lead_html}</p></div>
      {_facts_strip(report, status_html=status_html)}
    </section>
    {render_final_decisions_html(report)}
    {_input_checks_section(report)}
    {_sources_section(report)}
    <section class="panel section" id="disclaimer-sec" aria-labelledby="disc-h">
      <div class="panel-head"><h2 id="disc-h">{_t("方法与免责声明", "Method and disclaimer")}</h2></div>
      <div class="panel-body disclaimer">
        <p>{_t("结论来自主题动量、市场确认与政策 / 新闻证据的模型组合，详见", "Conclusions combine theme momentum, market confirmation and policy/news evidence; see the")} {method_link}{_t("。", " (in Chinese).")}</p>
        <p>{_t("本报告为非个性化研究输出，不构成投资建议，不包含仓位、配置比例或收益承诺。", "This report is non-personalised research output. It is not investment advice and contains no position sizes, allocations or return promises.")}</p>
      </div></section>
  </article>
</div>"""
    return _page_chrome(title_zh=title_zh, title_en=title_en, page_css=REPORT_PAGE_CSS, content=content)


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
        return _none_label(empty_label, {"暂无": "None", "本期无推荐": "No recommendation"}.get(empty_label, empty_label))
    return "".join(f'<span class="sym">{html.escape(str(symbol))}</span>' for symbol in symbols)


def render_horizon_snapshot(report: dict[str, Any], *, linked: bool = False) -> str:
    rows = []
    for horizon, label, _window, symbols in format_horizon_summary(report):
        tags = " ".join(f'<span class="sym">{html.escape(str(symbol))}</span>' for symbol in symbols)
        body = tags or _none_label("暂无", "None")
        rows.append(f"<span>{_t(label, HORIZON_LABELS_EN[horizon])}</span><span>{body}</span>")
    return f'<div class="hz-mini">{"".join(rows)}</div>'


def index_inputs_verified(report: dict[str, Any]) -> bool:
    """Missing legacy/unknown freshness never proves a complete set of inputs."""
    freshness = report.get("freshness")
    return isinstance(freshness, dict) and not report.get("summary", {}).get("data_quality_warnings") and all(
        isinstance(freshness.get(name), dict)
        and freshness[name].get("present") is True
        and freshness[name].get("valid") is True
        and freshness[name].get("reason") == "fresh"
        for name in ("ai_signal", "theme_momentum")
    )


def index_threshold_unmet(report: dict[str, Any], horizon: str) -> bool:
    decisions = report.get("final_decisions", {})
    rankings = decisions.get("horizon_rankings", {}) if isinstance(decisions, dict) else {}
    candidates = rankings.get(horizon) if isinstance(rankings, dict) else None
    return index_inputs_verified(report) and isinstance(candidates, list) and bool(candidates) and all(
        isinstance(item, dict) and item.get("action") in {"watch", "skip"} for item in candidates
    )


def _home_status_badge(report: dict[str, Any]) -> str:
    expires_text = str(report.get("expires_at") or "")
    if not expires_text:
        return _status_badge("b-unk", "最新 · 有效期未记录", "Latest · expiry not recorded")
    return (
        f'<span data-expires="{html.escape(expires_text)}"></span>'
        f'<span class="badge b-ok" data-when-current hidden>{_t("当前有效", "Current")}</span>'
        f'<span class="badge b-warn" data-when-expired hidden>{_t("已过期", "Expired")}</span>'
        f'<noscript><span class="badge b-unk">{_t("见有效期", "See validity")}</span></noscript>'
    )


def _home_input_summary(report: dict[str, Any]) -> str:
    checks = report.get("input_checks")
    if isinstance(checks, list):
        counts: dict[str, int] = {}
        for check in checks:
            if isinstance(check, dict):
                status = str(check.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
        badges = []
        for status, badge_class, zh_label, en_label in (
            ("available", "b-ok", "可用", "Available"),
            ("stale", "b-warn", "过期", "Stale"),
            ("missing", "b-bad", "缺失", "Missing"),
            ("invalid", "b-bad", "无效 / 不可用", "Invalid / unavailable"),
            ("unknown", "b-unk", "未知", "Unknown"),
        ):
            count = counts.get(status, 0)
            if count:
                badges.append(_status_badge(badge_class, f"{zh_label} {count}", f"{en_label} {count}"))
        if not badges:
            return ""
        return (
            '<div class="panel-body" style="border-top:1px solid var(--rule)">'
            f'<div class="small muted">{_t("输入检查", "Input checks")}</div>'
            f'<div class="check-summary">{" ".join(badges)}</div></div>'
        )
    if not report.get("expires_at"):
        return (
            '<div class="panel-body" style="border-top:1px solid var(--rule)">'
            f'<p class="small muted" style="margin:0">{_t("输入状态未记录（旧版报告格式）；不能视为输入完整。", "Input status not recorded (legacy report format); this does not mean inputs were complete.")}</p></div>'
        )
    return ""


def render_index_horizons(report: dict[str, Any]) -> str:
    """Show final report conclusions without promoting candidates into recommendations."""
    decisions = report.get("final_decisions", {})
    summary = decisions.get("horizon_summary") if isinstance(decisions, dict) else None
    has_summary = isinstance(summary, dict)
    score_head = f'<th scope="col" class="num">{_t("最高分 / 门槛", "Max score / gate")}</th>' if has_summary else ""
    rows = []
    for horizon, label, _window in HORIZON_COLUMNS:
        symbols = displayed_horizon_symbols(report, horizon)
        if symbols:
            conclusion = render_symbol_tags(symbols)
        else:
            reason = (
                _t("候选未达到推荐门槛。", "Candidates did not meet the recommendation gate.")
                if index_threshold_unmet(report, horizon)
                else _t("原因见完整报告中的输入状态。", "See input status in the full report for the reason.")
            )
            conclusion = f'{_none_label("本期无推荐", "No recommendation this period")}<span class="reason">{reason}</span>'
        score_cell = ""
        if has_summary:
            score_cell = (
                f'<td class="num" data-h="最高分 / 门槛" data-h-en="Max score / gate">'
                f"{_horizon_summary_html(report, horizon)}</td>"
            )
        zh_window, en_window = HORIZON_WINDOWS_I18N[horizon]
        rows.append(
            f'<tr><th scope="row" data-h="周期" data-h-en="Horizon"><span class="hz-name">{_t(label, HORIZON_LABELS_EN[horizon])}</span>'
            f'<span class="hz-window">{_t(zh_window, en_window)}</span></th>'
            f'<td data-h="最终结论" data-h-en="Final conclusion">{conclusion}</td>'
            f"{score_cell}</tr>"
        )
    footnote = ""
    if has_summary:
        footnote = (
            f'<p class="footnote">{_t("最高分覆盖全部已评估候选；分数达到门槛本身不构成推荐，组件、新鲜度与市场确认门槛仍然适用。“未评估”表示本周期没有评估候选，不等于 0。", "Max score covers all evaluated candidates. Meeting the score gate alone is not a recommendation; component, freshness and market-confirmation gates still apply. “Not evaluated” means no candidate was evaluated — it is not zero.")}</p>'
        )
    return (
        f'<table class="stack"><thead><tr><th scope="col">{_t("周期", "Horizon")}</th>'
        f'<th scope="col">{_t("最终结论", "Final conclusion")}</th>{score_head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>{footnote}'
    )


def render_index_empty_conclusion(report: dict[str, Any]) -> str:
    if any(displayed_horizon_symbols(report, horizon) for horizon, _, _ in HORIZON_COLUMNS):
        return ""
    if all(index_threshold_unmet(report, horizon) for horizon, _, _ in HORIZON_COLUMNS):
        return (
            '<div class="notice n-info" role="note" style="margin:0 20px 16px">'
            f'<p><strong>{_t("本期三个周期均未产生合格推荐。", "No horizon produced a qualifying recommendation this period.")}</strong></p>'
            f'<p>{_t("输入已核验完整；空结果本身就是结论：信号未达到门槛，而不是数据缺失。", "Inputs were verified complete. The empty result is itself the conclusion: signals did not meet the gate; this is not missing data.")}</p></div>'
        )
    if not index_inputs_verified(report):
        return (
            '<div class="notice n-warn" role="note" style="margin:0 20px 16px">'
            f'<p><strong>{_t("本期三个周期均未产生合格推荐，且输入不完整。", "No horizon produced a qualifying recommendation, and inputs are incomplete.")}</strong></p>'
            f'<p>{_t("部分输入缺失、过期或不可用；此空结果不能解读为“信号未达门槛”。请查看完整报告中的输入状态。", "Some inputs are missing, stale or unavailable, so this empty result cannot be read as “signals below the gate”. See input status in the full report.")}</p></div>'
        )
    return ""


def render_index_html(reports: list[dict[str, Any]], *, now: dt.datetime | None = None) -> str:
    sorted_reports = sorted(reports, key=lambda item: item["as_of"], reverse=True)
    reference_now = now or dt.datetime.now(dt.UTC)
    latest = next((item for item in sorted_reports if not is_report_expired(item, now=reference_now)), None)
    if latest is None and sorted_reports:
        latest = sorted_reports[0]

    banner = ""
    expired = False
    if latest:
        expired = is_report_expired(latest, now=reference_now)
        if latest.get("expires_at"):
            expires_date = _iso_date(latest.get("expires_at"))
            banner = (
                '<div class="notice n-warn" role="note" data-when-expired hidden>'
                f'<p><strong>{_t("当前展示的报告已过期。", "The displayed report has expired.")}</strong></p>'
                f'<p>{_t(f"本页展示的报告已于 {expires_date} 过期，仅供历史查阅，不再作为当前公开结论。", f"The displayed report expired on {expires_date} and is kept for reference only; it is no longer a current public conclusion.")}</p></div>'
            )

    if latest:
        as_of = html.escape(str(latest.get("as_of", "")))
        cadence_zh = cadence_label(latest)
        cadence_en = _cadence_en(latest)
        overline = (
            _t("最近一期 · 已过期", "Most recent · expired")
            if expired
            else _t("最新一期", "Latest publication")
        )
        latest_block = f"""
        <section class="panel" id="latest" aria-labelledby="latest-h">
          <div class="panel-head" style="border-bottom:0;padding-bottom:6px"><div>
            <p class="overline">{overline}</p>
            <h2 id="latest-h" style="font-size:22px">{_t(cadence_zh, cadence_en)} {_t("研究复盘", "research review")} · <time datetime="{as_of}">{as_of}</time></h2>
          </div></div>
          {_facts_strip(latest, status_html=_home_status_badge(latest))}
          {render_index_horizons(latest)}
          {render_index_empty_conclusion(latest)}
          {_home_input_summary(latest)}
          <div class="actions"><a class="btn" href="{html.escape(report_filename(latest))}">{_t("阅读完整报告", "Read full report")} →</a>
            <span class="small muted">{_t("含逐项理由、风险与输入证据", "Includes rationale, risks and input evidence")}</span></div>
        </section>"""
    else:
        latest_block = (
            '<section class="panel" aria-labelledby="latest-h">'
            f'<div class="panel-head"><h2 id="latest-h">{_t("暂无已发布报告", "No reports published yet")}</h2></div>'
            f'<div class="panel-body"><p class="muted" style="margin:0">{_t("研究报告发布后会显示在这里。当前没有可展示的结论、日期或输入状态。", "Research reports will appear here once published. There are no conclusions, dates or input statuses to show.")}</p></div>'
            "</section>"
        )

    items = []
    recent_reports = [item for item in sorted_reports if item is not latest][:INDEX_HISTORY_LIMIT]
    for report in recent_reports:
        decisions = report.get("final_decisions", {})
        count = len(decisions.get("recommendations", [])) if isinstance(decisions, dict) else 0
        count_en = f"{count} pick" if count == 1 else f"{count} picks"
        report_as_of = html.escape(str(report.get("as_of", "")))
        items.append(
            f'<tr class="recent-report"><td data-h="日期" data-h-en="Date">'
            f'<a class="rowlink" href="{html.escape(report_filename(report))}"><time datetime="{report_as_of}">{report_as_of}</time></a></td>'
            f'<td data-h="频率" data-h-en="Cadence">{_t(cadence_label(report), _cadence_en(report))}</td>'
            f'<td class="num" data-h="公开推荐" data-h-en="Public picks">{_t(f"{count} 项推荐", count_en)}</td></tr>'
        )
    if items:
        recent_body = (
            f'<table class="stack"><thead><tr><th scope="col">{_t("日期", "Date")}</th>'
            f'<th scope="col">{_t("频率", "Cadence")}</th>'
            f'<th scope="col" class="num">{_t("公开推荐", "Public picks")}</th></tr></thead>'
            f'<tbody>{"".join(items)}</tbody></table>'
        )
    else:
        recent_body = (
            f'<div class="panel-body"><p class="muted small" style="margin:0">{_t("暂无更多历史报告。", "No earlier reports.")}</p></div>'
        )

    content = f"""
<p class="overline">{_t("研究简报", "Research briefing")}</p>
<h1>{_t("智慧投顾研究", "Advisory Research")}</h1>
<p class="lead muted" style="margin-bottom:22px">{_t("将主题动量、市场确认与政策 / 新闻证据整理为按周期划分的研究结论。所有结论为非个性化研究输出。", "Theme momentum, market confirmation and policy/news evidence, organised into research conclusions by horizon. All conclusions are non-personalised research output.")}</p>
{banner}<div class="home-grid">{latest_block}<aside class="panel recent" aria-labelledby="recent-h">
      <div class="panel-head"><h2 id="recent-h">{_t("近期报告", "Recent reports")}</h2></div>
      {recent_body}
      <div class="actions"><a class="btn btn-ghost" href="archive.html">{_t("查看全部归档", "View full archive")} →</a></div>
    </aside></div>"""
    return _page_chrome(
        title_zh="智慧投顾研究系统",
        title_en="Advisory Research",
        page_css=INDEX_PAGE_CSS,
        content=content,
        active="index",
    )


def render_archive_card(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    signals = format_theme_ids(summary.get("top_theme_ids", []))
    signals_html = _none_label("无", "None") if signals == "无" else f"<span>{html.escape(signals)}</span>"
    top_symbols = [str(symbol) for symbol in summary.get("top_recommended_symbols", []) if str(symbol).strip()]
    as_of = html.escape(str(report.get("as_of", "")))
    return f"""
    <tr class="arch-row"><td data-h="日期" data-h-en="Date"><a class="mono" href="{html.escape(report_filename(report))}"><time datetime="{as_of}">{as_of}</time></a></td>
      <td data-h="频率" data-h-en="Cadence">{_t(cadence_label(report), _cadence_en(report))}</td>
      <td data-h="主要信号" data-h-en="Main signals">{signals_html}</td>
      <td data-h="推荐标的" data-h-en="Recommended symbols">{render_symbol_tags(top_symbols, empty_label="本期无推荐")}</td>
      <td data-h="周期结论" data-h-en="By horizon">{render_horizon_snapshot(report)}</td></tr>
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
        try:
            month_number = int(month)
            title_zh = f"{year} 年 {month_number} 月"
            title_en = f"{MONTH_LABELS_EN[month_number]} {year}"
        except (ValueError, IndexError):
            title_zh = key
            title_en = key
        count = len(group_reports)
        count_en = f"{count} report" if count == 1 else f"{count} reports"
        rows = "".join(render_archive_card(report) for report in group_reports)
        sections.append(
            f"""
      <section class="month" aria-labelledby="m-{html.escape(key)}"><h2 id="m-{html.escape(key)}">{_t(title_zh, title_en)} <span class="count">{_t(f"{count} 份", count_en)}</span></h2>
          <div class="panel section" style="margin-top:10px"><table class="stack arch"><thead><tr><th scope="col">{_t("日期", "Date")}</th><th scope="col">{_t("频率", "Cadence")}</th><th scope="col">{_t("主要信号", "Main signals")}</th><th scope="col">{_t("推荐标的", "Recommended symbols")}</th><th scope="col">{_t("周期结论", "By horizon")}</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""
        )
    if sections:
        total = len(sorted_reports)
        total_en = f"{total} report" if total == 1 else f"{total} reports"
        total_html = f'<p class="small muted">{_t(f"共 {total} 份报告", total_en)}</p>'
        archive = total_html + "".join(sections)
    else:
        archive = (
            '<section class="panel section"><div class="panel-body">'
            f'<h2>{_t("暂无报告", "No reports yet")}</h2>'
            f'<p class="muted" style="margin:6px 0 0">{_t("报告发布后会按月份列在这里。", "Reports will be listed here by month once published.")}</p>'
            "</div></section>"
        )
    content = f"""
<p class="overline">{_t("全部已发布报告", "All published reports")}</p><h1>{_t("历史归档", "Archive")}</h1>
      <p class="lead muted" style="margin-bottom:6px">{_t("按月份列出全部已发布报告，最新在前。没有报告的月份不会显示。", "All published reports by month, newest first. Months without reports are not shown.")}</p>{archive}"""
    return _page_chrome(
        title_zh="历史归档 - 智慧投顾研究系统",
        title_en="Archive - Advisory Research",
        page_css=ARCHIVE_PAGE_CSS,
        content=content,
        active="archive",
    )


def render_reports_index_json(reports: list[dict[str, Any]]) -> str:
    items = []
    for report in sorted(reports, key=lambda item: item["as_of"], reverse=True):
        as_of = str(report.get("as_of", ""))
        decisions = report.get("final_decisions")
        picks = decisions.get("recommendations", []) if isinstance(decisions, dict) else [
            item for item in report.get("recommendations", []) if item.get("rating") == "recommend"
        ]
        horizon_counts = {
            horizon: sum(pick.get("primary_horizon") == horizon for pick in picks)
            for horizon in ("short", "medium", "long")
        }
        items.append(
            {
                "as_of": as_of,
                "cadence": str(report.get("cadence", "")),
                "html": report_filename(report),
                "json": f"advisory_report_{as_of}.json",
                "recommendation_count": len(picks),
                "horizon_counts": horizon_counts,
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

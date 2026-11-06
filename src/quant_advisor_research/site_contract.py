"""Versioned JSON publication artifacts for the static advisory site.

The module projects already-selected advisory reports into the presentation-neutral
``data/v1`` bundle consumed by the frontend. It does not render HTML, RSS, CSS or
browser behavior, and it is not wired into the production publication entry point.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .advisory_report import theme_label
from .contracts import AdvisoryValidationError, validate_advisory_report
from .publisher import (
    cadence_label,
    displayed_horizon_symbols,
    format_horizon_conclusion,
    format_momentum_factor_summary,
    format_report_takeaway,
    format_theme_ids,
    horizon_display_meta,
    horizon_summary_symbols,
    index_inputs_verified,
    index_threshold_unmet,
    is_report_expired,
    load_report,
    ranked_horizon_picks,
    require_publish_candidates,
)
from .time_contract import TimeContractError, normalize_aware_datetime


CONTRACT_VERSION = "1.0.0"
DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES = ("zh-CN", "en")
SCHEMA_BASE = "https://quantstrategylab.github.io/QuantAdvisorResearch/schemas/site/1.0.0"
SITE_HOME_URL = "https://quantstrategylab.github.io/QuantAdvisorResearch/"
FEED_ROUTE = "feed.xml"
REPORT_SUFFIX = "-model-recommendations.html"
HORIZONS = ("long", "medium", "short")
INDEX_RECENT_LIMIT = 5
FEED_ITEM_LIMIT = 20
ARCHIVE_REPORT_LIMIT = 1000
DISCLAIMER_ZH = "投资有风险。本站内容为模型研究输出，不构成投资建议。"
FEED_TITLE_ZH = "智慧投顾研究系统"
FEED_DESCRIPTION_ZH = "QuantStrategyLab 智慧投顾研究系统，包含推荐理由、周期和风险提示。"
SITE_POLICY = {
    "non_personalized_recommendations_allowed": True,
    "execution_allowed": False,
    "portfolio_allocation_allowed": False,
    "personalized_advice_allowed": False,
    "account_specific_advice_allowed": False,
}
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "site" / CONTRACT_VERSION
PAYLOAD_PATH = re.compile(
    r"^(?:index|archive|feed)\.json$"
    r"|^reports/\d{4}-\d{2}-\d{2}-(?:daily|weekly|monthly)\.json$"
)
REPORT_PATH = re.compile(
    r"^reports/(?P<id>\d{4}-\d{2}-\d{2}-(?:daily|weekly|monthly))\.json$"
)
SUMMARY_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-(?:daily|weekly|monthly)$")


class SiteContractError(ValueError):
    """Raised when a projected or on-disk site bundle violates the v1 contract."""


@dataclass(frozen=True)
class SiteBundle:
    release_id: str
    built_at: str
    documents: Mapping[str, Mapping[str, Any]]
    raw: Mapping[str, bytes]

    @property
    def payload_paths(self) -> tuple[str, ...]:
        return tuple(sorted(path for path in self.documents if path != "manifest.json"))


def _timestamp(value: Any, name: str, *, allow_naive: bool = False) -> str:
    try:
        if isinstance(value, dt.datetime):
            parsed = value
        else:
            text = str(value or "").strip()
            parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            if not allow_naive:
                raise ValueError("timezone required")
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError) as exc:
        raise SiteContractError(f"{name}_invalid") from exc


def _localized_zh(value: Any, name: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        raise SiteContractError(f"{name}_empty")
    return {"zh-CN": text, "en": None}


def _optional_localized_zh(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    return {"zh-CN": text, "en": None} if text else None


def _plain_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _report_id(report: Mapping[str, Any]) -> str:
    return f"{report['as_of']}-{report['cadence']}"


def _report_route(report: Mapping[str, Any]) -> str:
    return f"{_report_id(report)}{REPORT_SUFFIX}"


def _report_payload_path(report: Mapping[str, Any]) -> str:
    return f"reports/{_report_id(report)}.json"


def _input_status(report: Mapping[str, Any]) -> str:
    if index_inputs_verified(report):
        return "verified"
    summary = report.get("summary")
    warnings = summary.get("data_quality_warnings") if isinstance(summary, Mapping) else None
    if (isinstance(warnings, list) and warnings) or isinstance(report.get("freshness"), Mapping):
        return "partial"
    return "unknown"


def _empty_reason(report: Mapping[str, Any], horizon: str, symbols: list[str]) -> str | None:
    if symbols:
        return None
    if index_threshold_unmet(report, horizon):
        return "threshold_unmet"
    if _input_status(report) == "partial":
        return "input_unavailable"
    return "unknown"


def _final_picks(report: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    decisions = report.get("final_decisions")
    if not isinstance(decisions, Mapping):
        return None
    picks = decisions.get("recommendations")
    if not isinstance(picks, list):
        return None
    return [pick for pick in picks if isinstance(pick, dict)]


def _final_recommendation_count(report: Mapping[str, Any]) -> int | None:
    picks = _final_picks(report)
    if picks is None:
        return None
    summary = report.get("summary")
    if isinstance(summary, Mapping):
        count = summary.get("final_recommendation_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    return len(picks)


def _report_description(report: Mapping[str, Any]) -> str:
    summary = report.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    symbols = [str(symbol) for symbol in summary.get("top_recommended_symbols", []) if str(symbol).strip()]
    themes = format_theme_ids(summary.get("top_theme_ids", []))
    return (
        f"主要信号={themes or '无'}；系统结论={', '.join(symbols) or '无'}。"
        "智慧投顾研究输出；不包含下单、仓位配置或账户级建议。"
    )


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    source_schema = str(report["schema_version"])
    as_of = str(report["as_of"])
    cadence = str(report["cadence"])
    symbols_by_horizon = {
        horizon: displayed_horizon_symbols(report, horizon)
        for horizon in HORIZONS
    }
    top_themes = [
        _localized_zh(theme_label(theme_id), f"top_theme[{index}]")
        for index, theme_id in enumerate(summary.get("top_theme_ids", []))
        if str(theme_id).strip()
    ]
    return {
        "id": f"{as_of}-{cadence}",
        "route": f"{as_of}-{cadence}{REPORT_SUFFIX}",
        "as_of": as_of,
        "cadence": cadence,
        "source_schema": source_schema,
        "title": _localized_zh(f"{as_of} {cadence_label(report)}智慧投顾研究", "title"),
        "description": _localized_zh(_report_description(report), "description"),
        "generated_at": _timestamp(report.get("generated_at"), "generated_at", allow_naive=source_schema == "5"),
        "reference_time": (
            _timestamp(report["reference_time"], "reference_time")
            if report.get("reference_time") is not None
            else None
        ),
        "expires_at": (
            _timestamp(report["expires_at"], "expires_at")
            if report.get("expires_at") is not None
            else None
        ),
        "input_status": _input_status(report),
        "final_recommendation_count": _final_recommendation_count(report),
        "horizons": {
            horizon: {
                "symbols": symbols_by_horizon[horizon],
                "empty_reason": _empty_reason(report, horizon, symbols_by_horizon[horizon]),
            }
            for horizon in HORIZONS
        },
        "top_themes": top_themes,
        "legacy_summary_symbols": [
            str(symbol) for symbol in summary.get("top_recommended_symbols", []) if str(symbol).strip()
        ],
        "legacy_horizon_symbols": {
            horizon: horizon_summary_symbols(report, horizon)
            for horizon in HORIZONS
        },
    }


def _card(pick: Mapping[str, Any], *, rank: int, horizon: str) -> dict[str, Any]:
    symbol = str(pick.get("symbol") or "").strip()
    if not symbol:
        raise SiteContractError("card_symbol_empty")
    primary_horizon = pick.get("primary_horizon")
    if primary_horizon == horizon:
        selection_basis = "primary_horizon"
    elif horizon == "long":
        selection_basis = "long_fallback"
    else:
        raise SiteContractError("card_selection_basis_invalid")
    actions = pick.get("horizon_actions")
    action = actions.get(horizon) if isinstance(actions, Mapping) else None
    horizon_action = action if action in {"recommend", "watch"} else "unknown"
    _label, window, _score = horizon_display_meta(dict(pick), horizon)
    return {
        "rank": rank,
        "symbol": symbol,
        "name": _plain_optional(pick.get("name")),
        "horizon_action": horizon_action,
        "selection_basis": selection_basis,
        "window": _localized_zh(window, f"card_window[{horizon}]"),
        "business_summary": _optional_localized_zh(pick.get("business_summary")),
        "prospect_summary": _optional_localized_zh(pick.get("prospect_summary")),
        "risk_summary": _optional_localized_zh(pick.get("risk_summary")),
    }


def _report_document(report: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    picks = _final_picks(report) or []
    cards = {
        horizon: [
            _card(pick, rank=rank, horizon=horizon)
            for rank, pick in enumerate(ranked_horizon_picks(picks, horizon), start=1)
        ]
        for horizon in HORIZONS
    }
    return {
        "summary": dict(summary),
        "lead": [
            _localized_zh(f"本期结论：{format_horizon_conclusion(report)}。", "lead[0]"),
            _localized_zh(format_momentum_factor_summary(report), "lead[1]"),
            _localized_zh(format_report_takeaway(report), "lead[2]"),
        ],
        "cards": cards,
        "disclaimer": _localized_zh(DISCLAIMER_ZH, "disclaimer"),
    }


def _envelope(kind: str, *, release_id: str, built_at: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "$schema": f"{SCHEMA_BASE}/{kind}.schema.json",
        "contract_version": CONTRACT_VERSION,
        "kind": kind,
        "release_id": release_id,
        "built_at": built_at,
        "default_locale": DEFAULT_LOCALE,
        "locales": [DEFAULT_LOCALE],
        "policy": dict(SITE_POLICY),
        "data": dict(data),
    }


def _ordered(reports: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(reports, key=lambda report: str(report["as_of"]), reverse=True)


def _latest_validity(
    latest: Mapping[str, Any] | None,
    *,
    evaluated_at: dt.datetime,
) -> str:
    if latest is None:
        return "none"
    expires_at = latest.get("expires_at")
    if expires_at is None:
        return "unknown"
    expires = normalize_aware_datetime(str(expires_at))
    return "expired" if evaluated_at > expires else "current"


def _select_latest(
    reports: Sequence[Mapping[str, Any]],
    *,
    evaluated_at: dt.datetime,
) -> Mapping[str, Any] | None:
    ordered = _ordered(reports)
    latest = next(
        (report for report in ordered if not is_report_expired(report, now=evaluated_at)),
        None,
    )
    if latest is None and ordered:
        latest = ordered[0]
    return latest


def project_site_bundle(
    reports: Sequence[Mapping[str, Any]],
    *,
    built_at: dt.datetime | str,
    evaluated_at: dt.datetime | str,
    release_id: str | None = None,
    feed_title: str = FEED_TITLE_ZH,
    feed_description: str = FEED_DESCRIPTION_ZH,
    allow_empty: bool = False,
) -> SiteBundle:
    """Project validated, already-selected reports into deterministic JSON artifacts."""

    built_at_text = _timestamp(built_at, "built_at")
    try:
        evaluated_at_dt = (
            normalize_aware_datetime(evaluated_at) if isinstance(evaluated_at, dt.datetime) else normalize_aware_datetime(str(evaluated_at))
        )
    except (TimeContractError, TypeError, ValueError) as exc:
        raise SiteContractError("evaluated_at_invalid") from exc
    evaluated_at_text = evaluated_at_dt.isoformat().replace("+00:00", "Z")

    report_list = list(reports)
    if not report_list and not allow_empty:
        raise SiteContractError("reports_empty")
    if len(report_list) > ARCHIVE_REPORT_LIMIT:
        raise SiteContractError("reports_exceed_limit")
    for report in report_list:
        try:
            validate_advisory_report(report)
        except (AdvisoryValidationError, AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SiteContractError(f"report_invalid: {exc}") from exc

    ids = [_report_id(report) for report in report_list]
    if len(ids) != len(set(ids)):
        raise SiteContractError("report_id_duplicate")

    try:
        normalized_release_id = str(uuid.UUID(str(release_id))) if release_id else str(uuid.uuid4())
    except (ValueError, AttributeError, TypeError) as exc:
        raise SiteContractError("release_id_invalid") from exc

    summaries = {_report_id(report): _summary(report) for report in report_list}
    ordered = _ordered(report_list)
    archive_summaries = [summaries[_report_id(report)] for report in ordered]
    latest_report = _select_latest(report_list, evaluated_at=evaluated_at_dt)
    latest_summary = summaries[_report_id(latest_report)] if latest_report is not None else None
    latest_id = latest_summary["id"] if latest_summary is not None else None
    recent = [summary for summary in archive_summaries if summary["id"] != latest_id][:INDEX_RECENT_LIMIT]

    documents: dict[str, dict[str, Any]] = {}
    documents["index.json"] = _envelope(
        "index",
        release_id=normalized_release_id,
        built_at=built_at_text,
        data={
            "evaluated_at": evaluated_at_text,
            "latest": latest_summary,
            "latest_validity": _latest_validity(latest_summary, evaluated_at=evaluated_at_dt),
            "recent": recent,
        },
    )
    documents["archive.json"] = _envelope(
        "archive",
        release_id=normalized_release_id,
        built_at=built_at_text,
        data={"reports": archive_summaries},
    )
    for report in report_list:
        documents[_report_payload_path(report)] = _envelope(
            "report",
            release_id=normalized_release_id,
            built_at=built_at_text,
            data=_report_document(report, summaries[_report_id(report)]),
        )
    documents["feed.json"] = _envelope(
        "feed",
        release_id=normalized_release_id,
        built_at=built_at_text,
        data={
            "title": _localized_zh(feed_title, "feed_title"),
            "description": _localized_zh(feed_description, "feed_description"),
            "home_url": SITE_HOME_URL,
            "feed_route": FEED_ROUTE,
            "items": [
                {
                    "report_id": summary["id"],
                    "title": summary["title"],
                    "route": summary["route"],
                    "guid": f"{SITE_HOME_URL}{summary['route']}",
                    "published_at": summary["generated_at"],
                    "description": summary["description"],
                }
                for summary in archive_summaries[:FEED_ITEM_LIMIT]
            ],
        },
    )

    raw = {path: _serialize(document) for path, document in documents.items()}
    files = [
        {
            "path": path,
            "kind": str(documents[path]["kind"]),
            "sha256": hashlib.sha256(raw[path]).hexdigest(),
            "bytes": len(raw[path]),
        }
        for path in sorted(documents)
    ]
    manifest = _envelope(
        "manifest",
        release_id=normalized_release_id,
        built_at=built_at_text,
        data={"files": files, "report_count": len(ordered)},
    )
    manifest_path = "manifest.json"
    documents[manifest_path] = manifest
    raw[manifest_path] = _serialize(manifest)
    return SiteBundle(
        release_id=normalized_release_id,
        built_at=built_at_text,
        documents=documents,
        raw=raw,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non_finite_json:{value}")


def _json_loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_json_constant)


def _serialize(document: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SiteContractError(f"json_serialization_invalid: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load_schemas(schema_dir: Path) -> tuple[dict[str, dict[str, Any]], Any]:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError as exc:  # pragma: no cover - exercised when optional dep is absent
        raise SiteContractError("jsonschema_not_installed") from exc

    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Any]] = []
    for path in sorted(schema_dir.glob("*.schema.json")):
        try:
            schema = _json_loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise SiteContractError(f"schema_unreadable:{path.name}") from exc
        if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
            raise SiteContractError(f"schema_id_missing:{path.name}")
        Draft202012Validator.check_schema(schema)
        schemas[schema["$id"]] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    if not schemas:
        raise SiteContractError("schema_registry_empty")
    return schemas, Registry().with_resources(resources)


def _validate_schemas(documents: Mapping[str, Mapping[str, Any]], schema_dir: Path) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover
        raise SiteContractError("jsonschema_not_installed") from exc
    schemas, registry = _load_schemas(schema_dir)
    for path, document in documents.items():
        schema_url = document.get("$schema")
        if schema_url not in schemas:
            raise SiteContractError(f"{path}:schema_unsupported")
        validator = Draft202012Validator(
            schemas[str(schema_url)],
            registry=registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.path) or "$"
            raise SiteContractError(f"{path}:schema_invalid:{location}:{error.message}")


def _walk_localized(value: Any):
    if isinstance(value, Mapping):
        if set(value) == {"zh-CN", "en"}:
            yield value
            return
        for item in value.values():
            yield from _walk_localized(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_localized(item)


def _validate_locales(documents: Mapping[str, Mapping[str, Any]]) -> None:
    locales = documents["manifest.json"]["locales"]
    if DEFAULT_LOCALE not in locales:
        raise SiteContractError("locale_default_missing")
    translated = "en" in locales
    for path, document in documents.items():
        for text in _walk_localized(document):
            english = text.get("en")
            if translated and not (isinstance(english, str) and english.strip()):
                raise SiteContractError(f"{path}:locale_translation_missing")
            if not translated and english is not None:
                raise SiteContractError(f"{path}:locale_translation_unapproved")


def _validate_envelope(documents: Mapping[str, Mapping[str, Any]]) -> None:
    base = documents["manifest.json"]
    for key in ("release_id", "built_at", "default_locale", "locales", "policy"):
        for path, document in documents.items():
            if document.get(key) != base.get(key):
                raise SiteContractError(f"{path}:envelope_mismatch:{key}")


def _expected_kind(path: str) -> str:
    if path in {"index.json", "archive.json", "feed.json"}:
        return path[: -len(".json")]
    if REPORT_PATH.fullmatch(path):
        return "report"
    raise SiteContractError(f"payload_path_invalid:{path}")


def _validate_manifest(
    bundle: SiteBundle,
    archive: Mapping[str, Any],
) -> None:
    manifest = bundle.documents["manifest.json"]
    entries = manifest["data"]["files"]
    payload_paths = set(bundle.payload_paths)
    listed_paths = [entry["path"] for entry in entries]
    if len(listed_paths) != len(set(listed_paths)):
        raise SiteContractError("manifest_path_duplicate")
    if set(listed_paths) != payload_paths:
        raise SiteContractError("manifest_membership_mismatch")
    report_count = int(manifest["data"]["report_count"])
    if report_count != len(archive["data"]["reports"]):
        raise SiteContractError("manifest_report_count_mismatch")
    if len(entries) != report_count + 3:
        raise SiteContractError("manifest_file_count_mismatch")
    for entry in entries:
        path = entry["path"]
        if not PAYLOAD_PATH.fullmatch(path):
            raise SiteContractError(f"manifest_path_invalid:{path}")
        if entry["kind"] != _expected_kind(path):
            raise SiteContractError(f"manifest_kind_mismatch:{path}")
        raw = bundle.raw.get(path)
        if raw is None:
            raise SiteContractError(f"manifest_payload_missing:{path}")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise SiteContractError(f"manifest_sha256_mismatch:{path}")
        if len(raw) != entry["bytes"]:
            raise SiteContractError(f"manifest_bytes_mismatch:{path}")


def _validate_summary(summary: Mapping[str, Any], *, path: str) -> None:
    report_id = summary["id"]
    if not SUMMARY_ID.fullmatch(report_id):
        raise SiteContractError(f"{path}:summary_id_invalid")
    if summary["route"] != f"{report_id}{REPORT_SUFFIX}":
        raise SiteContractError(f"{path}:summary_route_mismatch")
    if report_id != f"{summary['as_of']}-{summary['cadence']}":
        raise SiteContractError(f"{path}:summary_identity_mismatch")
    if summary["source_schema"] == "5" and (summary["reference_time"] is not None or summary["expires_at"] is not None):
        raise SiteContractError(f"{path}:legacy_timestamp_synthesized")


def _validate_cross_file(bundle: SiteBundle) -> None:
    documents = bundle.documents
    payload_paths = set(bundle.payload_paths)
    expected = {"index.json", "archive.json", "feed.json"} | {
        path for path in payload_paths if REPORT_PATH.fullmatch(path)
    }
    if payload_paths != expected:
        raise SiteContractError("payload_membership_mismatch")

    archive = documents["archive.json"]
    index = documents["index.json"]
    feed = documents["feed.json"]
    archive_summaries = archive["data"]["reports"]
    summaries_by_id: dict[str, Mapping[str, Any]] = {}
    previous_as_of: str | None = None
    for summary in archive_summaries:
        _validate_summary(summary, path="archive.json")
        report_id = summary["id"]
        if report_id in summaries_by_id:
            raise SiteContractError("archive_id_duplicate")
        summaries_by_id[report_id] = summary
        if previous_as_of is not None and summary["as_of"] > previous_as_of:
            raise SiteContractError("archive_order_not_descending")
        previous_as_of = summary["as_of"]

    report_paths = {
        path for path in payload_paths if REPORT_PATH.fullmatch(path)
    }
    for path in report_paths:
        match = REPORT_PATH.fullmatch(path)
        assert match is not None
        report_id = match.group("id")
        summary = summaries_by_id.get(report_id)
        if summary is None:
            raise SiteContractError(f"{path}:report_not_in_archive")
        document = documents[path]
        if _canonical(document["data"]["summary"]) != _canonical(summary):
            raise SiteContractError(f"{path}:summary_mismatch")
        for horizon in HORIZONS:
            cards = document["data"]["cards"][horizon]
            if [card["rank"] for card in cards] != list(range(1, len(cards) + 1)):
                raise SiteContractError(f"{path}:card_rank_invalid:{horizon}")
            symbols = [card["symbol"] for card in cards]
            if len(symbols) != len(set(symbols)):
                raise SiteContractError(f"{path}:card_symbol_duplicate:{horizon}")
            if symbols != summary["horizons"][horizon]["symbols"]:
                raise SiteContractError(f"{path}:card_symbols_mismatch:{horizon}")
            if horizon != "long" and any(card["selection_basis"] == "long_fallback" for card in cards):
                raise SiteContractError(f"{path}:long_fallback_outside_long")
    if len(report_paths) != len(archive_summaries):
        raise SiteContractError("report_file_count_mismatch")

    latest = index["data"]["latest"]
    latest_id = latest["id"] if latest is not None else None
    if latest is not None:
        if latest_id not in summaries_by_id:
            raise SiteContractError("index_latest_not_in_archive")
        if _canonical(latest) != _canonical(summaries_by_id[latest_id]):
            raise SiteContractError("index_latest_summary_mismatch")
    expected_validity = _latest_validity(
        latest,
        evaluated_at=normalize_aware_datetime(index["data"]["evaluated_at"]),
    )
    if index["data"]["latest_validity"] != expected_validity:
        raise SiteContractError("index_latest_validity_mismatch")

    recent = index["data"]["recent"]
    recent_ids = [summary["id"] for summary in recent]
    if len(recent_ids) != len(set(recent_ids)):
        raise SiteContractError("index_recent_duplicate")
    if latest_id is not None and latest_id in recent_ids:
        raise SiteContractError("index_recent_contains_latest")
    for summary in recent:
        if summary["id"] not in summaries_by_id:
            raise SiteContractError("index_recent_not_in_archive")
        if _canonical(summary) != _canonical(summaries_by_id[summary["id"]]):
            raise SiteContractError("index_recent_summary_mismatch")
    expected_recent_ids = [
        summary["id"] for summary in archive_summaries if summary["id"] != latest_id
    ][:INDEX_RECENT_LIMIT]
    if recent_ids != expected_recent_ids:
        raise SiteContractError("index_recent_membership_mismatch")

    items = feed["data"]["items"]
    item_ids = [item["report_id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise SiteContractError("feed_item_duplicate")
    expected_feed_ids = [summary["id"] for summary in archive_summaries][:FEED_ITEM_LIMIT]
    if item_ids != expected_feed_ids:
        raise SiteContractError("feed_item_membership_mismatch")
    previous_published: str | None = None
    for item in items:
        summary = summaries_by_id[item["report_id"]]
        if item["route"] != summary["route"]:
            raise SiteContractError("feed_route_mismatch")
        if item["title"] != summary["title"]:
            raise SiteContractError("feed_title_mismatch")
        if item["description"] != summary["description"]:
            raise SiteContractError("feed_description_mismatch")
        if item["published_at"] != summary["generated_at"]:
            raise SiteContractError("feed_timestamp_mismatch")
        if item["guid"] != f"{SITE_HOME_URL}{summary['route']}":
            raise SiteContractError("feed_guid_mismatch")
        if previous_published is not None and item["published_at"] > previous_published:
            raise SiteContractError("feed_order_not_descending")
        previous_published = item["published_at"]
    for item in items:
        if item["report_id"] not in summaries_by_id:
            raise SiteContractError("feed_item_not_in_archive")


def validate_site_bundle(bundle: SiteBundle, *, schema_dir: Path | str | None = None) -> None:
    """Validate schema, membership, checksums, locales and cross-file semantics offline."""

    resolved_schema_dir = Path(schema_dir) if schema_dir is not None else SCHEMA_DIR
    documents = bundle.documents
    if set(documents) != set(bundle.raw):
        raise SiteContractError("bundle_document_bytes_mismatch")
    if "manifest.json" not in documents:
        raise SiteContractError("manifest_missing")
    if bundle.raw.get("manifest.json") is None:
        raise SiteContractError("manifest_bytes_missing")
    _validate_schemas(documents, resolved_schema_dir)
    _validate_envelope(documents)
    _validate_locales(documents)
    _validate_manifest(bundle, documents["archive.json"])
    _validate_cross_file(bundle)


def write_site_bundle(
    bundle: SiteBundle,
    output_dir: str | Path,
    *,
    schema_dir: Path | str | None = None,
) -> tuple[Path, ...]:
    """Validate a bundle, then write its exact bytes into an output directory."""

    validate_site_bundle(bundle, schema_dir=schema_dir)
    output = Path(output_dir)
    written: list[Path] = []
    for relative in sorted(bundle.raw):
        if not PAYLOAD_PATH.fullmatch(relative) and relative != "manifest.json":
            raise SiteContractError(f"payload_path_invalid:{relative}")
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bundle.raw[relative])
        written.append(target)
    return tuple(written)


def read_site_bundle(
    bundle_dir: str | Path,
    *,
    schema_dir: Path | str | None = None,
) -> SiteBundle:
    """Read and validate a bundle directory using only its manifest-listed bytes."""

    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    try:
        manifest_raw = manifest_path.read_bytes()
        manifest = _json_loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SiteContractError("manifest_unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "manifest":
        raise SiteContractError("manifest_invalid")
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise SiteContractError("contract_version_unsupported")
    data = manifest.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("files"), list):
        raise SiteContractError("manifest_files_invalid")

    documents: dict[str, dict[str, Any]] = {"manifest.json": manifest}
    raw: dict[str, bytes] = {"manifest.json": manifest_raw}
    for entry in data["files"]:
        if not isinstance(entry, Mapping):
            raise SiteContractError("manifest_entry_invalid")
        relative = entry.get("path")
        if not isinstance(relative, str) or not PAYLOAD_PATH.fullmatch(relative):
            raise SiteContractError(f"payload_path_invalid:{relative}")
        target = (root / relative).resolve()
        if root.resolve() not in target.parents:
            raise SiteContractError(f"payload_path_escape:{relative}")
        try:
            payload_raw = target.read_bytes()
            document = _json_loads(payload_raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise SiteContractError(f"payload_unreadable:{relative}") from exc
        if not isinstance(document, dict):
            raise SiteContractError(f"payload_object_invalid:{relative}")
        documents[relative] = document
        raw[relative] = payload_raw

    bundle = SiteBundle(
        release_id=str(manifest.get("release_id")),
        built_at=str(manifest.get("built_at")),
        documents=documents,
        raw=raw,
    )
    validate_site_bundle(bundle, schema_dir=schema_dir)
    return bundle


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project validated advisory reports or validate a versioned site JSON bundle."
    )
    parser.add_argument("--validate", metavar="DIR", help="Validate an existing bundle directory.")
    parser.add_argument("--reports", nargs="+", help="One or more advisory report JSON files.")
    parser.add_argument("--output-dir", help="Staging directory for the projected bundle.")
    parser.add_argument("--mandatory-current", help="Mandatory current report path.")
    parser.add_argument("--recovered-history", nargs="*", default=[], help="Recovered history report paths.")
    parser.add_argument("--built-at", help="Explicit publication build timestamp (RFC 3339).")
    parser.add_argument("--evaluated-at", help="Explicit publication evaluation timestamp (RFC 3339).")
    parser.add_argument("--release-id", help="Optional release UUID for deterministic rebuilds.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow an explicitly initialized empty site.")
    parser.add_argument("--schema-dir", help="Override the local schema directory.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    schema_dir = Path(args.schema_dir) if args.schema_dir else None
    if args.validate:
        read_site_bundle(args.validate, schema_dir=schema_dir)
        return
    if not args.reports or not args.output_dir or not args.built_at or not args.evaluated_at:
        raise SystemExit("--reports, --output-dir, --built-at and --evaluated-at are required")
    selection = require_publish_candidates(
        args.mandatory_current,
        list(args.recovered_history) if args.mandatory_current else list(args.reports),
    )
    reports = [load_report(path) for path in selection.selected_paths]
    bundle = project_site_bundle(
        reports,
        built_at=args.built_at,
        evaluated_at=args.evaluated_at,
        release_id=args.release_id,
        allow_empty=args.allow_empty,
    )
    write_site_bundle(bundle, args.output_dir, schema_dir=schema_dir)


if __name__ == "__main__":
    main()

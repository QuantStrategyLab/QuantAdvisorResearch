from copy import deepcopy
import json
from pathlib import Path

import pytest

from quant_advisor_research import advisory_report
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report
from quant_advisor_research.publisher import render_reports_index_json


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(advisory_report, "utc_now_iso", lambda: "2026-05-31T01:00:00Z")
    return advisory_report.build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def test_horizon_maximum_includes_candidates_that_all_fail_selection(monkeypatch):
    monkeypatch.setattr(
        advisory_report,
        "build_horizon_scores",
        lambda *args: {
            horizon: {
                "score": 0.2,
                "components": {"source": 0.1, "momentum": 0.1, "medium_context": 0.1,
                               "long_context": 0.1, "market_confirmation": None},
            }
            for horizon in ("short", "medium", "long")
        },
    )
    decisions = advisory_report.build_final_decisions([{"symbol": "EXAMPLE"}], None)
    assert decisions["recommendations"] == []
    assert decisions["watchlist"] == []
    assert decisions["horizon_summary"] == {
        "short": {"max_score": 0.2, "threshold": 0.60},
        "medium": {"max_score": 0.2, "threshold": 0.52},
        "long": {"max_score": 0.2, "threshold": 0.62},
    }


def test_no_candidates_has_no_invented_score():
    decisions = advisory_report.build_final_decisions([], None)
    assert all(item["max_score"] is None for item in decisions["horizon_summary"].values())


def test_input_checks_and_sources_never_invent_fetch_times(report):
    checks = {item["name"]: item for item in report["input_checks"]}
    assert set(checks) == {"political_events", "political_watchlist", "ai_signal",
                           "theme_momentum", "market_confirmation"}
    assert checks["political_events"]["status"] == "available"
    assert checks["political_watchlist"]["as_of"] is None
    for name in ("ai_signal", "theme_momentum", "market_confirmation"):
        assert checks[name]["status"] == "missing"
        assert checks[name]["as_of"] is None
    assert report["sources"]
    assert len({(item["url"], item["type"]) for item in report["sources"]}) == len(report["sources"])
    assert all(item["fetched_at"] is None and item["status"] == "unverified" for item in report["sources"])
    assert all(item["url"].startswith(("http://", "https://")) for item in report["sources"])


@pytest.mark.parametrize("kind", ["invalid", "stale", "stale_legacy", "future", "fresh", "unavailable"])
def test_theme_input_check_preserves_failed_context_state(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(advisory_report, "utc_now_iso", lambda: "2026-05-31T01:00:00Z")
    source = tmp_path / "theme.example.json"
    if kind == "unavailable":
        pass
    elif kind == "invalid":
        source.write_text("{invalid", encoding="utf-8")
    else:
        theme = json.loads((ROOT / "examples/theme_momentum_snapshot.example.json").read_text())
        if kind in {"stale", "stale_legacy"}:
            theme.update(as_of="2026-05-01", generated_at="2026-05-02T00:00:00Z",
                         expires_at="2026-05-09T00:00:00Z")
        if kind == "stale_legacy":
            theme.pop("expires_at")
        if kind == "future":
            theme.update(as_of="2026-06-01", generated_at="2026-06-02T00:00:00Z",
                         expires_at="2026-06-09T00:00:00Z")
        source.write_text(json.dumps(theme), encoding="utf-8")
    result = advisory_report.build_advisory_report(
        as_of="2026-05-30", cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
        theme_momentum_path=source,
    )
    check = next(item for item in result["input_checks"] if item["name"] == "theme_momentum")
    assert check["status"] == {"fresh": "available", "stale": "stale", "stale_legacy": "stale",
                               "invalid": "invalid", "future": "invalid", "unavailable": "invalid"}[kind]
    assert check["detail"]


def test_index_counts_public_picks_once_and_excludes_watch_and_overflow(report):
    report["final_decisions"] = {
        "recommendations": [{"symbol": "EXAMPLE-A", "primary_horizon": "medium"},
                            {"symbol": "EXAMPLE-B", "primary_horizon": "long"}],
        "watchlist": [{"symbol": "EXAMPLE-C", "primary_horizon": "short"}],
        "overflow_recommendations": [{"symbol": "EXAMPLE-D", "primary_horizon": "short"}],
    }
    older = deepcopy(report)
    older["as_of"] = "2026-05-23"
    older["final_decisions"]["recommendations"] = []
    index = json.loads(render_reports_index_json([older, report]))
    assert index["schema_version"] == 1
    recent, empty = index["reports"]
    assert recent["as_of"] == "2026-05-30"
    assert recent["html"].endswith(".html") and recent["json"].endswith(".json")
    assert recent["recommendation_count"] == 2
    assert recent["horizon_counts"] == {"short": 0, "medium": 1, "long": 1}
    assert empty["recommendation_count"] == 0
    assert empty["horizon_counts"] == {"short": 0, "medium": 0, "long": 0}


def test_index_legacy_report_counts_only_recommend_ratings(report):
    report.pop("final_decisions")
    report["recommendations"] = [
        {"symbol": "EXAMPLE-A", "rating": "recommend", "primary_horizon": "short"},
        {"symbol": "EXAMPLE-B", "rating": "watch", "primary_horizon": "long"},
    ]
    item = json.loads(render_reports_index_json([report]))["reports"][0]
    assert item["recommendation_count"] == 1
    assert item["horizon_counts"] == {"short": 1, "medium": 0, "long": 0}


def test_sources_exclude_non_http_and_userinfo():
    watchlist = {
        key: advisory_report.WatchlistItem(key, key, "", "", "", url)
        for key, url in {
            "EXAMPLE-A": "https://example.invalid/evidence",
            "EXAMPLE-B": "javascript:alert(1)",
            "EXAMPLE-C": "https://example-user@example.invalid/private",
            "EXAMPLE-D": "file:///tmp/example.csv",
        }.items()
    }
    assert advisory_report.report_sources([], watchlist) == [
        {"url": "https://example.invalid/evidence", "type": "watchlist", "fetched_at": None,
         "status": "unverified"}
    ]


@pytest.mark.parametrize("schema", ["5", "6"])
def test_old_reports_without_additions_remain_valid(report, schema):
    for key in ("input_checks", "sources"):
        report.pop(key, None)
    report["final_decisions"].pop("horizon_summary", None)
    if schema == "5":
        report.update(schema_version="5", contract_version="model_recommendations.v5")
        for key in ("reference_time", "expires_at", "freshness", "input_digest"):
            report.pop(key)
    validate_advisory_report(report)


@pytest.mark.parametrize("field,value", [
    ("max_score", float("nan")), ("max_score", True), ("max_score", 1.1),
    ("threshold", None), ("threshold", -0.1), ("threshold", "0.6"),
])
def test_invalid_optional_scores_are_rejected(report, field, value):
    report["final_decisions"]["horizon_summary"]["short"][field] = value
    with pytest.raises(AdvisoryValidationError, match="horizon_summary"):
        validate_advisory_report(report)


@pytest.mark.parametrize("key,item", [
    ("input_checks", {"name": "ai_signal", "detail": "missing", "status": "green", "as_of": None}),
    ("input_checks", {"name": "ai_signal", "detail": "missing", "status": "missing", "as_of": "bad-date"}),
    ("sources", {"url": "javascript:alert(1)", "type": "political_event", "fetched_at": None,
                 "status": "unverified"}),
    ("sources", {"url": "https://example.invalid/", "type": "political_event", "fetched_at": "bad-time",
                 "status": "unverified"}),
])
def test_invalid_optional_evidence_is_rejected(report, key, item):
    report[key] = [item]
    with pytest.raises(AdvisoryValidationError, match=key):
        validate_advisory_report(report)

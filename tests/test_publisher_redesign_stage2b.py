from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.publisher import (
    classify_report_path,
    publish_reports,
    report_content_fingerprint,
    unique_report_paths_by_content,
)
from quant_advisor_research.archive_backfill import backfill_site_archive
from quant_advisor_research.time_contract import canonical_reference_time


ROOT = Path(__file__).resolve().parents[1]


def build_v5() -> dict:
    return build_advisory_report(
        as_of="2026-05-30",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def build_v6() -> dict:
    report = build_v5()
    report.update(
        {
            "schema_version": "6",
            "contract_version": "model_recommendations.v6",
            "reference_time": canonical_reference_time(dt.date(2026, 5, 30)).isoformat().replace("+00:00", "Z"),
            "generated_at": "2026-05-31T12:00:00.123456Z",
            "expires_at": "2026-06-07T12:00:00.123456Z",
            "freshness": {
                "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
            },
        }
    )
    return report


def write_report(path: Path, report: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_valid_v5_v6_selection_is_order_independent_and_prefers_v6(tmp_path: Path) -> None:
    v5_path = write_report(tmp_path / "v5.json", build_v5())
    v6_path = write_report(tmp_path / "v6.json", build_v6())
    assert unique_report_paths_by_content([v5_path, v6_path]) == [v6_path]
    assert unique_report_paths_by_content([v6_path, v5_path]) == [v6_path]


def test_malformed_partial_v6_cannot_shadow_valid_v5(tmp_path: Path) -> None:
    v5_path = write_report(tmp_path / "v5.json", build_v5())
    malformed_v6 = build_v6()
    malformed_v6.pop("reference_time")
    v6_path = write_report(tmp_path / "v6.json", malformed_v6)
    assert unique_report_paths_by_content([v6_path, v5_path]) == [v5_path]
    assert classify_report_path(v6_path).status == "INVALID"


def test_freshness_state_and_substantive_warning_changes_are_not_deduped(tmp_path: Path) -> None:
    fresh = build_v6()
    fresh["source_artifacts"]["ai_signal"] = "context.json"
    fresh["freshness"]["ai_signal"] = {
        "present": True, "valid": True, "reason": "fresh",
        "as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z", "expires_at": "2026-06-30",
    }
    expired = json.loads(json.dumps(fresh))
    expired["freshness"]["ai_signal"] = {
        "present": True, "valid": False, "reason": "expired",
        "as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z", "expires_at": "2026-05-30T23:59:59Z",
    }
    first = write_report(tmp_path / "fresh.json", fresh)
    second = write_report(tmp_path / "expired.json", expired)
    assert report_content_fingerprint(fresh) != report_content_fingerprint(expired)
    assert set(unique_report_paths_by_content([first, second])) == {first, second}

    warned = build_v5()
    warned["summary"]["data_quality_warnings"] = ["ai_signal:stale_as_of"]
    changed = json.loads(json.dumps(warned))
    changed["summary"]["data_quality_warnings"] = ["ai_signal:future_source"]
    assert report_content_fingerprint(warned) != report_content_fingerprint(changed)


def test_compatibility_only_differences_are_deduped(tmp_path: Path) -> None:
    first = build_v5()
    second = json.loads(json.dumps(first))
    first["summary"]["data_quality_warnings"] = ["compatibility:legacy_a", "operator warning"]
    second["summary"]["data_quality_warnings"] = ["schema_compatibility:v6_b", "operator warning"]
    first_path = write_report(tmp_path / "first.json", first)
    second_path = write_report(tmp_path / "second.json", second)
    assert report_content_fingerprint(first) == report_content_fingerprint(second)
    assert len(unique_report_paths_by_content([second_path, first_path])) == 1


def test_schema_time_and_relative_identity_ties_are_deterministic(tmp_path: Path) -> None:
    old = build_v5()
    old["generated_at"] = "2026-05-31T12:00:00Z"
    new = json.loads(json.dumps(old))
    new["generated_at"] = "2026-06-01T12:00:00Z"
    old_path = write_report(tmp_path / "old.json", old)
    new_path = write_report(tmp_path / "new.json", new)
    assert unique_report_paths_by_content([new_path, old_path]) == [new_path]

    a = write_report(tmp_path / "a" / "report.json", old)
    b = write_report(tmp_path / "b" / "report.json", old)
    assert unique_report_paths_by_content([b, a]) == [a]
    assert unique_report_paths_by_content([a, b]) == [a]


def test_period_cadence_and_content_boundaries_are_preserved(tmp_path: Path) -> None:
    weekly = build_v5()
    daily = json.loads(json.dumps(weekly))
    daily["cadence"] = "daily"
    different = json.loads(json.dumps(weekly))
    different["recommendations"][0]["reasons"] = ["different logical content"]
    paths = [
        write_report(tmp_path / "weekly.json", weekly),
        write_report(tmp_path / "daily.json", daily),
        write_report(tmp_path / "different.json", different),
    ]
    assert set(unique_report_paths_by_content(paths)) == set(paths)


def test_distinct_reports_retain_caller_order(tmp_path: Path) -> None:
    earlier = build_v5()
    earlier["generated_at"] = "2026-05-31T12:00:00Z"
    later = json.loads(json.dumps(earlier))
    later["schema_version"] = "6"
    later["contract_version"] = "model_recommendations.v6"
    later["reference_time"] = canonical_reference_time(dt.date(2026, 5, 30)).isoformat().replace("+00:00", "Z")
    later["generated_at"] = "2026-06-01T12:00:00.123456Z"
    later["expires_at"] = "2026-06-08T12:00:00.123456Z"
    later["recommendations"][0]["reasons"] = ["distinct logical content"]
    later["freshness"] = {
        "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
        "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
    }
    first = write_report(tmp_path / "first.json", earlier)
    second = write_report(tmp_path / "second.json", later)
    assert unique_report_paths_by_content([first, second]) == [first, second]


@pytest.mark.parametrize(
    ("name", "payload", "status", "reason"),
    [
        ("malformed.json", "{not-json", "IO_INVALID", "json_invalid"),
        ("bad-date.json", dict(build_v5(), as_of="not-a-date"), "INVALID", "contract_invalid"),
        ("bad-generated.json", dict(build_v5(), generated_at="not-a-time"), "INVALID", "contract_invalid"),
    ],
)
def test_quarantine_classification_is_sanitized_and_structured(
    tmp_path: Path, name: str, payload, status: str, reason: str
) -> None:
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        write_report(path, payload)
    classification = classify_report_path(path)
    assert classification.status == status
    assert classification.reason == reason
    assert "not-a-time" not in repr(classification)
    assert "raw" not in repr(classification)


def test_empty_valid_set_fails_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="no_valid_report_candidates"):
        unique_report_paths_by_content([invalid])


def test_backfill_all_invalid_fails_before_site_write(tmp_path: Path) -> None:
    invalid = tmp_path / "advisory_report_2026-05-30.json"
    invalid.write_text("[]", encoding="utf-8")
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="no_valid_report_candidates"):
        backfill_site_archive(
            report_paths=[invalid],
            output_dir=output,
            site_url="https://example.invalid",
            feed_title="Test",
        )
    assert list(output.iterdir()) == [sentinel]


def test_repeated_reads_are_deterministic(tmp_path: Path) -> None:
    v5 = write_report(tmp_path / "v5.json", build_v5())
    v6 = write_report(tmp_path / "v6.json", build_v6())
    first = unique_report_paths_by_content([v5, v6])
    second = unique_report_paths_by_content([v5, v6])
    assert first == second == [v6]


def test_all_invalid_input_fails_before_site_write(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="no_valid_report_candidates"):
        publish_reports([invalid], output, site_url="https://example.invalid", feed_title="Test")
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(output.iterdir()) == [sentinel]


def test_mixed_valid_invalid_publishes_only_valid_candidates(tmp_path: Path) -> None:
    valid = write_report(tmp_path / "valid.json", build_v5())
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    output = tmp_path / "site"
    written = publish_reports(
        [invalid, valid], output, site_url="https://example.invalid", feed_title="Test"
    )
    assert written
    assert (output / "2026-05-30-weekly-model-recommendations.html").exists()


def test_v5_naive_generated_at_is_utc_but_v6_naive_is_invalid(tmp_path: Path) -> None:
    v5 = build_v5()
    v5["generated_at"] = "2026-05-31T12:00:00"
    v5_path = write_report(tmp_path / "v5.json", v5)
    assert classify_report_path(v5_path).status == "VALID"

    v6 = build_v6()
    v6["generated_at"] = "2026-05-31T12:00:00"
    v6_path = write_report(tmp_path / "v6.json", v6)
    assert classify_report_path(v6_path).status == "INVALID"


def test_weekly_overlapping_duplicates_are_pairwise_consistent(tmp_path: Path) -> None:
    reports = []
    for name, as_of, generated_at in (
        ("a.json", "2026-06-20", "2026-06-20T12:00:00Z"),
        ("b.json", "2026-06-21", "2026-06-21T12:00:00Z"),
        ("c.json", "2026-06-27", "2026-06-27T12:00:00Z"),
    ):
        report = build_v5()
        report["as_of"] = as_of
        report["generated_at"] = generated_at
        reports.append(write_report(tmp_path / name, report))
    first = unique_report_paths_by_content([reports[2], reports[0], reports[1]])
    second = unique_report_paths_by_content([reports[1], reports[2], reports[0]])
    assert set(first) == set(second)
    assert len(first) == 2
    for left, right in ((first[0], first[1]), (second[0], second[1])):
        left_report = json.loads(left.read_text(encoding="utf-8"))
        right_report = json.loads(right.read_text(encoding="utf-8"))
        assert not (left_report["as_of"] == right_report["as_of"])


@pytest.mark.parametrize("field", ["schema_version", "cadence"])
@pytest.mark.parametrize("value", [[], {}])
def test_malformed_metadata_types_are_quarantined(tmp_path: Path, field: str, value) -> None:
    report = build_v5()
    report[field] = value
    classification = classify_report_path(write_report(tmp_path / "bad.json", report))
    assert classification.status == "INVALID"
    assert classification.reason == "contract_invalid"


def test_nested_invalid_action_types_are_quarantined_without_raw_payload(tmp_path: Path) -> None:
    report = build_v5()
    report["recommendations"][0]["rating"] = []
    report["recommendations"][0]["horizon_actions"] = {"short": []}
    classification = classify_report_path(write_report(tmp_path / "bad.json", report))
    assert classification.status == "INVALID"
    assert classification.reason == "contract_invalid"
    assert "[]" not in repr(classification)

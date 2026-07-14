from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.archive_backfill import discover_report_paths
from quant_advisor_research.publisher import (
    classify_report_path,
    main as publisher_main,
    publish_reports,
    report_content_fingerprint,
    select_publish_candidates,
    unique_report_paths_by_content,
)
from quant_advisor_research.time_contract import canonical_reference_time


ROOT = Path(__file__).resolve().parents[1]


def build_v5(as_of: str = "2026-06-20") -> dict:
    return build_advisory_report(
        as_of=as_of,
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def build_v6(as_of: str = "2026-06-20") -> dict:
    report = build_v5(as_of)
    report.update(
        {
            "schema_version": "6",
            "contract_version": "model_recommendations.v6",
            "reference_time": canonical_reference_time(dt.date.fromisoformat(as_of)).isoformat().replace("+00:00", "Z"),
            "generated_at": "2026-06-21T12:00:00.123456Z",
            "expires_at": "2026-06-28T12:00:00.123456Z",
            "freshness": {
                "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
            },
        }
    )
    return report


def write_report(path: Path, report: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(report, str):
        path.write_text(report, encoding="utf-8")
    else:
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_same_period_history_winner_is_input_order_independent_and_as_of_precedes_build_time(tmp_path: Path) -> None:
    older_as_of = write_report(tmp_path / "older.json", build_v5("2026-06-20"))
    newer_as_of = build_v5("2026-06-21")
    newer_as_of["generated_at"] = "2026-06-20T00:00:00Z"
    newer_path = write_report(tmp_path / "newer.json", newer_as_of)

    assert unique_report_paths_by_content([older_as_of, newer_path]) == [newer_path]
    assert unique_report_paths_by_content([newer_path, older_as_of]) == [newer_path]


def test_same_day_schema_precedes_generated_at(tmp_path: Path) -> None:
    v5 = build_v5()
    v5["generated_at"] = "2026-06-30T00:00:00Z"
    v6 = build_v6()
    v6["generated_at"] = "2026-06-21T00:00:00.000001Z"
    v6["expires_at"] = "2026-06-28T00:00:00.000001Z"
    v5_path = write_report(tmp_path / "v5.json", v5)
    v6_path = write_report(tmp_path / "v6.json", v6)

    assert unique_report_paths_by_content([v5_path, v6_path]) == [v6_path]
    assert unique_report_paths_by_content([v6_path, v5_path]) == [v6_path]


def test_invalid_v6_cannot_shadow_valid_v5(tmp_path: Path) -> None:
    v5_path = write_report(tmp_path / "v5.json", build_v5())
    invalid_v6 = build_v6()
    invalid_v6.pop("reference_time")
    v6_path = write_report(tmp_path / "v6.json", invalid_v6)

    assert unique_report_paths_by_content([v6_path, v5_path]) == [v5_path]
    assert classify_report_path(v6_path).status == "INVALID"


def test_freshness_and_substantive_warning_change_fingerprint() -> None:
    first = build_v5()
    second = copy.deepcopy(first)
    first["summary"]["data_quality_warnings"] = ["ai_signal:stale_as_of"]
    second["summary"]["data_quality_warnings"] = ["ai_signal:future_source"]
    assert report_content_fingerprint(first) != report_content_fingerprint(second)


def test_compatibility_only_warning_and_v5_v6_metadata_do_not_change_fingerprint() -> None:
    v5 = build_v5()
    v6 = build_v6()
    v5["summary"]["data_quality_warnings"] = ["compatibility:legacy"]
    v6["summary"]["data_quality_warnings"] = ["schema_compatibility:v6"]

    assert report_content_fingerprint(v5) == report_content_fingerprint(v6)


def test_discovery_returns_valid_and_malformed_siblings_for_later_validation(tmp_path: Path) -> None:
    valid = write_report(tmp_path / "valid" / "advisory_report_2026-06-20.json", build_v5())
    malformed = write_report(tmp_path / "bad" / "advisory_report_2026-06-20.json", "{not-json")

    discovered = discover_report_paths([tmp_path], [])

    assert set(discovered) == {valid, malformed}


def test_discovery_orders_all_candidates_newest_first_with_stable_same_date_tie(tmp_path: Path) -> None:
    oldest = write_report(
        tmp_path / "root-a" / "advisory_report_2026-06-18.json", build_v5("2026-06-18")
    )
    newest = write_report(
        tmp_path / "root-b" / "advisory_report_2026-06-20.json", build_v5("2026-06-20")
    )
    same_day_sibling = write_report(
        tmp_path / "root-c" / "advisory_report_2026-06-20.json", build_v5("2026-06-20")
    )

    discovered = discover_report_paths([tmp_path / "root-a", tmp_path / "root-b", tmp_path / "root-c"], [oldest])

    assert [path.name for path in discovered] == [newest.name, same_day_sibling.name, oldest.name]
    assert discovered[0].parent < discovered[1].parent


def test_mandatory_current_is_pinned_over_higher_schema_history_duplicate(tmp_path: Path) -> None:
    current = write_report(tmp_path / "advisory_report_2026-06-20.json", build_v5())
    recovered = write_report(tmp_path / "recovered.json", build_v6())

    selection = select_publish_candidates(current, [recovered])

    assert selection.selected_paths == (current,)
    assert selection.mandatory_current_status == "VALID_SELECTED"


def test_invalid_current_with_valid_history_fails_before_site_write(tmp_path: Path) -> None:
    invalid_current = write_report(tmp_path / "current.json", "{not-json")
    history = write_report(tmp_path / "history.json", build_v5())
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="mandatory_current_invalid"):
        publish_reports(
            [invalid_current],
            output,
            site_url="https://example.invalid",
            feed_title="Test",
            mandatory_current=invalid_current,
            recovered_history=[history],
        )
    assert list(output.iterdir()) == [sentinel]


def test_valid_current_with_invalid_history_publishes_current(tmp_path: Path) -> None:
    current = write_report(tmp_path / "advisory_report_2026-06-20.json", build_v5())
    invalid_history = write_report(tmp_path / "history.json", "[]")
    output = tmp_path / "site"

    publish_reports(
        [current],
        output,
        site_url="https://example.invalid",
        feed_title="Test",
        mandatory_current=current,
        recovered_history=[invalid_history],
    )

    assert (output / "2026-06-20-weekly-model-recommendations.html").exists()


@pytest.mark.parametrize("current_name", ["current.json", "advisory_report_2026-06-19.json"])
def test_current_report_requires_validated_canonical_basename(tmp_path: Path, current_name: str) -> None:
    current = write_report(tmp_path / current_name, build_v5("2026-06-20"))
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="mandatory_current_filename_invalid"):
        publish_reports(
            [current],
            output,
            site_url="https://example.invalid",
            feed_title="Test",
            mandatory_current=current,
            recovered_history=[],
        )
    assert list(output.iterdir()) == [sentinel]


def test_direct_publisher_cli_rejects_mixed_invalid_before_site_write(tmp_path: Path) -> None:
    valid = write_report(tmp_path / "advisory_report_2026-06-19.json", build_v5("2026-06-19"))
    corrupt = write_report(tmp_path / "advisory_report_2026-06-20.json", "{not-json")
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid_report_candidate"):
        publisher_main(
            ["--reports", str(corrupt), str(valid), "--output-dir", str(output)]
        )
    assert list(output.iterdir()) == [sentinel]


def test_direct_publisher_cli_keeps_all_valid_history_compatibility(tmp_path: Path) -> None:
    first = write_report(tmp_path / "advisory_report_2026-06-19.json", build_v5("2026-06-19"))
    second = write_report(tmp_path / "advisory_report_2026-06-20.json", build_v5("2026-06-20"))
    output = tmp_path / "site"

    publisher_main(["--reports", str(first), str(second), "--output-dir", str(output)])

    assert (output / "index.html").exists()


def test_selected_fingerprint_collision_fails_before_site_write(tmp_path: Path) -> None:
    first = build_v5()
    second = copy.deepcopy(first)
    second["recommendations"][0]["reasons"] = ["different semantic content"]
    first_path = write_report(tmp_path / "first.json", first)
    second_path = write_report(tmp_path / "second.json", second)
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="archive_destination_collision"):
        publish_reports([first_path, second_path], output, site_url="https://example.invalid", feed_title="Test")
    assert list(output.iterdir()) == [sentinel]


def test_missing_mandatory_current_is_stable_and_history_only_all_invalid_fails(tmp_path: Path) -> None:
    history = write_report(tmp_path / "history.json", build_v5())
    with pytest.raises(ValueError, match="mandatory_current_missing"):
        select_publish_candidates(tmp_path / "missing.json", [history])

    invalid = write_report(tmp_path / "invalid.json", "[]")
    with pytest.raises(ValueError, match="no_valid_report_candidates"):
        unique_report_paths_by_content([invalid])


def test_duplicate_canonical_paths_are_validated_once_and_diagnostics_are_sanitized(tmp_path: Path) -> None:
    report_path = write_report(tmp_path / "nested" / "report.json", build_v5())
    selection = select_publish_candidates(None, [report_path, report_path])

    assert selection.selected_paths == (report_path,)
    assert "nested" not in repr(selection.quarantined)
    assert "report.json" not in repr(selection.quarantined)

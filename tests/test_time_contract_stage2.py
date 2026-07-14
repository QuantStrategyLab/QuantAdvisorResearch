from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifacts import write_report_manifest
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report
from quant_advisor_research.publisher import (
    render_feed_xml,
    render_reports_index_json,
    report_content_fingerprint,
)
from quant_advisor_research.time_contract import canonical_reference_time, contract_version_for_schema


ROOT = Path(__file__).resolve().parents[1]


def build_legacy_v5() -> dict:
    return build_advisory_report(
        as_of="2026-05-30", cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def build_v6_from_v5() -> dict:
    report = build_legacy_v5()
    report["schema_version"] = "6"
    report["contract_version"] = "model_recommendations.v6"
    report["reference_time"] = canonical_reference_time(dt.date(2026, 5, 30)).isoformat().replace("+00:00", "Z")
    report["generated_at"] = "2026-05-31T12:00:00.123456Z"
    report["expires_at"] = "2026-06-07T12:00:00.123456Z"
    report["freshness"] = {
        "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
        "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
    }
    return report


def test_v5_v6_dual_read_and_downgrade_disguise_rejection() -> None:
    v5 = build_legacy_v5()
    validate_advisory_report(v5)
    assert contract_version_for_schema(v5["schema_version"]) == "model_recommendations.v5"

    v6 = build_v6_from_v5()
    validate_advisory_report(v6)

    mismatched = dict(v6, contract_version="model_recommendations.v5")
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(mismatched)

    disguised = dict(v6, schema_version="5")
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(disguised)


def test_manifest_contract_version_is_derived_from_report_schema(tmp_path: Path) -> None:
    v5 = build_legacy_v5()
    v6 = build_v6_from_v5()
    outputs = []
    for name, report in (("v5", v5), ("v6", v6)):
        report_path = tmp_path / f"{name}.json"
        markdown_path = tmp_path / f"{name}.md"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        markdown_path.write_text("# report\n", encoding="utf-8")
        manifest = write_report_manifest(
            report=report, report_path=report_path, markdown_path=markdown_path,
            manifest_path=tmp_path / f"{name}.manifest.json",
        )
        outputs.append(json.loads(manifest.read_text(encoding="utf-8")))
    assert outputs[0]["contract_version"] == "model_recommendations.v5"
    assert outputs[1]["contract_version"] == "model_recommendations.v6"


def test_manifest_rejects_malformed_v6_marker_but_preserves_v5_legacy_omission(tmp_path: Path) -> None:
    v5 = build_legacy_v5()
    v6 = build_v6_from_v5()
    for name, report in (("v5", v5), ("v6", v6)):
        report_path = tmp_path / f"{name}.json"
        markdown_path = tmp_path / f"{name}.md"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        markdown_path.write_text("# report\n", encoding="utf-8")
        if name == "v6":
            report.pop("contract_version")
            with pytest.raises(ValueError, match="explicit contract_version"):
                write_report_manifest(
                    report=report, report_path=report_path, markdown_path=markdown_path,
                    manifest_path=tmp_path / f"{name}.manifest.json",
                )
        else:
            manifest = write_report_manifest(
                report=report, report_path=report_path, markdown_path=markdown_path,
                manifest_path=tmp_path / f"{name}.manifest.json",
            )
            assert json.loads(manifest.read_text(encoding="utf-8"))["contract_version"] == "model_recommendations.v5"

    mismatched = build_v6_from_v5()
    mismatched["contract_version"] = "model_recommendations.v5"
    report_path = tmp_path / "mismatched.json"
    markdown_path = tmp_path / "mismatched.md"
    report_path.write_text(json.dumps(mismatched), encoding="utf-8")
    markdown_path.write_text("# report\n", encoding="utf-8")
    with pytest.raises(ValueError, match="do not match"):
        write_report_manifest(
            report=mismatched, report_path=report_path, markdown_path=markdown_path,
            manifest_path=tmp_path / "mismatched.manifest.json",
        )


@pytest.mark.parametrize(
    ("freshness_update", "reason"),
    [
        ({"present": False, "valid": True, "reason": "fresh"}, "valid entries must be present"),
        (
            {
                "present": True, "valid": True, "reason": "fresh",
                "as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z",
                "expires_at": "2026-05-30T23:59:59Z",
            },
            "expired",
        ),
        (
            {
                "present": True, "valid": True, "reason": "fresh",
                "as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z",
                "expires_at": "2026-05-30T11:59:59Z",
            },
            "expires_before_generated",
        ),
        (
            {
                "present": True, "valid": True, "reason": "fresh",
                "as_of": "2026-05-30", "generated_at": "malformed",
                "expires_at": "2026-06-30",
            },
            "invalid_generated_at",
        ),
    ],
)
def test_v6_valid_freshness_uses_shared_fail_closed_semantics(
    freshness_update: dict[str, object], reason: str
) -> None:
    report = build_v6_from_v5()
    report["freshness"]["ai_signal"] = freshness_update
    with pytest.raises(AdvisoryValidationError, match=reason):
        validate_advisory_report(report)


def test_v6_valid_freshness_requires_coherent_source_window() -> None:
    report = build_v6_from_v5()
    report["freshness"]["ai_signal"] = {
        "present": True,
        "valid": True,
        "reason": "fresh",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
        "expires_at": "2026-06-30",
    }
    validate_advisory_report(report)


def test_v5_v6_same_content_fingerprint_ignores_only_volatile_metadata() -> None:
    v5 = build_legacy_v5()
    v6 = build_v6_from_v5()
    v5["summary"]["data_quality_warnings"] = ["ai_signal:compatibility_missing_expires_at", "operator warning"]
    v6["summary"]["data_quality_warnings"] = ["theme_momentum:stale_as_of", "operator warning"]
    assert report_content_fingerprint(v5) == report_content_fingerprint(v6)

    v6["summary"]["data_quality_warnings"] = ["theme_momentum:stale_as_of", "different operator warning"]
    assert report_content_fingerprint(v5) != report_content_fingerprint(v6)


def test_archive_index_and_feed_order_are_deterministic_and_use_actual_pubdate() -> None:
    older = build_legacy_v5()
    newer = build_legacy_v5()
    older["as_of"] = "2026-05-23"
    older["generated_at"] = "2026-05-31T12:00:00.123456Z"
    newer["as_of"] = "2026-05-30"
    newer["generated_at"] = "2026-06-07T12:00:00.654321Z"

    index = json.loads(render_reports_index_json([newer, older]))
    assert [item["as_of"] for item in index["reports"]] == ["2026-05-30", "2026-05-23"]
    feed = render_feed_xml([newer, older], site_url="https://example.invalid/advisor", feed_title="QAR")
    assert "Sun, 07 Jun 2026 12:00:00 GMT" in feed
    assert "Sun, 31 May 2026 12:00:00 GMT" in feed

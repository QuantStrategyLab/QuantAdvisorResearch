from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifacts import write_report_manifest
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report
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


def test_v5_legacy_and_v6_positive_dual_read() -> None:
    validate_advisory_report(build_v5())
    validate_advisory_report(build_v6())


@pytest.mark.parametrize(
    "mutator",
    [
        lambda report: report.pop("contract_version"),
        lambda report: report.update(contract_version="model_recommendations.v5"),
        lambda report: report.update(schema_version=6),
        lambda report: report.update(schema_version=""),
        lambda report: report.update(schema_version="5", reference_time="2026-05-31T00:00:00Z"),
    ],
)
def test_v6_or_downgrade_disguises_fail_closed(mutator) -> None:
    report = build_v6()
    mutator(report)
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_v5_legacy_missing_marker_remains_readable() -> None:
    report = build_v5()
    report.pop("contract_version", None)
    validate_advisory_report(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("as_of", "2026-05-31"),
        ("generated_at", "2026-06-01T00:00:00Z"),
        ("generated_at", "malformed"),
        ("expires_at", "2026-05-30T11:00:00Z"),
    ],
)
def test_v6_report_relative_freshness_validation_is_fail_closed(field: str, value: str) -> None:
    report = build_v6()
    report["freshness"]["ai_signal"] = {
        "present": True,
        "valid": True,
        "reason": "fresh",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
        "expires_at": "2026-06-30",
    }
    report["freshness"]["ai_signal"][field] = value
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_v6_freshness_rejects_reason_and_present_valid_incoherence() -> None:
    report = build_v6()
    report["freshness"]["ai_signal"] = {
        "present": False,
        "valid": True,
        "reason": "fresh",
    }
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)

    report = build_v6()
    report["freshness"]["ai_signal"] = {"present": False, "valid": False, "reason": "fresh"}
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_v6_explicit_legacy_expiry_exception_is_exact() -> None:
    report = build_v6()
    report["freshness"]["ai_signal"] = {
        "present": True,
        "valid": True,
        "reason": "legacy_expiry_compatibility",
        "compatibility_warning": "missing_expires_at",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
    }
    validate_advisory_report(report)

    report["freshness"]["ai_signal"].pop("compatibility_warning")
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_repeated_validation_does_not_depend_on_wall_clock(monkeypatch) -> None:
    report = build_v6()
    monkeypatch.setattr(time, "time", lambda: 0.0)
    validate_advisory_report(report)
    monkeypatch.setattr(time, "time", lambda: 4_000_000_000.0)
    validate_advisory_report(report)


def test_manifest_version_is_report_derived_without_global_v6_contamination(tmp_path: Path) -> None:
    for name, report, expected in (("v5", build_v5(), "model_recommendations.v5"), ("v6", build_v6(), "model_recommendations.v6")):
        report_path = tmp_path / f"{name}.json"
        markdown_path = tmp_path / f"{name}.md"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        markdown_path.write_text("# report\n", encoding="utf-8")
        manifest = write_report_manifest(
            report=report,
            report_path=report_path,
            markdown_path=markdown_path,
            manifest_path=tmp_path / f"{name}.manifest.json",
        )
        assert json.loads(manifest.read_text(encoding="utf-8"))["contract_version"] == expected


def test_manifest_rejects_incomplete_v6_but_keeps_v5_legacy_omission(tmp_path: Path) -> None:
    v5 = build_v5()
    v5.pop("contract_version", None)
    v6 = build_v6()
    v6.pop("contract_version")
    for name, report, should_pass in (("v5", v5, True), ("v6", v6, False)):
        report_path = tmp_path / f"{name}.json"
        markdown_path = tmp_path / f"{name}.md"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        markdown_path.write_text("# report\n", encoding="utf-8")
        if should_pass:
            write_report_manifest(
                report=report,
                report_path=report_path,
                markdown_path=markdown_path,
                manifest_path=tmp_path / f"{name}.manifest.json",
            )
        else:
            with pytest.raises(ValueError):
                write_report_manifest(
                    report=report,
                    report_path=report_path,
                    markdown_path=markdown_path,
                    manifest_path=tmp_path / f"{name}.manifest.json",
                )

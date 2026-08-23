from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifacts import write_report_manifest
from quant_advisor_research.contracts import AdvisoryValidationError, validate_advisory_report
from quant_advisor_research.time_contract import canonical_reference_time


ROOT = Path(__file__).resolve().parents[1]
V6_INPUT_DIGEST = "a" * 64


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
            "input_digest": V6_INPUT_DIGEST,
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


@pytest.mark.parametrize("input_digest", [None, "", "a" * 63, "A" * 64, "sha256:" + "a" * 64, True])
def test_v6_input_digest_is_required_lowercase_sha256(input_digest: object) -> None:
    report = build_v6()
    if input_digest is None:
        report.pop("input_digest")
        expected = "v6_fields_incomplete"
    else:
        report["input_digest"] = input_digest
        expected = "input_digest_invalid"
    with pytest.raises(AdvisoryValidationError, match=expected):
        validate_advisory_report(report)


def test_v5_does_not_silently_accept_v6_input_digest() -> None:
    report = build_v5()
    report["input_digest"] = V6_INPUT_DIGEST
    with pytest.raises(AdvisoryValidationError, match="v6_fields_on_v5"):
        validate_advisory_report(report)


def test_checked_in_v6_contract_fixture_is_readable() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/advisory_report_v6.json").read_text(encoding="utf-8"))
    empty_input_set = {
        name: None
        for name in ("political_events", "political_watchlist", "ai_signal", "theme_momentum", "market_confirmation")
    }
    canonical = json.dumps(empty_input_set, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert fixture["input_digest"] == hashlib.sha256(canonical).hexdigest()
    validate_advisory_report(fixture)


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


@pytest.mark.parametrize("value", [None, ""])
def test_v6_present_false_rejects_timestamp_keys_even_when_falsey(value) -> None:
    report = build_v6()
    report["freshness"]["ai_signal"]["as_of"] = value
    with pytest.raises(AdvisoryValidationError, match="freshness_state_incoherent"):
        validate_advisory_report(report)


@pytest.mark.parametrize(
    "item",
    [
        {
            "present": True, "valid": False, "reason": "as_of_in_future",
            "as_of": "2026-05-31", "generated_at": "2026-05-30T12:00:00Z",
            "expires_at": "2026-06-30",
        },
        {
            "present": True, "valid": False, "reason": "generated_after_reference",
            "as_of": "2026-05-30", "generated_at": "2026-05-31T00:00:00.000001Z",
            "expires_at": "2026-06-30",
        },
        {
            "present": True, "valid": False, "reason": "expires_before_generated",
            "as_of": "2026-05-30", "generated_at": "2026-05-30T12:00:00Z",
            "expires_at": "2026-05-30T11:00:00Z",
        },
    ],
)
def test_v6_accepts_well_formed_canonical_invalid_outcomes(item: dict[str, object]) -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
    report["freshness"]["ai_signal"] = item
    validate_advisory_report(report)


def test_v6_rejects_malformed_invalid_outcome_and_unknown_data_keys() -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
    report["freshness"]["ai_signal"] = {
        "present": True,
        "valid": False,
        "reason": "invalid_generated_at",
        "as_of": "2026-05-30",
        "generated_at": "not-a-time",
        "expires_at": "2026-06-30",
    }
    with pytest.raises(AdvisoryValidationError, match="freshness_assessment_invalid"):
        validate_advisory_report(report)

    report = build_v6()
    report["freshness"]["ai_signal"]["raw_payload"] = {"secret": "must-not-persist"}
    with pytest.raises(AdvisoryValidationError, match="freshness_keys_invalid"):
        validate_advisory_report(report)


def test_v6_rejects_top_level_freshness_extra_key_with_sanitized_error() -> None:
    report = build_v6()
    report["freshness"]["debug"] = {"raw": "redacted"}
    with pytest.raises(AdvisoryValidationError, match="freshness_keys_invalid"):
        validate_advisory_report(report)


def test_v6_requires_freshness_when_source_artifact_is_declared() -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
    with pytest.raises(AdvisoryValidationError, match="source_artifact_freshness_mismatch"):
        validate_advisory_report(report)


@pytest.mark.parametrize("artifact_value", ["", None, [], {"path": "context.json"}])
def test_v6_source_artifact_values_are_minimal_and_coherent(artifact_value) -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = artifact_value
    if isinstance(artifact_value, dict) or isinstance(artifact_value, list):
        expected = "source_artifact_value_invalid"
    else:
        expected = None
    if expected:
        with pytest.raises(AdvisoryValidationError, match=expected):
            validate_advisory_report(report)
    else:
        validate_advisory_report(report)


def test_v6_present_source_requires_nonempty_artifact_and_valid_absent_pair() -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
    report["freshness"]["ai_signal"] = {
        "present": True,
        "valid": True,
        "reason": "fresh",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
        "expires_at": "2026-06-30",
    }
    validate_advisory_report(report)

    report["source_artifacts"].pop("ai_signal")
    with pytest.raises(AdvisoryValidationError, match="source_artifact_freshness_mismatch"):
        validate_advisory_report(report)

    report["source_artifacts"]["ai_signal"] = ""
    with pytest.raises(AdvisoryValidationError, match="source_artifact_freshness_mismatch"):
        validate_advisory_report(report)

    report["source_artifacts"]["theme_momentum"] = "theme.json"
    with pytest.raises(AdvisoryValidationError, match="source_artifact_freshness_mismatch"):
        validate_advisory_report(report)


def test_v6_rejects_field_timestamp_and_reason_mismatch() -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
    item = {
        "present": True,
        "valid": False,
        "reason": "expired",
        "as_of": "2026-05-30",
        "generated_at": "2026-05-30T12:00:00Z",
        "expires_at": "2026-06-30",
    }
    report["freshness"]["ai_signal"] = item
    with pytest.raises(AdvisoryValidationError, match="freshness_state_incoherent"):
        validate_advisory_report(report)

    item["reason"] = "fresh"
    with pytest.raises(AdvisoryValidationError, match="freshness_state_incoherent|freshness_reason_mismatch"):
        validate_advisory_report(report)

    report = build_v6()
    report["freshness"]["ai_signal"] = {"present": False, "valid": False, "reason": "fresh"}
    with pytest.raises(AdvisoryValidationError):
        validate_advisory_report(report)


def test_v6_explicit_legacy_expiry_exception_is_exact() -> None:
    report = build_v6()
    report["source_artifacts"]["ai_signal"] = "context.json"
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
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        assert payload["contract_version"] == expected
        if name == "v6":
            assert payload["input_digest"] == V6_INPUT_DIGEST
        else:
            assert "input_digest" not in payload


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


def test_manifest_uses_exact_on_disk_payload_and_bytes(tmp_path: Path) -> None:
    report = build_v5()
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    raw = (json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    report_path.write_bytes(raw)
    markdown_path.write_text("# report\n", encoding="utf-8")

    manifest = write_report_manifest(
        report=report,
        report_path=report_path,
        markdown_path=markdown_path,
        manifest_path=tmp_path / "report.manifest.json",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["artifacts"]["json"]["sha256"] == hashlib.sha256(raw).hexdigest()

    stale = dict(report, as_of="2026-06-06")
    with pytest.raises(ValueError, match="report_payload_mismatch"):
        write_report_manifest(
            report=stale,
            report_path=report_path,
            markdown_path=markdown_path,
            manifest_path=tmp_path / "stale.manifest.json",
        )


def test_manifest_rejects_malformed_or_mismatched_on_disk_payload(tmp_path: Path) -> None:
    report = build_v5()
    markdown_path = tmp_path / "report.md"
    markdown_path.write_text("# report\n", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="report_payload_invalid"):
        write_report_manifest(
            report=report,
            report_path=report_path,
            markdown_path=markdown_path,
            manifest_path=tmp_path / "malformed.manifest.json",
        )

    on_disk = build_v6()
    on_disk.pop("contract_version")
    report_path.write_text(json.dumps(on_disk), encoding="utf-8")
    with pytest.raises(ValueError, match="report_payload_mismatch"):
        write_report_manifest(
            report=report,
            report_path=report_path,
            markdown_path=markdown_path,
            manifest_path=tmp_path / "mismatch.manifest.json",
        )

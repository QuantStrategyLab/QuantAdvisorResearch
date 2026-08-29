from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.m0_research_source_snapshot import (
    M0_RESEARCH_SOURCE_ID,
    M0_RESEARCH_SOURCE_SNAPSHOT_SCHEMA_VERSION,
    M0ResearchSourceSnapshotError,
    build_m0_research_source_snapshot,
    main,
    validate_m0_research_source_snapshot,
)
from quant_advisor_research.time_contract import canonical_reference_time, normalize_aware_datetime


ROOT = Path(__file__).resolve().parents[1]


def build_report(*, schema_version: str = "5") -> dict:
    report = build_advisory_report(
        as_of="2026-06-20",
        cadence="weekly",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )
    if schema_version == "6":
        generated_at = normalize_aware_datetime(report["generated_at"])
        reference_time = canonical_reference_time(dt.date.fromisoformat(report["as_of"]))
        report.update(
            {
                "schema_version": "6",
                "contract_version": "model_recommendations.v6",
                "reference_time": reference_time.isoformat().replace("+00:00", "Z"),
                "expires_at": (generated_at + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                "input_digest": "a" * 64,
                "freshness": {
                    "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                    "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
                },
            }
        )
    return report


def test_builds_closed_deterministic_ready_snapshot_from_v5_report() -> None:
    report = build_report()

    first = build_m0_research_source_snapshot(report)
    second = build_m0_research_source_snapshot(json.loads(json.dumps(report, sort_keys=True)))

    assert first == second
    assert first["schema_version"] == M0_RESEARCH_SOURCE_SNAPSHOT_SCHEMA_VERSION
    assert first["source_id"] == M0_RESEARCH_SOURCE_ID
    assert first["data_status"] == "ready"
    assert first["errors"] == []
    assert first["computed_at"] == first["generated_at"]
    assert first["source_report_digest"] == first["hypotheses"][0]["provenance"]["source_report_digest"]
    assert all(item["no_order"] is True for item in first["hypotheses"])
    assert all(item["authority"] == "research_only" for item in first["hypotheses"])
    assert all(item["permitted_next_step"] == "research_validation_only" for item in first["hypotheses"])
    assert all("target_weight" not in item for item in first["hypotheses"])
    validate_m0_research_source_snapshot(first)


def test_binds_v6_input_digest_and_report_digest() -> None:
    snapshot = build_m0_research_source_snapshot(build_report(schema_version="6"))

    assert snapshot["hypotheses"]
    assert all(item["provenance"]["source_schema_version"] == "6" for item in snapshot["hypotheses"])
    assert all(item["provenance"]["source_input_digest"] == "a" * 64 for item in snapshot["hypotheses"])
    assert all(
        item["provenance"]["source_report_digest"] == snapshot["source_report_digest"]
        for item in snapshot["hypotheses"]
    )


def test_closed_snapshot_rejects_unbound_hypothesis_or_noncanonical_time() -> None:
    snapshot = build_m0_research_source_snapshot(build_report())
    snapshot["hypotheses"][0]["provenance"]["source_report_digest"] = "b" * 64

    with pytest.raises(M0ResearchSourceSnapshotError, match="source_report_digest_mismatch"):
        validate_m0_research_source_snapshot(snapshot)

    snapshot = build_m0_research_source_snapshot(build_report())
    snapshot["computed_at"] = snapshot["computed_at"].replace("Z", "+00:00")

    with pytest.raises(M0ResearchSourceSnapshotError, match="source_time_invalid"):
        validate_m0_research_source_snapshot(snapshot)


def test_cli_reads_one_report_and_writes_snapshot(tmp_path: Path) -> None:
    report_path = tmp_path / "advisory_report.json"
    output_path = tmp_path / "m0_source_snapshot.json"
    report_path.write_text(json.dumps(build_report()), encoding="utf-8")

    main(["--report", str(report_path), "--output-json", str(output_path)])

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    validate_m0_research_source_snapshot(payload)

from __future__ import annotations

import datetime as dt
import json
import traceback
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

import quant_advisor_research.artifact_integrity as artifact_integrity
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.artifact_integrity import (
    ARTIFACT_INTEGRITY_VERSION,
    ArtifactIntegrityError,
    MAX_SNAPSHOT_DEPTH,
    artifact_integrity_digest,
    make_artifact_integrity_evidence,
)
from quant_advisor_research.publisher import report_content_fingerprint
from quant_advisor_research.period_contract import PeriodContractError
from quant_advisor_research.time_contract import TimeContractError, canonical_reference_time, normalize_aware_datetime


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
                "freshness": {
                    "ai_signal": {"present": False, "valid": False, "reason": "not_provided"},
                    "theme_momentum": {"present": False, "valid": False, "reason": "not_provided"},
                },
            }
        )
    return report


def test_mapping_order_and_readonly_mapping_have_same_digest() -> None:
    report = build_report()
    reordered = OrderedDict(reversed(list(report.items())))

    assert artifact_integrity_digest(report) == artifact_integrity_digest(reordered)
    assert artifact_integrity_digest(report) == artifact_integrity_digest(MappingProxyType(report))


def test_metadata_changes_artifact_digest_but_not_semantic_digest() -> None:
    report = build_report()
    baseline_semantic = report_content_fingerprint(report)
    baseline_artifact = artifact_integrity_digest(report)

    for field, value in (
        ("generated_at", "2026-06-20T00:00:00Z"),
        ("contract_version", "model_recommendations.v5"),
        ("source_artifacts", {"political_events": "different-source.csv"}),
    ):
        changed = dict(report)
        changed[field] = value
        assert report_content_fingerprint(changed) == baseline_semantic
        assert artifact_integrity_digest(changed) != baseline_artifact


@pytest.mark.parametrize("field", ["reference_time", "expires_at", "generated_at"])
def test_v6_time_metadata_changes_artifact_digest_but_not_semantic_digest(field: str) -> None:
    report = build_report(schema_version="6")
    changed = dict(report)
    if field == "reference_time":
        changed["as_of"] = "2026-06-21"
        changed[field] = canonical_reference_time(dt.date(2026, 6, 21)).isoformat().replace("+00:00", "Z")
    elif field == "expires_at":
        generated_at = normalize_aware_datetime(report["generated_at"]) + dt.timedelta(seconds=1)
        changed["generated_at"] = generated_at.isoformat().replace("+00:00", "Z")
        changed[field] = (generated_at + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z")
    else:
        generated_at = normalize_aware_datetime(report[field]) + dt.timedelta(seconds=1)
        changed[field] = generated_at.isoformat().replace("+00:00", "Z")
        changed["expires_at"] = (generated_at + dt.timedelta(days=7)).isoformat().replace("+00:00", "Z")

    assert report_content_fingerprint(changed) == report_content_fingerprint(report)
    assert artifact_integrity_digest(changed) != artifact_integrity_digest(report)


def test_schema_version_change_is_reflected_in_artifact_digest() -> None:
    v5 = build_report()
    v6 = build_report(schema_version="6")

    assert artifact_integrity_digest(v5) != artifact_integrity_digest(v6)


def test_canonical_digest_is_independent_of_json_whitespace() -> None:
    report = build_report()
    compact = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pretty = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    assert json.loads(compact) == json.loads(pretty)
    assert artifact_integrity_digest(json.loads(compact)) == artifact_integrity_digest(json.loads(pretty))


def test_evidence_contains_only_descriptive_metadata() -> None:
    evidence = make_artifact_integrity_evidence(build_report())

    assert evidence.version == ARTIFACT_INTEGRITY_VERSION
    assert len(evidence.digest) == 64
    assert not hasattr(evidence, "report")
    assert not hasattr(evidence, "path")
    assert not hasattr(evidence, "seal")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(unserializable={"bad"}),
        lambda report: report.update(unserializable=Path("secret/path")),
        lambda report: report.update(unserializable=b"bytes"),
        lambda report: report.update(unserializable=("tuple",)),
        lambda report: report.update(unserializable=float("nan")),
        lambda report: report.update(unserializable=float("inf")),
        lambda report: report.update({1: "non-string-key"}),
        lambda report: report.update(unserializable="\ud800"),
    ],
)
def test_invalid_wire_shapes_are_sanitized(mutation) -> None:
    report = build_report()
    mutation(report)

    with pytest.raises(ArtifactIntegrityError, match="report_integrity_invalid"):
        artifact_integrity_digest(report)


def test_circular_and_deep_values_are_sanitized() -> None:
    report = build_report()
    circular: list[object] = []
    circular.append(circular)
    report["circular"] = circular

    with pytest.raises(ArtifactIntegrityError, match="report_integrity_invalid"):
        artifact_integrity_digest(report)

    report = build_report()
    deep: object = "leaf"
    for _ in range(MAX_SNAPSHOT_DEPTH + 2):
        deep = [deep]
    report["deep"] = deep

    with pytest.raises(ArtifactIntegrityError, match="report_integrity_invalid"):
        artifact_integrity_digest(report)


class ExplodingMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("untrusted mapping failure")

    def __iter__(self):
        raise RuntimeError("untrusted mapping failure")

    def __len__(self) -> int:
        return 1


def test_mapping_iteration_failure_is_sanitized() -> None:
    with pytest.raises(ArtifactIntegrityError, match="report_integrity_invalid"):
        artifact_integrity_digest(ExplodingMapping())


def test_snapshot_happens_before_validation_and_hashing() -> None:
    report = build_report()

    class MutatingMapping(Mapping[str, object]):
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value
            self.mutated = False

        def __getitem__(self, key: str) -> object:
            return self.value[key]

        def __iter__(self):
            return iter(self.value)

        def __len__(self) -> int:
            return len(self.value)

        def items(self):
            snapshot = list(self.value.items())
            if not self.mutated:
                self.mutated = True
                self.value["generated_at"] = "not-used-after-snapshot"
            return snapshot

    original = report["generated_at"]
    evidence = make_artifact_integrity_evidence(MutatingMapping(report))
    assert report["generated_at"] != original
    assert evidence.digest == artifact_integrity_digest(dict(report, generated_at=original))


@pytest.mark.parametrize("exception_type", [artifact_integrity.AdvisoryValidationError, TimeContractError, PeriodContractError])
@pytest.mark.parametrize("operation", ["canonicalize", "digest", "evidence"])
def test_known_validator_exceptions_are_sanitized(monkeypatch, exception_type, operation: str) -> None:
    marker = "UNTRUSTED_VALIDATOR_EXCEPTION"

    def raise_known(_report) -> None:
        raise exception_type(marker)

    monkeypatch.setattr(artifact_integrity, "validate_advisory_report", raise_known)
    report = build_report()
    call = {
        "canonicalize": artifact_integrity.canonicalize_validated_report,
        "digest": artifact_integrity_digest,
        "evidence": make_artifact_integrity_evidence,
    }[operation]

    with pytest.raises(ArtifactIntegrityError, match="report_invalid") as error:
        call(report)
    assert error.value.__suppress_context__ is True
    assert marker not in repr(error.value)
    assert marker not in "".join(traceback.format_exception(error.value))


def test_unexpected_runtime_error_is_not_swallowed(monkeypatch) -> None:
    def raise_unexpected(_report) -> None:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(artifact_integrity, "validate_advisory_report", raise_unexpected)

    with pytest.raises(RuntimeError, match="programming failure"):
        artifact_integrity_digest(build_report())

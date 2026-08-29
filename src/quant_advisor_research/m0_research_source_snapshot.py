"""Build closed, deterministic M0 research source snapshots from advisory reports.

This is a deliberately one-way, offline producer.  It reads one already
validated advisory report, projects it with :mod:`m0_research_hypothesis`, and
writes the transport envelope consumed by the read-only M0 research ledger.
It has no scheduler, network, strategy, runtime, platform, allocation, or
execution dependency.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifact_integrity import ArtifactIntegrityError, artifact_integrity_digest, snapshot_json_wire
from .artifacts import write_json
from .m0_research_hypothesis import (
    M0ResearchHypothesisValidationError,
    adapt_advisory_report_to_m0_hypotheses,
    validate_m0_research_hypothesis,
)
from .time_contract import TimeContractError, normalize_aware_datetime


M0_RESEARCH_SOURCE_SNAPSHOT_SCHEMA_VERSION = "qsl_m0_research_source_snapshot.v1"
M0_RESEARCH_SOURCE_ID = "quant-advisor-research"
M0_RESEARCH_SOURCE_STATUS = "ready"

_SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "source_id",
        "source_report_digest",
        "generated_at",
        "computed_at",
        "data_status",
        "hypotheses",
        "errors",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class M0ResearchSourceSnapshotError(ValueError):
    """Raised when an M0 source snapshot cannot be built or validated."""


def _iso_utc(value: str) -> str:
    try:
        return normalize_aware_datetime(value).isoformat().replace("+00:00", "Z")
    except (TimeContractError, TypeError, ValueError) as exc:
        raise M0ResearchSourceSnapshotError("source_generated_at_invalid") from exc


def _require_exact_snapshot(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _SNAPSHOT_KEYS:
        raise M0ResearchSourceSnapshotError("source_snapshot_keys_invalid")
    return dict(payload)


def validate_m0_research_source_snapshot(payload: Mapping[str, Any]) -> None:
    """Validate the closed ``qsl_m0_research_source_snapshot.v1`` ready shape.

    QuantAdvisorResearch only emits ``ready`` snapshots.  Source failures are
    fail-closed exceptions rather than partial transport records, so an
    invalid report can never be mistaken for an empty research signal.
    """

    snapshot = _require_exact_snapshot(payload)
    if snapshot["schema_version"] != M0_RESEARCH_SOURCE_SNAPSHOT_SCHEMA_VERSION:
        raise M0ResearchSourceSnapshotError("source_snapshot_schema_invalid")
    if snapshot["source_id"] != M0_RESEARCH_SOURCE_ID or not _IDENTIFIER_RE.fullmatch(snapshot["source_id"]):
        raise M0ResearchSourceSnapshotError("source_id_invalid")
    source_report_digest = snapshot["source_report_digest"]
    if not isinstance(source_report_digest, str) or not _SHA256_RE.fullmatch(source_report_digest):
        raise M0ResearchSourceSnapshotError("source_report_digest_invalid")
    if snapshot["data_status"] != M0_RESEARCH_SOURCE_STATUS:
        raise M0ResearchSourceSnapshotError("source_data_status_invalid")
    if snapshot["errors"] != []:
        raise M0ResearchSourceSnapshotError("ready_source_errors_invalid")

    generated_at = snapshot["generated_at"]
    computed_at = snapshot["computed_at"]
    if not isinstance(generated_at, str) or not isinstance(computed_at, str):
        raise M0ResearchSourceSnapshotError("source_time_invalid")
    canonical_generated_at = _iso_utc(generated_at)
    canonical_computed_at = _iso_utc(computed_at)
    if generated_at != canonical_generated_at or computed_at != canonical_computed_at:
        raise M0ResearchSourceSnapshotError("source_time_invalid")
    # The producer intentionally has no wall-clock input.  A source report
    # always yields the same snapshot timestamp, including during replays.
    if computed_at != generated_at:
        raise M0ResearchSourceSnapshotError("source_time_invalid")

    hypotheses = snapshot["hypotheses"]
    if not isinstance(hypotheses, list) or len(hypotheses) > 500:
        raise M0ResearchSourceSnapshotError("source_hypotheses_invalid")
    hypothesis_ids: set[str] = set()
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping):
            raise M0ResearchSourceSnapshotError("source_hypothesis_invalid")
        try:
            validate_m0_research_hypothesis(hypothesis)
        except M0ResearchHypothesisValidationError as exc:
            raise M0ResearchSourceSnapshotError("source_hypothesis_invalid") from exc
        hypothesis_id = hypothesis["hypothesis_id"]
        if hypothesis_id in hypothesis_ids:
            raise M0ResearchSourceSnapshotError("source_hypothesis_duplicate")
        hypothesis_ids.add(hypothesis_id)
        provenance = hypothesis["provenance"]
        if provenance["source_report_digest"] != source_report_digest:
            raise M0ResearchSourceSnapshotError("source_report_digest_mismatch")
        if hypothesis["generated_at"] != generated_at:
            raise M0ResearchSourceSnapshotError("source_hypothesis_time_invalid")


def build_m0_research_source_snapshot(report: Mapping[str, Any]) -> dict[str, object]:
    """Build one read-only ready snapshot from a validated v5 or v6 report.

    ``source_report_digest`` is the full validated report digest, not a file
    digest.  It therefore binds the transport output to the exact public
    report semantics and metadata even when equivalent JSON is re-formatted.
    """

    try:
        report_snapshot = snapshot_json_wire(report)
        hypotheses = adapt_advisory_report_to_m0_hypotheses(report_snapshot)
        source_report_digest = artifact_integrity_digest(report_snapshot)
    except (
        ArtifactIntegrityError,
        M0ResearchHypothesisValidationError,
        TypeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise M0ResearchSourceSnapshotError("source_report_invalid") from exc

    generated_at = _iso_utc(str(report_snapshot["generated_at"]))
    snapshot: dict[str, object] = {
        "schema_version": M0_RESEARCH_SOURCE_SNAPSHOT_SCHEMA_VERSION,
        "source_id": M0_RESEARCH_SOURCE_ID,
        "source_report_digest": source_report_digest,
        "generated_at": generated_at,
        "computed_at": generated_at,
        "data_status": M0_RESEARCH_SOURCE_STATUS,
        "hypotheses": sorted(hypotheses, key=lambda item: str(item["hypothesis_id"])),
        "errors": [],
    }
    validate_m0_research_source_snapshot(snapshot)
    return snapshot


def load_advisory_report(path: str | Path) -> dict[str, object]:
    """Read one local JSON report without network or artifact discovery."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M0ResearchSourceSnapshotError("source_report_unreadable") from exc
    if not isinstance(payload, Mapping):
        raise M0ResearchSourceSnapshotError("source_report_invalid")
    try:
        return snapshot_json_wire(payload)
    except ArtifactIntegrityError as exc:
        raise M0ResearchSourceSnapshotError("source_report_invalid") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a closed, offline M0 research source snapshot from one advisory report.")
    parser.add_argument("--report", required=True, help="Validated v5 or v6 advisory report JSON path.")
    parser.add_argument("--output-json", required=True, help="Destination for qsl_m0_research_source_snapshot.v1 JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    report = load_advisory_report(args.report)
    snapshot = build_m0_research_source_snapshot(report)
    write_json(args.output_json, snapshot)


if __name__ == "__main__":
    main()

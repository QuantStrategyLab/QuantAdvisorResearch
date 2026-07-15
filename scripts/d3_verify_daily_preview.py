#!/usr/bin/env python3
"""Verify a downloaded D3 bundle against the complete build evidence payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from quant_advisor_research.preview_bundle import read_preview_bundle

EVIDENCE_VERSION = "qar.d3.build_evidence.v1"
FIXED_FILES = ("manifest.json", "report.html", "report.json")
EVIDENCE_KEYS = {"evidence_version", "base_sha", "source", "deterministic_clock", "bundle", "repeat_build"}
DEPENDENCY_INVENTORY = [
    ".github/workflows/qar_d3_daily_preview_artifact.yml",
    "scripts/d3_build_daily_preview.py",
    "scripts/d3_verify_daily_preview.py",
    "src/quant_advisor_research/advisory_report.py",
    "src/quant_advisor_research/artifact_integrity.py",
    "src/quant_advisor_research/artifacts.py",
    "src/quant_advisor_research/contracts.py",
    "src/quant_advisor_research/csv_utils.py",
    "src/quant_advisor_research/period_contract.py",
    "src/quant_advisor_research/preview_bundle.py",
    "src/quant_advisor_research/preview_workspace.py",
    "src/quant_advisor_research/time_contract.py",
    "tests/test_d3_preview_artifact.py",
    "examples/political_events.example.csv",
    "examples/political_watchlist.example.csv",
    "pyproject.toml",
]


def _file_hashes(workspace: Path) -> dict[str, dict[str, object]]:
    return {
        name: {"sha256": hashlib.sha256((workspace / name).read_bytes()).hexdigest(), "size": (workspace / name).stat().st_size}
        for name in FIXED_FILES
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify(*, workspace: Path, evidence_path: Path, expected_base_sha: str, expected_as_of: str, expected_events: str, expected_watchlist: str, frozen_generated_at: str) -> dict[str, object]:
    if any(not Path(path).is_file() for path in DEPENDENCY_INVENTORY):
        raise ValueError("dependency_inventory_invalid")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_KEYS | {"workflow_dependency_inventory"}:
        raise ValueError("evidence_shape_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_base_sha):
        raise ValueError("base_sha_invalid")
    read_preview_bundle(workspace)
    if {path.name for path in workspace.iterdir()} != set(FIXED_FILES):
        raise ValueError("file_set_invalid")
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    if (workspace / "manifest.json").read_bytes() != _canonical_json(manifest):
        raise ValueError("manifest_noncanonical")
    files = _file_hashes(workspace)
    expected = {
        "evidence_version": EVIDENCE_VERSION,
        "base_sha": expected_base_sha,
        "source": {
            "fixture_paths": [Path(expected_events).as_posix(), Path(expected_watchlist).as_posix()],
            "provenance": "repository_representative_fixture",
        },
        "deterministic_clock": {"frozen_generated_at": frozen_generated_at, "producer_invocations": 2},
        "workflow_dependency_inventory": DEPENDENCY_INVENTORY,
        "bundle": {"contract": "qar.preview_bundle.v1", "source": manifest["source"], "files": files},
        "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": files},
    }
    if evidence != expected:
        raise ValueError("build_evidence_mismatch")
    source = manifest.get("source", {})
    if source != {
        "schema_version": "5",
        "contract_version": "model_recommendations.v5",
        "cadence": "daily",
        "as_of": expected_as_of,
        "generated_at": frozen_generated_at,
    }:
        raise ValueError("source_contract_mismatch")
    result = {"status": "passed", "base_sha": expected_base_sha, "files": files, "bundle_contract": manifest["bundle_contract"], "readback": "passed", "evidence_binding": "exact_full_payload"}
    print(json.dumps(result, sort_keys=True))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--evidence-path", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--political-events", required=True)
    parser.add_argument("--political-watchlist", required=True)
    parser.add_argument("--frozen-generated-at", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    verify(
        workspace=args.workspace,
        evidence_path=args.evidence_path,
        expected_base_sha=args.base_sha,
        expected_as_of=args.as_of,
        expected_events=args.political_events,
        expected_watchlist=args.political_watchlist,
        frozen_generated_at=args.frozen_generated_at,
    )

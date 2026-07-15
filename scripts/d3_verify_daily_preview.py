#!/usr/bin/env python3
"""Workflow-only downloaded artifact verifier with exact environment binding."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from d3_evidence import DEPENDENCY_INVENTORY, locked_environment_evidence
from quant_advisor_research.preview_bundle import read_preview_bundle

EVIDENCE_VERSION = "qar.d3.build_evidence.v2"
FIXED_FILES = ("manifest.json", "report.html", "report.json")
EXPECTED_EVIDENCE_KEYS = frozenset({
    "evidence_version", "base_sha", "source", "deterministic_clock", "workflow_dependency_inventory",
    "locked_environment", "bundle", "repeat_build",
})


def _file_hashes(workspace: Path) -> dict[str, dict[str, object]]:
    return {name: {"sha256": hashlib.sha256((workspace / name).read_bytes()).hexdigest(), "size": (workspace / name).stat().st_size} for name in FIXED_FILES}


def _distributions() -> list[str]:
    return sorted({f"{name}=={dist.version}" for dist in importlib.metadata.distributions() if (name := dist.metadata.get("Name"))})


def verify(args: argparse.Namespace) -> None:
    evidence = json.loads(Path(args.evidence_path).read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or set(evidence) != EXPECTED_EVIDENCE_KEYS:
        raise ValueError("build_evidence_shape_invalid")
    if evidence.get("workflow_dependency_inventory") != DEPENDENCY_INVENTORY:
        raise ValueError("dependency_inventory_mismatch")
    expected_environment = locked_environment_evidence(lock_sha256=hashlib.sha256(Path(args.lock_path).read_bytes()).hexdigest(), uv_version=args.uv_version, python_version=platform.python_version(), distributions=_distributions())
    expected_source = {"schema_version": "5", "contract_version": "model_recommendations.v5", "cadence": "daily", "as_of": args.as_of, "generated_at": args.frozen_generated_at}
    workspace = Path(args.workspace); read_preview_bundle(workspace)
    if {p.name for p in workspace.iterdir()} != set(FIXED_FILES): raise ValueError("file_set_invalid")
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source") != expected_source or manifest.get("bundle_contract") != "qar.preview_bundle.v1": raise ValueError("source_contract_mismatch")
    files = _file_hashes(workspace)
    expected = {"evidence_version": EVIDENCE_VERSION, "base_sha": args.base_sha, "source": {"fixture_paths": [Path(args.political_events).as_posix(), Path(args.political_watchlist).as_posix()], "provenance": "repository_representative_fixture"}, "deterministic_clock": {"frozen_generated_at": args.frozen_generated_at, "producer_invocations": 2}, "workflow_dependency_inventory": DEPENDENCY_INVENTORY, "locked_environment": expected_environment, "bundle": {"contract": "qar.preview_bundle.v1", "source": expected_source, "files": files}, "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": files}}
    if evidence != expected: raise ValueError("build_evidence_mismatch")
    print(json.dumps({"status": "passed", "evidence_binding": "exact_full_payload", "base_sha": args.base_sha, "files": files}, sort_keys=True))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(); p.add_argument("--workspace", required=True); p.add_argument("--evidence-path", required=True); p.add_argument("--base-sha", required=True); p.add_argument("--uv-version", required=True); p.add_argument("--lock-path", required=True); p.add_argument("--as-of", required=True); p.add_argument("--political-events", required=True); p.add_argument("--political-watchlist", required=True); p.add_argument("--frozen-generated-at", required=True); return p.parse_args()


if __name__ == "__main__": verify(parse_args())

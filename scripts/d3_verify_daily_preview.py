#!/usr/bin/env python3
"""Verify downloaded D3 bundle and complete evidence binding."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from d3_evidence import DEPENDENCY_INVENTORY, EVIDENCE_VERSION, BundleSnapshot, EvidenceContractError, locked_environment_evidence, repository_file_hashes, validate_exact_bundle, validate_preview_snapshot

EXPECTED_KEYS = frozenset({"evidence_version", "base_sha", "head_sha", "source", "deterministic_clock", "workflow_dependency_inventory", "dependency_files", "locked_environment", "bundle", "repeat_build"})


def _distributions() -> list[str]:
    return sorted({f"{name}=={dist.version}" for dist in importlib.metadata.distributions() if (name := dist.metadata.get("Name"))})


def _hashes(snapshot: BundleSnapshot) -> dict[str, dict[str, object]]:
    return {item.name: {"sha256": item.sha256, "size": len(item.content)} for item in snapshot.members}


def verify(args: argparse.Namespace) -> None:
    try:
        evidence = json.loads(Path(args.evidence_path).read_text(encoding="utf-8"))
        if not isinstance(evidence, dict) or set(evidence) != EXPECTED_KEYS:
            raise EvidenceContractError("build_evidence_shape_invalid")
        dependency_files = repository_file_hashes(args.repo_root, DEPENDENCY_INVENTORY)
        if evidence["workflow_dependency_inventory"] != DEPENDENCY_INVENTORY or evidence["dependency_files"] != dependency_files:
            raise EvidenceContractError("dependency_evidence_mismatch")
        environment = locked_environment_evidence(lock_sha256=hashlib.sha256(Path(args.lock_path).read_bytes()).hexdigest(), uv_version=args.uv_version, python_version=platform.python_version(), distributions=_distributions())
        expected_source = {"schema_version": "5", "contract_version": "model_recommendations.v5", "cadence": "daily", "as_of": args.as_of, "generated_at": args.frozen_generated_at}
        snapshot = validate_exact_bundle(args.workspace)
        _, manifest = validate_preview_snapshot(snapshot)
        if manifest.get("bundle_contract") != "qar.preview_bundle.v1" or manifest.get("source") != expected_source:
            raise EvidenceContractError("source_contract_mismatch")
        files = _hashes(snapshot)
        expected = {
            "evidence_version": EVIDENCE_VERSION, "base_sha": args.base_sha, "head_sha": args.head_sha,
            "source": {"fixture_paths": [Path(args.political_events).as_posix(), Path(args.political_watchlist).as_posix()], "provenance": "repository_representative_fixture"},
            "deterministic_clock": {"frozen_generated_at": args.frozen_generated_at, "producer_invocations": 2},
            "workflow_dependency_inventory": DEPENDENCY_INVENTORY, "dependency_files": dependency_files,
            "locked_environment": environment,
            "bundle": {"contract": "qar.preview_bundle.v1", "source": expected_source, "files": files},
            "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": files},
        }
        if evidence != expected:
            raise EvidenceContractError("build_evidence_mismatch")
        print(json.dumps({"status": "passed", "evidence_binding": "exact_full_payload_and_bundle_members", "base_sha": args.base_sha, "head_sha": args.head_sha, "files": files}, sort_keys=True))
    except EvidenceContractError as exc:
        raise RuntimeError(exc.code) from None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    for name in ("workspace", "evidence-path", "base-sha", "head-sha", "uv-version", "lock-path", "repo-root", "as-of", "political-events", "political-watchlist", "frozen-generated-at"):
        p.add_argument(f"--{name}", required=True)
    return p.parse_args()


if __name__ == "__main__":
    verify(parse_args())

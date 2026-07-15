#!/usr/bin/env python3
"""Build two frozen-clock representative daily previews and bind evidence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from d3_evidence import DEPENDENCY_INVENTORY, EVIDENCE_VERSION, EvidenceContractError, locked_environment_evidence, repository_file_hashes, validate_exact_bundle
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.preview_bundle import read_preview_bundle
from quant_advisor_research.preview_workspace import build_preview_workspace


def _distributions() -> list[str]:
    return sorted({f"{name}=={dist.version}" for dist in importlib.metadata.distributions() if (name := dist.metadata.get("Name"))})


def _build_report(args: argparse.Namespace) -> dict[str, object]:
    with patch("quant_advisor_research.advisory_report.utc_now_iso", return_value=args.frozen_generated_at):
        return build_advisory_report(as_of=args.as_of, cadence="daily", political_events_path=Path(args.political_events), political_watchlist_path=Path(args.political_watchlist))


def _bundle_hashes(workspace: Path) -> dict[str, dict[str, object]]:
    members = validate_exact_bundle(workspace)
    result = {}
    for name, path in members.items():
        content = path.read_bytes()
        result[name] = {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
    return result


def build_evidence(args: argparse.Namespace) -> None:
    try:
        dependency_files = repository_file_hashes(args.repo_root, DEPENDENCY_INVENTORY)
        lock_sha = hashlib.sha256(Path(args.lock_path).read_bytes()).hexdigest()
        environment = locked_environment_evidence(lock_sha256=lock_sha, uv_version=args.uv_version, python_version=platform.python_version(), distributions=_distributions())
        if not re.fullmatch(r"[0-9a-f]{40}", args.base_sha) or not re.fullmatch(r"[0-9a-f]{40}", args.head_sha):
            raise EvidenceContractError("provenance_sha_invalid")
        parent = Path(tempfile.mkdtemp(prefix="qar-d3-parent-", dir=args.temp_root))
        first = build_preview_workspace(_build_report(args), parent)
        second = build_preview_workspace(_build_report(args), parent)
        first_members = validate_exact_bundle(first)
        second_members = validate_exact_bundle(second)
        read_preview_bundle(first); read_preview_bundle(second)
        first_files, second_files = _bundle_hashes(first), _bundle_hashes(second)
        if first_files != second_files or any(first_members[name].read_bytes() != second_members[name].read_bytes() for name in first_members):
            raise EvidenceContractError("repeat_build_not_equal")
        manifest = json.loads(first_members["manifest.json"].read_text(encoding="utf-8"))
        source = {"schema_version": "5", "contract_version": "model_recommendations.v5", "cadence": "daily", "as_of": args.as_of, "generated_at": args.frozen_generated_at}
        if manifest.get("bundle_contract") != "qar.preview_bundle.v1" or manifest.get("source") != source:
            raise EvidenceContractError("source_contract_mismatch")
        evidence = {
            "evidence_version": EVIDENCE_VERSION, "base_sha": args.base_sha, "head_sha": args.head_sha,
            "source": {"fixture_paths": [Path(args.political_events).as_posix(), Path(args.political_watchlist).as_posix()], "provenance": "repository_representative_fixture"},
            "deterministic_clock": {"frozen_generated_at": args.frozen_generated_at, "producer_invocations": 2},
            "workflow_dependency_inventory": DEPENDENCY_INVENTORY, "dependency_files": dependency_files,
            "locked_environment": environment,
            "bundle": {"contract": "qar.preview_bundle.v1", "source": source, "files": first_files},
            "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": second_files},
        }
        evidence_path = Path(args.evidence_path)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        Path(args.workspace_path_file).write_text(str(first) + "\n", encoding="utf-8")
        print(json.dumps({"workspace": str(first), "evidence": str(evidence_path), "base_sha": args.base_sha, "head_sha": args.head_sha}, sort_keys=True))
    except EvidenceContractError as exc:
        raise RuntimeError(exc.code) from None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    for name in ("as-of", "political-events", "political-watchlist", "frozen-generated-at", "base-sha", "head-sha", "uv-version", "lock-path", "repo-root", "temp-root", "evidence-path", "workspace-path-file"):
        p.add_argument(f"--{name}", required=True)
    return p.parse_args()


if __name__ == "__main__":
    build_evidence(parse_args())

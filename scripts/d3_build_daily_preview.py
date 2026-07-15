#!/usr/bin/env python3
"""Workflow-only D3 builder; uv discovery is never imported by ordinary tests."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from d3_evidence import DEPENDENCY_INVENTORY, locked_environment_evidence
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.preview_bundle import read_preview_bundle
from quant_advisor_research.preview_workspace import build_preview_workspace

EVIDENCE_VERSION = "qar.d3.build_evidence.v2"
FIXED_FILES = ("manifest.json", "report.html", "report.json")


def _file_hashes(workspace: Path) -> dict[str, dict[str, object]]:
    return {name: {"sha256": hashlib.sha256((workspace / name).read_bytes()).hexdigest(), "size": (workspace / name).stat().st_size} for name in FIXED_FILES}


def _distributions() -> list[str]:
    return sorted({f"{name}=={dist.version}" for dist in importlib.metadata.distributions() if (name := dist.metadata.get("Name"))})


def _report(as_of: str, events: Path, watchlist: Path, generated_at: str) -> dict[str, object]:
    with patch("quant_advisor_research.advisory_report.utc_now_iso", return_value=generated_at):
        return build_advisory_report(as_of=as_of, cadence="daily", political_events_path=events, political_watchlist_path=watchlist)


def build_evidence(args: argparse.Namespace) -> Path:
    if any(not Path(item).is_file() for item in DEPENDENCY_INVENTORY):
        raise RuntimeError("dependency_inventory_invalid")
    lock_path = Path(args.lock_path)
    environment = locked_environment_evidence(
        lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        uv_version=args.uv_version,
        python_version=platform.python_version(),
        distributions=_distributions(),
    )
    parent = Path(tempfile.mkdtemp(prefix="qar-d3-parent-", dir=args.temp_root))
    succeeded = False
    try:
        first = build_preview_workspace(_report(args.as_of, Path(args.political_events), Path(args.political_watchlist), args.frozen_generated_at), parent)
        second = build_preview_workspace(_report(args.as_of, Path(args.political_events), Path(args.political_watchlist), args.frozen_generated_at), parent)
        read_preview_bundle(first); read_preview_bundle(second)
        first_files, second_files = _file_hashes(first), _file_hashes(second)
        if first_files != second_files or any((first / n).read_bytes() != (second / n).read_bytes() for n in FIXED_FILES):
            raise RuntimeError("repeat_build_not_equal")
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        source = {"schema_version": "5", "contract_version": "model_recommendations.v5", "cadence": "daily", "as_of": args.as_of, "generated_at": args.frozen_generated_at}
        if manifest.get("source") != source or manifest.get("bundle_contract") != "qar.preview_bundle.v1":
            raise RuntimeError("source_contract_mismatch")
        if not re.fullmatch(r"[0-9a-f]{40}", args.base_sha):
            raise RuntimeError("base_sha_invalid")
        evidence = {
            "evidence_version": EVIDENCE_VERSION, "base_sha": args.base_sha,
            "source": {"fixture_paths": [Path(args.political_events).as_posix(), Path(args.political_watchlist).as_posix()], "provenance": "repository_representative_fixture"},
            "deterministic_clock": {"frozen_generated_at": args.frozen_generated_at, "producer_invocations": 2},
            "workflow_dependency_inventory": DEPENDENCY_INVENTORY,
            "locked_environment": environment,
            "bundle": {"contract": manifest["bundle_contract"], "source": source, "files": first_files},
            "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": second_files},
        }
        evidence_path = Path(args.evidence_path); evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        Path(args.workspace_path_file).write_text(str(first) + "\n", encoding="utf-8")
        succeeded = True
        print(json.dumps({"workspace": str(first), "evidence": str(evidence_path), "base_sha": args.base_sha}, sort_keys=True))
        return first
    finally:
        if not succeeded:
            try: parent.rmdir()
            except OSError: pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(); p.add_argument("--as-of", required=True); p.add_argument("--political-events", required=True); p.add_argument("--political-watchlist", required=True); p.add_argument("--frozen-generated-at", required=True); p.add_argument("--base-sha", required=True); p.add_argument("--uv-version", required=True); p.add_argument("--lock-path", required=True); p.add_argument("--temp-root", required=True); p.add_argument("--evidence-path", required=True); p.add_argument("--workspace-path-file", required=True); return p.parse_args()


if __name__ == "__main__": build_evidence(parse_args())

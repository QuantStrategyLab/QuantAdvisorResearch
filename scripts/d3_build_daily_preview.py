#!/usr/bin/env python3
"""Build two frozen-clock representative daily preview workspaces and evidence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.preview_bundle import read_preview_bundle
from quant_advisor_research.preview_workspace import build_preview_workspace

EVIDENCE_VERSION = "qar.d3.build_evidence.v1"
FIXED_FILES = ("manifest.json", "report.html", "report.json")
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


def _base_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _file_hashes(workspace: Path) -> dict[str, dict[str, object]]:
    return {
        name: {"sha256": hashlib.sha256((workspace / name).read_bytes()).hexdigest(), "size": (workspace / name).stat().st_size}
        for name in FIXED_FILES
    }


def _installed_distributions() -> tuple[list[str], str]:
    lines = sorted(
        f"{name}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
        if (name := distribution.metadata.get("Name"))
    )
    return lines, hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _build_report(*, as_of: str, events: Path, watchlist: Path, frozen_generated_at: str) -> dict[str, object]:
    with patch("quant_advisor_research.advisory_report.utc_now_iso", return_value=frozen_generated_at):
        return build_advisory_report(
            as_of=as_of,
            cadence="daily",
            political_events_path=events,
            political_watchlist_path=watchlist,
        )


def build_evidence(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    if any(not Path(path).is_file() for path in DEPENDENCY_INVENTORY):
        raise RuntimeError("dependency_inventory_invalid")
    lock_path = Path(args.lock_path)
    lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    distributions, distributions_sha256 = _installed_distributions()
    temp_root = Path(args.temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix="qar-d3-parent-", dir=temp_root))
    succeeded = False
    try:
        first_report = _build_report(
            as_of=args.as_of,
            events=Path(args.political_events),
            watchlist=Path(args.political_watchlist),
            frozen_generated_at=args.frozen_generated_at,
        )
        second_report = _build_report(
            as_of=args.as_of,
            events=Path(args.political_events),
            watchlist=Path(args.political_watchlist),
            frozen_generated_at=args.frozen_generated_at,
        )
        first = build_preview_workspace(first_report, parent)
        second = build_preview_workspace(second_report, parent)
        read_preview_bundle(first)
        read_preview_bundle(second)
        first_files = _file_hashes(first)
        second_files = _file_hashes(second)
        if first_files != second_files or any((first / name).read_bytes() != (second / name).read_bytes() for name in FIXED_FILES):
            raise RuntimeError("repeat_build_not_equal")
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        source = manifest["source"]
        base_sha = args.base_sha or _base_sha()
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise RuntimeError("base_sha_invalid")
        if source != {
            "schema_version": "5",
            "contract_version": "model_recommendations.v5",
            "cadence": "daily",
            "as_of": args.as_of,
            "generated_at": args.frozen_generated_at,
        }:
            raise RuntimeError("source_contract_mismatch")
        evidence = {
            "evidence_version": EVIDENCE_VERSION,
            "base_sha": base_sha,
            "source": {
                "fixture_paths": [Path(args.political_events).as_posix(), Path(args.political_watchlist).as_posix()],
                "provenance": "repository_representative_fixture",
            },
            "deterministic_clock": {"frozen_generated_at": args.frozen_generated_at, "producer_invocations": 2},
            "locked_environment": {
                "lockfile": lock_path.as_posix(),
                "lock_sha256": lock_sha256,
                "uv_version": args.uv_version,
                "python_version": __import__("platform").python_version(),
                "installed_distributions": distributions,
                "installed_distributions_sha256": distributions_sha256,
            },
            "workflow_dependency_inventory": DEPENDENCY_INVENTORY,
            "bundle": {
                "contract": manifest["bundle_contract"],
                "source": source,
                "files": first_files,
            },
            "repeat_build": {"independent_invocations": 2, "bytes_equal": True, "files": second_files},
        }
        evidence_path = Path(args.evidence_path)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        Path(args.workspace_path_file).write_text(str(first) + "\n", encoding="utf-8")
        print(json.dumps({"workspace": str(first), "evidence": str(evidence_path), "base_sha": evidence["base_sha"]}, sort_keys=True))
        succeeded = True
        return first, evidence
    finally:
        if not succeeded:
            try:
                parent.rmdir()
            except OSError:
                shutil.rmtree(parent, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--political-events", required=True)
    parser.add_argument("--political-watchlist", required=True)
    parser.add_argument("--frozen-generated-at", required=True)
    parser.add_argument("--temp-root", default=os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--workspace-path-file", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--uv-version", required=True)
    parser.add_argument("--lock-path", default="uv.lock")
    return parser.parse_args()


if __name__ == "__main__":
    build_evidence(parse_args())

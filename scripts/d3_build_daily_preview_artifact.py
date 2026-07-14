#!/usr/bin/env python3
"""Build and locally verify the D3 representative daily preview artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quant_advisor_research import advisory_report
from quant_advisor_research.preview_bundle import PreviewBundleError, build_preview_bundle, read_preview_bundle


BASE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SOURCE_KIND = "repository_representative_fixture"
SOURCE_SCHEMA_VERSION = "5"
SOURCE_CONTRACT_VERSION = "model_recommendations.v5"
BUNDLE_CONTRACT = "qar.preview_bundle.v1"
CHECKS = [
    "exact_three_files",
    "canonical_json_readback",
    "manifest_hashes",
    "manifest_source_pair",
    "relative_html_links",
    "repeat_build_bytes",
]


def _require_base_sha(value: str) -> str:
    if BASE_SHA_PATTERN.fullmatch(value) is None:
        raise PreviewBundleError("base_sha_invalid")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_contract(report: dict[str, object], manifest: dict[str, object]) -> None:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise PreviewBundleError("contract_drift")
    if report.get("schema_version") != SOURCE_SCHEMA_VERSION or report.get("cadence") != "daily":
        raise PreviewBundleError("contract_drift")
    if manifest.get("bundle_contract") != BUNDLE_CONTRACT:
        raise PreviewBundleError("contract_drift")
    expected_source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "contract_version": SOURCE_CONTRACT_VERSION,
        "cadence": "daily",
        "as_of": report.get("as_of"),
        "generated_at": report.get("generated_at"),
    }
    if source != expected_source:
        raise PreviewBundleError("contract_drift")


def _evidence(
    *, output: Path, report: dict[str, object], manifest: dict[str, object], base_sha: str, repeat_equal: bool
) -> dict[str, object]:
    return {
        "source_kind": SOURCE_KIND,
        "base_sha": base_sha,
        "bundle_contract": BUNDLE_CONTRACT,
        "source": {
            "cadence": report["cadence"],
            "as_of": report["as_of"],
            "generated_at": report["generated_at"],
            "schema_version": report["schema_version"],
        },
        "provenance": {
            "political_events": "examples/political_events.example.csv",
            "political_watchlist": "examples/political_watchlist.example.csv",
        },
        "files": sorted(path.name for path in output.iterdir()),
        "sha256": {name: _sha256(output / name) for name in ("manifest.json", "report.html", "report.json")},
        "manifest_source": manifest["source"],
        "html_links": ["report.json", "manifest.json"],
        "checks": CHECKS,
        "repeat_build_bytes": repeat_equal,
        "deterministic_clock": {"mode": "frozen_harness", "generated_at": report["generated_at"]},
    }


def build(args: argparse.Namespace) -> None:
    base_sha = _require_base_sha(args.base_sha)
    output = Path(args.artifact_dir)
    events = Path(args.political_events)
    watchlist = Path(args.political_watchlist)
    if not events.is_file() or not watchlist.is_file():
        raise PreviewBundleError("fixture_missing")
    if not args.frozen_generated_at:
        raise PreviewBundleError("frozen_generated_at_required")
    repeat_parent = Path(tempfile.mkdtemp(prefix=f".{output.name}.repeat-", dir=output.parent))
    try:
        repeat_output = repeat_parent / "preview"
        with patch.object(advisory_report, "utc_now_iso", return_value=args.frozen_generated_at):
            first_report = advisory_report.build_advisory_report(
                as_of=args.as_of,
                cadence=args.cadence,
                political_events_path=events,
                political_watchlist_path=watchlist,
            )
            build_preview_bundle(first_report, output)
            first_evidence = read_preview_bundle(output)
            second_report = advisory_report.build_advisory_report(
                as_of=args.as_of,
                cadence=args.cadence,
                political_events_path=events,
                political_watchlist_path=watchlist,
            )
            build_preview_bundle(second_report, repeat_output)
        evidence = first_evidence
        _require_contract(dict(evidence.report), dict(evidence.manifest))
        repeat_equal = all(
            (output / name).read_bytes() == (repeat_output / name).read_bytes()
            for name in ("manifest.json", "report.html", "report.json")
        )
    finally:
        shutil.rmtree(repeat_parent, ignore_errors=True)
    if not repeat_equal:
        raise PreviewBundleError("repeat_build_non_deterministic")
    payload = _evidence(
        output=output,
        report=dict(evidence.report),
        manifest=dict(evidence.manifest),
        base_sha=base_sha,
        repeat_equal=repeat_equal,
    )
    evidence_path = Path(args.evidence_path)
    if evidence_path.exists():
        raise PreviewBundleError("evidence_exists")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--as-of", required=True)
    result.add_argument("--cadence", choices=("daily", "weekly", "monthly"), default="daily")
    result.add_argument("--political-events", required=True)
    result.add_argument("--political-watchlist", required=True)
    result.add_argument("--artifact-dir", required=True)
    result.add_argument("--evidence-path", required=True)
    result.add_argument("--base-sha", required=True)
    result.add_argument("--frozen-generated-at", required=True)
    return result


def main() -> None:
    try:
        build(parser().parse_args())
    except PreviewBundleError as exc:
        print(f"daily_preview_build_failed:{exc.code}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, TypeError, ValueError, UnicodeError):
        print("daily_preview_build_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build D3 representative evidence with an explicit harness-frozen clock."""
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


BASE_SHA_RE = re.compile(r"[0-9a-f]{40}")
FILES = ["manifest.json", "report.html", "report.json"]
BUNDLE = "qar.preview_bundle.v1"
SCHEMA = "5"
CONTRACT = "model_recommendations.v5"


def error(code: str) -> PreviewBundleError:
    return PreviewBundleError(code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_exact_files(artifact_dir: Path) -> None:
    if sorted(path.name for path in artifact_dir.iterdir()) != FILES or any(
        not (artifact_dir / name).is_file() for name in FILES
    ):
        raise error("file_set_invalid")


def require_external_paths(artifact_dir: Path, *evidence_paths: Path) -> None:
    try:
        artifact_resolved = artifact_dir.resolve()
        for evidence_path in evidence_paths:
            evidence_resolved = evidence_path.resolve()
            if evidence_resolved == artifact_resolved or artifact_resolved in evidence_resolved.parents:
                raise error("evidence_path_inside_artifact")
    except PreviewBundleError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise error("evidence_path_invalid") from None


def contract_source(report: dict[str, object], manifest: dict[str, object], frozen: str) -> dict[str, object]:
    source = manifest.get("source")
    expected = {
        "schema_version": SCHEMA,
        "contract_version": CONTRACT,
        "cadence": "daily",
        "as_of": report.get("as_of"),
        "generated_at": frozen,
    }
    if (
        report.get("schema_version") != SCHEMA
        or report.get("cadence") != "daily"
        or report.get("generated_at") != frozen
        or manifest.get("bundle_contract") != BUNDLE
        or not isinstance(source, dict)
        or source != expected
    ):
        raise error("contract_or_clock_drift")
    return source


def build(args: argparse.Namespace) -> None:
    if BASE_SHA_RE.fullmatch(args.base_sha) is None or not args.frozen_generated_at:
        raise error("input_invalid")
    events = Path(args.political_events)
    watchlist = Path(args.political_watchlist)
    output = Path(args.artifact_dir)
    evidence_path = Path(args.evidence_path)
    require_external_paths(output, evidence_path)
    if not events.is_file() or not watchlist.is_file():
        raise error("fixture_missing")
    repeat_parent = Path(tempfile.mkdtemp(prefix=f".{output.name}.repeat-", dir=output.parent))
    try:
        repeat_output = repeat_parent / "preview"
        with patch.object(advisory_report, "utc_now_iso", return_value=args.frozen_generated_at):
            first = advisory_report.build_advisory_report(
                as_of=args.as_of, cadence="daily", political_events_path=events, political_watchlist_path=watchlist
            )
            build_preview_bundle(first, output)
            first_readback = read_preview_bundle(output)
            second = advisory_report.build_advisory_report(
                as_of=args.as_of, cadence="daily", political_events_path=events, political_watchlist_path=watchlist
            )
            build_preview_bundle(second, repeat_output)
            second_readback = read_preview_bundle(repeat_output)
        first_report = dict(first_readback.report)
        second_report = dict(second_readback.report)
        first_manifest = dict(first_readback.manifest)
        second_manifest = dict(second_readback.manifest)
        first_source = contract_source(first_report, first_manifest, args.frozen_generated_at)
        second_source = contract_source(second_report, second_manifest, args.frozen_generated_at)
        if first_source != second_source:
            raise error("producer_metadata_mismatch")
        if any((output / name).read_bytes() != (repeat_output / name).read_bytes() for name in FILES):
            raise error("repeat_build_non_deterministic")
        payload = {
            "source_kind": "repository_representative_fixture",
            "base_sha": args.base_sha,
            "bundle_contract": BUNDLE,
            "frozen_generated_at": args.frozen_generated_at,
            "producer_generated_at_values": [first_report["generated_at"], second_report["generated_at"]],
            "report_generated_at": first_report["generated_at"],
            "manifest_generated_at_values": [first_source["generated_at"], second_source["generated_at"]],
            "source": {key: first_report[key] for key in ("cadence", "as_of", "generated_at", "schema_version")},
            "manifest_source": first_source,
            "files": sorted(path.name for path in output.iterdir()),
            "sha256": {name: sha256(output / name) for name in FILES},
            "repeat_build_bytes": True,
            "deterministic_clock": {"mode": "frozen_harness", "generated_at": args.frozen_generated_at},
        }
    finally:
        shutil.rmtree(repeat_parent, ignore_errors=True)
    require_exact_files(output)
    if evidence_path.exists():
        raise error("evidence_exists")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    require_exact_files(output)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--political-events", required=True)
    parser.add_argument("--political-watchlist", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--frozen-generated-at", required=True)
    try:
        build(parser.parse_args())
    except PreviewBundleError as exc:
        print(f"d3_clock_build_failed:{exc.code}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, TypeError, ValueError, UnicodeError):
        print("d3_clock_build_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

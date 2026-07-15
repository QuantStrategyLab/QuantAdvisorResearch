#!/usr/bin/env python3
"""Build a fresh D3 representative daily preview and external build evidence."""
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
BUNDLE_CONTRACT = "qar.preview_bundle.v1"
SCHEMA_VERSION = "5"
REPORT_CONTRACT = "model_recommendations.v5"
FIXED_FILES = ["manifest.json", "report.html", "report.json"]


def fail(code: str) -> PreviewBundleError:
    return PreviewBundleError(code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_contract(report: dict[str, object], manifest: dict[str, object]) -> dict[str, object]:
    source = manifest.get("source")
    expected = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": REPORT_CONTRACT,
        "cadence": "daily",
        "as_of": report.get("as_of"),
        "generated_at": report.get("generated_at"),
    }
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("cadence") != "daily"
        or manifest.get("bundle_contract") != BUNDLE_CONTRACT
        or not isinstance(source, dict)
        or source != expected
    ):
        raise fail("contract_drift")
    return source


def build(args: argparse.Namespace) -> None:
    if BASE_SHA_RE.fullmatch(args.base_sha) is None:
        raise fail("base_sha_invalid")
    if not args.frozen_generated_at:
        raise fail("frozen_generated_at_required")
    events = Path(args.political_events)
    watchlist = Path(args.political_watchlist)
    output = Path(args.artifact_dir)
    if not events.is_file() or not watchlist.is_file():
        raise fail("fixture_missing")

    repeat_parent = Path(tempfile.mkdtemp(prefix=f".{output.name}.repeat-", dir=output.parent))
    try:
        repeat_output = repeat_parent / "preview"
        with patch.object(advisory_report, "utc_now_iso", return_value=args.frozen_generated_at):
            first = advisory_report.build_advisory_report(
                as_of=args.as_of,
                cadence="daily",
                political_events_path=events,
                political_watchlist_path=watchlist,
            )
            build_preview_bundle(first, output)
            first_readback = read_preview_bundle(output)
            second = advisory_report.build_advisory_report(
                as_of=args.as_of,
                cadence="daily",
                political_events_path=events,
                political_watchlist_path=watchlist,
            )
            build_preview_bundle(second, repeat_output)
        first_report = dict(first_readback.report)
        first_manifest = dict(first_readback.manifest)
        manifest_source = require_contract(first_report, first_manifest)
        repeat_equal = all((output / name).read_bytes() == (repeat_output / name).read_bytes() for name in FIXED_FILES)
    finally:
        shutil.rmtree(repeat_parent, ignore_errors=True)
    if not repeat_equal:
        raise fail("repeat_build_non_deterministic")
    payload = {
        "source_kind": "repository_representative_fixture",
        "base_sha": args.base_sha,
        "bundle_contract": BUNDLE_CONTRACT,
        "source": {key: first_report[key] for key in ("cadence", "as_of", "generated_at", "schema_version")},
        "manifest_source": manifest_source,
        "deterministic_clock": {"mode": "frozen_harness", "generated_at": args.frozen_generated_at},
        "files": sorted(path.name for path in output.iterdir()),
        "sha256": {name: sha256(output / name) for name in FIXED_FILES},
        "repeat_build_bytes": repeat_equal,
    }
    if payload["files"] != FIXED_FILES:
        raise fail("file_set_invalid")
    evidence_path = Path(args.evidence_path)
    if evidence_path.exists():
        raise fail("evidence_exists")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        print(f"d3_reslice_build_failed:{exc.code}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, TypeError, ValueError, UnicodeError):
        print("d3_reslice_build_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

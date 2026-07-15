#!/usr/bin/env python3
"""Verify downloaded D3 bytes and exact frozen-clock/build-evidence binding."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quant_advisor_research.preview_bundle import PreviewBundleError, read_preview_bundle


BASE_SHA_RE = re.compile(r"[0-9a-f]{40}")
FILES = ["manifest.json", "report.html", "report.json"]
BUNDLE = "qar.preview_bundle.v1"
SCHEMA = "5"
CONTRACT = "model_recommendations.v5"


def error(code: str) -> PreviewBundleError:
    return PreviewBundleError(code)


def canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise error("manifest_canonical_invalid") from None


def verify(args: argparse.Namespace) -> None:
    if BASE_SHA_RE.fullmatch(args.base_sha) is None or not args.frozen_generated_at:
        raise error("input_invalid")
    output = Path(args.artifact_dir)
    if sorted(path.name for path in output.iterdir()) != FILES:
        raise error("file_set_invalid")
    raw_manifest = (output / "manifest.json").read_bytes()
    try:
        parsed_manifest = json.loads(raw_manifest.decode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise error("manifest_canonical_invalid") from None
    if raw_manifest != canonical(parsed_manifest):
        raise error("manifest_noncanonical")
    readback = read_preview_bundle(output)
    report = dict(readback.report)
    manifest = dict(readback.manifest)
    source = manifest.get("source")
    expected_source = {
        "schema_version": SCHEMA,
        "contract_version": CONTRACT,
        "cadence": "daily",
        "as_of": report.get("as_of"),
        "generated_at": args.frozen_generated_at,
    }
    if (
        report.get("schema_version") != SCHEMA
        or report.get("cadence") != "daily"
        or report.get("generated_at") != args.frozen_generated_at
        or manifest.get("bundle_contract") != BUNDLE
        or not isinstance(source, dict)
        or source != expected_source
    ):
        raise error("contract_or_clock_drift")
    try:
        build_evidence = json.loads(Path(args.build_evidence_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError):
        raise error("build_evidence_invalid") from None
    actual_hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in FILES}
    if (
        not isinstance(build_evidence, dict)
        or build_evidence.get("source_kind") != "repository_representative_fixture"
        or build_evidence.get("base_sha") != args.base_sha
        or build_evidence.get("bundle_contract") != BUNDLE
        or build_evidence.get("frozen_generated_at") != args.frozen_generated_at
        or build_evidence.get("producer_generated_at_values") != [args.frozen_generated_at, args.frozen_generated_at]
        or build_evidence.get("manifest_generated_at_values") != [args.frozen_generated_at, args.frozen_generated_at]
        or build_evidence.get("report_generated_at") != args.frozen_generated_at
        or build_evidence.get("manifest_source") != source
        or build_evidence.get("files") != FILES
        or build_evidence.get("sha256") != actual_hashes
    ):
        raise error("build_evidence_mismatch")
    payload = {
        "source_kind": "downloaded_repository_representative_fixture",
        "base_sha": args.base_sha,
        "bundle_contract": BUNDLE,
        "frozen_generated_at": args.frozen_generated_at,
        "source": source,
        "files": FILES,
        "sha256": actual_hashes,
        "manifest_canonical_bytes": True,
        "build_evidence_bound": True,
    }
    evidence_path = Path(args.evidence_path)
    if evidence_path.exists():
        raise error("evidence_exists")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--build-evidence-path", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--frozen-generated-at", required=True)
    try:
        verify(parser.parse_args())
    except (PreviewBundleError, OSError, TypeError, ValueError, UnicodeError):
        print("d3_clock_readback_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

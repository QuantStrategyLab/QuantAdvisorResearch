#!/usr/bin/env python3
"""Read back a downloaded D3 preview artifact without production integration."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quant_advisor_research.preview_bundle import PreviewBundleError, read_preview_bundle


BASE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SOURCE_KIND = "downloaded_repository_representative_fixture"
SOURCE_SCHEMA_VERSION = "5"
SOURCE_CONTRACT_VERSION = "model_recommendations.v5"
BUNDLE_CONTRACT = "qar.preview_bundle.v1"


def verify(args: argparse.Namespace) -> None:
    if BASE_SHA_PATTERN.fullmatch(args.base_sha) is None:
        raise PreviewBundleError("base_sha_invalid")
    output = Path(args.artifact_dir)
    evidence = read_preview_bundle(output)
    report = dict(evidence.report)
    manifest = dict(evidence.manifest)
    source = manifest.get("source")
    expected_source = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "contract_version": SOURCE_CONTRACT_VERSION,
        "cadence": "daily",
        "as_of": report.get("as_of"),
        "generated_at": report.get("generated_at"),
    }
    if (
        not isinstance(source, dict)
        or report.get("schema_version") != SOURCE_SCHEMA_VERSION
        or report.get("cadence") != "daily"
        or manifest.get("bundle_contract") != BUNDLE_CONTRACT
        or source != expected_source
    ):
        raise PreviewBundleError("contract_drift")
    try:
        build_evidence = json.loads(Path(args.build_evidence_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError):
        raise PreviewBundleError("build_evidence_invalid") from None
    if not isinstance(build_evidence, dict):
        raise PreviewBundleError("build_evidence_invalid")
    if (
        build_evidence.get("source_kind") != "repository_representative_fixture"
        or build_evidence.get("base_sha") != args.base_sha
        or build_evidence.get("bundle_contract") != BUNDLE_CONTRACT
        or build_evidence.get("manifest_source") != source
    ):
        raise PreviewBundleError("build_evidence_mismatch")
    expected_hashes = build_evidence.get("sha256")
    if not isinstance(expected_hashes, dict):
        raise PreviewBundleError("build_evidence_invalid")
    actual_hashes = {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "report.html", "report.json")
    }
    if (
        expected_hashes != actual_hashes
        or build_evidence.get("files") != ["manifest.json", "report.html", "report.json"]
        or build_evidence.get("source") != {
            "cadence": "daily",
            "as_of": report.get("as_of"),
            "generated_at": report.get("generated_at"),
            "schema_version": SOURCE_SCHEMA_VERSION,
        }
    ):
        raise PreviewBundleError("build_evidence_mismatch")
    payload = {
        "source_kind": SOURCE_KIND,
        "base_sha": args.base_sha,
        "bundle_contract": BUNDLE_CONTRACT,
        "source": source,
        "files": sorted(path.name for path in output.iterdir()),
        "sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("manifest.json", "report.html", "report.json")
        },
        "checks": [
            "exact_three_files",
            "canonical_json_readback",
            "manifest_hashes",
            "manifest_source_pair",
            "relative_html_links",
        ],
        "build_evidence_bound": True,
    }
    evidence_path = Path(args.evidence_path)
    if evidence_path.exists():
        raise PreviewBundleError("evidence_exists")
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--artifact-dir", required=True)
    result.add_argument("--evidence-path", required=True)
    result.add_argument("--build-evidence-path", required=True)
    result.add_argument("--base-sha", required=True)
    return result


def main() -> None:
    try:
        verify(parser().parse_args())
    except (PreviewBundleError, OSError, TypeError, ValueError, UnicodeError):
        print("daily_preview_readback_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

"""Concrete daily report-to-preview bundle with no legacy or runtime integration."""
from __future__ import annotations

import hashlib
import html
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .artifact_integrity import ArtifactIntegrityError, snapshot_json_wire
from .contracts import AdvisoryValidationError, validate_advisory_report

BUNDLE_CONTRACT = "qar.preview_bundle.v1"
SOURCE_SCHEMA_VERSION = "5"
SOURCE_CONTRACT_VERSION = "model_recommendations.v5"
_FIXED_FILES = frozenset({"report.json", "report.html", "manifest.json"})
_MANIFEST_KEYS = frozenset({"bundle_contract", "source", "artifacts"})
_SOURCE_KEYS = frozenset({"schema_version", "contract_version", "cadence", "as_of", "generated_at"})
_ARTIFACT_KEYS = frozenset({"name", "role", "sha256"})


class PreviewBundleError(ValueError):
    """Stable, sanitized preview bundle error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PreviewBundleEvidence:
    report: Mapping[str, object]
    manifest: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.report, Mapping) or not isinstance(self.manifest, Mapping):
            raise PreviewBundleError("readback_invalid")

    @property
    def bundle_contract(self) -> str:
        return BUNDLE_CONTRACT


def _error(code: str) -> PreviewBundleError:
    return PreviewBundleError(code)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("serialization_invalid") from None


def _validated_source(report: Mapping[str, Any]) -> dict[str, object]:
    try:
        snapshot = snapshot_json_wire(report)
        validate_advisory_report(snapshot)
    except (ArtifactIntegrityError, AdvisoryValidationError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("source_invalid") from None
    if snapshot.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise _error("source_schema_unsupported")
    if "contract_version" in snapshot:
        raise _error("source_contract_field_forbidden")
    if snapshot.get("cadence") != "daily":
        raise _error("daily_only")
    if type(snapshot.get("as_of")) is not str or type(snapshot.get("generated_at")) is not str:
        raise _error("source_time_invalid")
    return snapshot


def _render_html(snapshot: Mapping[str, object], report_bytes: bytes) -> bytes:
    escaped = html.escape(report_bytes.decode("utf-8"), quote=True)
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>QAR Daily Preview</title></head>"
        "<body><nav><a href=\"report.json\">report.json</a> "
        "<a href=\"manifest.json\">manifest.json</a></nav>"
        f"<h1>Daily report {html.escape(str(snapshot['as_of']), quote=True)}</h1>"
        f"<pre>{escaped}</pre></body></html>"
    )
    return document.encode("utf-8")


def _manifest(snapshot: Mapping[str, object], report_bytes: bytes, html_bytes: bytes) -> dict[str, object]:
    def artifact(name: str, role: str, content: bytes) -> dict[str, str]:
        return {"name": name, "role": role, "sha256": hashlib.sha256(content).hexdigest()}

    return {
        "bundle_contract": BUNDLE_CONTRACT,
        "source": {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "contract_version": SOURCE_CONTRACT_VERSION,
            "cadence": "daily",
            "as_of": snapshot["as_of"],
            "generated_at": snapshot["generated_at"],
        },
        "artifacts": {
            "report.json": artifact("report.json", "source_report", report_bytes),
            "report.html": artifact("report.html", "escaped_preview", html_bytes),
        },
    }


def _output_dir(path: str | Path) -> Path:
    output = Path(path)
    try:
        if not output.is_dir():
            raise _error("output_directory_invalid")
        if any(output.iterdir()):
            raise _error("output_not_empty")
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("output_directory_invalid") from None
    return output


def build_preview_bundle(report: Mapping[str, Any], output_dir: str | Path) -> PreviewBundleEvidence:
    """Validate once, build three deterministic bytes, then write an empty directory."""
    snapshot = _validated_source(report)
    output = _output_dir(output_dir)
    report_bytes = _canonical_json(snapshot)
    html_bytes = _render_html(snapshot, report_bytes)
    manifest = _manifest(snapshot, report_bytes, html_bytes)
    manifest_bytes = _canonical_json(manifest)
    files = {"report.json": report_bytes, "report.html": html_bytes, "manifest.json": manifest_bytes}
    temp_dir: str | None = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=".qar-preview-", dir=output)
        for name, content in files.items():
            Path(temp_dir, name).write_bytes(content)
        for name in files:
            os.replace(Path(temp_dir, name), output / name)
        os.rmdir(temp_dir)
        temp_dir = None
    except (OSError, TypeError, ValueError):
        raise _error("output_write_failed") from None
    finally:
        if temp_dir is not None:
            for child in Path(temp_dir).iterdir():
                child.unlink(missing_ok=True)
            Path(temp_dir).rmdir()
    return PreviewBundleEvidence(MappingProxyType(snapshot), MappingProxyType(manifest))


def _parse_json_bytes(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(text)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("readback_invalid") from None


def read_preview_bundle(output_dir: str | Path) -> PreviewBundleEvidence:
    output = Path(output_dir)
    try:
        if not output.is_dir() or {item.name for item in output.iterdir()} != _FIXED_FILES:
            raise _error("readback_file_set_invalid")
        report_bytes = (output / "report.json").read_bytes()
        html_bytes = (output / "report.html").read_bytes()
        manifest_bytes = (output / "manifest.json").read_bytes()
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("readback_invalid") from None

    report = _parse_json_bytes(report_bytes)
    if not isinstance(report, Mapping):
        raise _error("readback_invalid")
    snapshot = _validated_source(report)
    if _canonical_json(snapshot) != report_bytes:
        raise _error("report_bytes_noncanonical")
    manifest = _parse_json_bytes(manifest_bytes)
    if not isinstance(manifest, Mapping):
        raise _error("manifest_invalid")
    if set(manifest) != _MANIFEST_KEYS or set(manifest.get("source", {})) != _SOURCE_KEYS:
        raise _error("manifest_shape_invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {"report.json", "report.html"}:
        raise _error("manifest_shape_invalid")
    for item in artifacts.values():
        if not isinstance(item, Mapping) or set(item) != _ARTIFACT_KEYS or type(item.get("name")) is not str or type(item.get("role")) is not str:
            raise _error("manifest_shape_invalid")
    expected_manifest = _manifest(snapshot, report_bytes, html_bytes)
    if manifest != expected_manifest:
        raise _error("manifest_mismatch")
    expected_html = _render_html(snapshot, report_bytes)
    if html_bytes != expected_html or html_bytes.count(b'href="report.json"') != 1 or html_bytes.count(b'href="manifest.json"') != 1:
        raise _error("html_links_invalid")
    return PreviewBundleEvidence(MappingProxyType(snapshot), MappingProxyType(dict(manifest)))


__all__ = [
    "BUNDLE_CONTRACT", "SOURCE_CONTRACT_VERSION", "PreviewBundleError", "PreviewBundleEvidence",
    "build_preview_bundle", "read_preview_bundle",
]

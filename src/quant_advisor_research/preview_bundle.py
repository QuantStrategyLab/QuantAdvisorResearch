"""Concrete daily preview bundle with an explicit trusted-parent boundary.

The caller must provide a stable, non-symlink parent and coordinate all writers
through the bundle install lock. This module fails closed for filesystem races
within that contract; it does not claim to pin hostile ancestor replacement.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import stat
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
_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)


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


def _output_parent(path: str | Path) -> Path:
    output = Path(path)
    _assert_parent_chain(output)
    try:
        os.lstat(output)
        raise _error("output_exists")
    except FileNotFoundError:
        return output
    except (OSError, TypeError, ValueError):
        raise _error("output_exists") from None


def _assert_parent_chain(path: Path) -> None:
    try:
        current = path.parent
        while True:
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise _error("output_parent_invalid")
            if current.parent == current:
                return
            current = current.parent
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("output_parent_invalid") from None


def _assert_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except (OSError, TypeError, ValueError):
        raise _error("output_write_failed") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise _error("output_write_failed")


def _safe_file_flags(base: int) -> int:
    if _NOFOLLOW is None:
        raise _error("filesystem_unsupported")
    return base | _NOFOLLOW


def _assert_regular_file(path: Path, descriptor: int | None = None) -> None:
    try:
        info = os.fstat(descriptor) if descriptor is not None else os.lstat(path)
    except (OSError, TypeError, ValueError):
        raise _error("filesystem_invalid") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _error("filesystem_invalid")
    if descriptor is not None:
        try:
            path_info = os.lstat(path)
        except OSError:
            raise _error("filesystem_invalid") from None
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise _error("filesystem_invalid")


def _write_member(path: Path, content: bytes) -> None:
    fd = -1
    try:
        fd = os.open(path, _safe_file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
        _assert_regular_file(path, fd)
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
        _assert_regular_file(path, fd)
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("output_write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _read_member(path: Path) -> bytes:
    fd = -1
    try:
        _assert_regular_file(path)
        fd = os.open(path, _safe_file_flags(os.O_RDONLY))
        _assert_regular_file(path, fd)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        _assert_regular_file(path, fd)
        return b"".join(chunks)
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("readback_invalid") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _acquire_install_lock(parent: Path, output: Path) -> tuple[int, Path]:
    lock = parent / f".{output.name}.install-lock"
    try:
        fd = os.open(lock, _safe_file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
        _assert_regular_file(lock, fd)
        return fd, lock
    except PreviewBundleError:
        raise
    except (FileExistsError, OSError, TypeError, ValueError):
        raise _error("output_exists") from None


def _release_install_lock(fd: int, path: Path) -> None:
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _cleanup_staging(path: Path) -> None:
    try:
        for entry in os.scandir(path):
            child = Path(entry.path)
            try:
                os.unlink(child)
            except IsADirectoryError:
                os.rmdir(child)
        os.rmdir(path)
    except OSError:
        pass


def _fsync_directory(path: Path) -> None:
    fd = -1
    try:
        fd = os.open(path, _safe_file_flags(os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)))
        os.fsync(fd)
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("output_write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _read_bundle_files(output: Path, *, allow_install_lock: bool = False) -> tuple[bytes, bytes, bytes]:
    try:
        _assert_parent_chain(output)
        lock = output.parent / f".{output.name}.install-lock"
        if not allow_install_lock:
            try:
                os.lstat(lock)
            except FileNotFoundError:
                pass
            else:
                raise _error("readback_incomplete")
        output_info = os.lstat(output)
        if stat.S_ISLNK(output_info.st_mode) or not stat.S_ISDIR(output_info.st_mode):
            raise _error("readback_invalid")
        if {entry.name for entry in os.scandir(output)} != _FIXED_FILES:
            raise _error("readback_file_set_invalid")
        return (
            _read_member(output / "report.json"),
            _read_member(output / "report.html"),
            _read_member(output / "manifest.json"),
        )
    except PreviewBundleError as exc:
        if exc.code == "readback_file_set_invalid":
            raise
        raise _error("readback_invalid") from None
    except (OSError, TypeError, ValueError):
        raise _error("readback_invalid") from None


def build_preview_bundle(report: Mapping[str, Any], output_dir: str | Path) -> PreviewBundleEvidence:
    """Validate once, build three deterministic bytes, then write an empty directory."""
    snapshot = _validated_source(report)
    output = _output_parent(output_dir)
    report_bytes = _canonical_json(snapshot)
    html_bytes = _render_html(snapshot, report_bytes)
    manifest = _manifest(snapshot, report_bytes, html_bytes)
    manifest_bytes = _canonical_json(manifest)
    files = {"report.json": report_bytes, "report.html": html_bytes, "manifest.json": manifest_bytes}
    staging_dir: str | None = None
    lock_fd = -1
    lock_path: Path | None = None
    output_created = False
    install_succeeded = False
    try:
        output = _output_parent(output)
        staging_dir = tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
        staging_path = Path(staging_dir)
        _assert_directory(staging_path)
        for name, content in files.items():
            _write_member(staging_path / name, content)
        try:
            read_preview_bundle(staging_path)
        except PreviewBundleError:
            raise _error("output_write_failed") from None
        lock_fd, lock_path = _acquire_install_lock(output.parent, output)
        _output_parent(output)
        os.mkdir(output, 0o700)
        output_created = True
        for name in files:
            os.rename(staging_path / name, output / name)
        _read_preview_bundle(output, allow_install_lock=True)
        _fsync_directory(output)
        install_succeeded = True
        staging_dir = None
    except FileExistsError:
        raise _error("output_exists") from None
    except PreviewBundleError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("output_write_failed") from None
    finally:
        if staging_dir is not None:
            _cleanup_staging(Path(staging_dir))
        if output_created and not install_succeeded:
            _cleanup_staging(output)
        if lock_fd >= 0 and lock_path is not None:
            _release_install_lock(lock_fd, lock_path)
    return PreviewBundleEvidence(MappingProxyType(snapshot), MappingProxyType(manifest))


def _parse_json_bytes(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
        return json.loads(text)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise _error("readback_invalid") from None


def _read_preview_bundle(output: Path, *, allow_install_lock: bool = False) -> PreviewBundleEvidence:
    report_bytes, html_bytes, manifest_bytes = _read_bundle_files(output, allow_install_lock=allow_install_lock)

    report = _parse_json_bytes(report_bytes)
    if not isinstance(report, Mapping):
        raise _error("readback_invalid")
    snapshot = _validated_source(report)
    if _canonical_json(snapshot) != report_bytes:
        raise _error("report_bytes_noncanonical")
    manifest = _parse_json_bytes(manifest_bytes)
    if not isinstance(manifest, Mapping):
        raise _error("manifest_invalid")
    if _canonical_json(manifest) != manifest_bytes:
        raise _error("manifest_bytes_noncanonical")
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


def read_preview_bundle(output_dir: str | Path) -> PreviewBundleEvidence:
    return _read_preview_bundle(Path(output_dir))


__all__ = [
    "BUNDLE_CONTRACT", "SOURCE_CONTRACT_VERSION", "PreviewBundleError", "PreviewBundleEvidence",
    "build_preview_bundle", "read_preview_bundle",
]

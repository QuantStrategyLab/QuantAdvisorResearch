"""Private, build-before-return daily preview workspace foundation.

The caller supplies only a trusted stable parent. No fixed destination is
accepted and no publish/rename operation is performed by this API.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_integrity import ArtifactIntegrityError, snapshot_json_wire
from .contracts import AdvisoryValidationError, validate_advisory_report
from .preview_bundle import BUNDLE_CONTRACT, PreviewBundleError, SOURCE_CONTRACT_VERSION, read_preview_bundle

_FIXED_FILES = frozenset({"report.json", "report.html", "manifest.json"})
_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_WORKSPACE_PREFIX = ".qar-preview-"


class PreviewWorkspaceError(ValueError):
    """Stable, sanitized private-workspace error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _error(code: str) -> PreviewWorkspaceError:
    return PreviewWorkspaceError(code)


def _assert_parent_chain(parent: Path) -> None:
    try:
        current = parent
        while True:
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise _error("parent_invalid")
            if current.parent == current:
                return
            current = current.parent
    except PreviewWorkspaceError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("parent_invalid") from None


def _validated_source(report: Mapping[str, Any]) -> dict[str, object]:
    try:
        snapshot = snapshot_json_wire(report)
        validate_advisory_report(snapshot)
    except (ArtifactIntegrityError, AdvisoryValidationError, TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("source_invalid") from None
    if snapshot.get("schema_version") != "5":
        raise _error("source_schema_unsupported")
    if "contract_version" in snapshot or snapshot.get("cadence") != "daily":
        raise _error("source_contract_invalid")
    if type(snapshot.get("as_of")) is not str or type(snapshot.get("generated_at")) is not str:
        raise _error("source_time_invalid")
    return snapshot


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise _error("serialization_invalid") from None


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
            "schema_version": "5",
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


def _assert_regular(path: Path, descriptor: int | None = None) -> None:
    try:
        info = os.fstat(descriptor) if descriptor is not None else os.lstat(path)
    except (OSError, TypeError, ValueError):
        raise _error("filesystem_invalid") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _error("filesystem_invalid")
    if descriptor is not None:
        path_info = os.lstat(path)
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise _error("filesystem_invalid")


def _open_flags(base: int) -> int:
    if _NOFOLLOW is None:
        raise _error("filesystem_unsupported")
    return base | _NOFOLLOW


def _write_file(path: Path, content: bytes) -> None:
    fd = -1
    try:
        fd = os.open(path, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), 0o600)
        _assert_regular(path, fd)
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
        _assert_regular(path, fd)
    except PreviewWorkspaceError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("workspace_write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _read_file(path: Path) -> bytes:
    fd = -1
    try:
        _assert_regular(path)
        fd = os.open(path, _open_flags(os.O_RDONLY))
        _assert_regular(path, fd)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except PreviewWorkspaceError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("workspace_readback_invalid") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _read_workspace_files(workspace: Path) -> dict[str, bytes]:
    try:
        info = os.lstat(workspace)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise _error("workspace_readback_invalid")
        if {entry.name for entry in os.scandir(workspace)} != _FIXED_FILES:
            raise _error("workspace_file_set_invalid")
        return {name: _read_file(workspace / name) for name in sorted(_FIXED_FILES)}
    except PreviewWorkspaceError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("workspace_readback_invalid") from None


def _fsync_directory(path: Path) -> None:
    fd = -1
    try:
        fd = os.open(path, _open_flags(os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)))
        os.fsync(fd)
    except PreviewWorkspaceError:
        raise
    except (OSError, TypeError, ValueError):
        raise _error("workspace_write_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _cleanup_workspace(path: Path) -> None:
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return
        for entry in os.scandir(path):
            child = Path(entry.path)
            try:
                os.unlink(child)
            except IsADirectoryError:
                os.rmdir(child)
        os.rmdir(path)
    except OSError:
        pass


def build_preview_workspace(report: Mapping[str, Any], trusted_parent: str | Path) -> Path:
    """Build and validate a private bundle, returning its path only on success."""
    parent = Path(trusted_parent)
    _assert_parent_chain(parent)
    snapshot = _validated_source(report)
    report_bytes = _canonical_json(snapshot)
    html_bytes = _render_html(snapshot, report_bytes)
    manifest_bytes = _canonical_json(_manifest(snapshot, report_bytes, html_bytes))
    files = {"report.json": report_bytes, "report.html": html_bytes, "manifest.json": manifest_bytes}
    workspace: Path | None = None
    succeeded = False
    try:
        workspace = Path(tempfile.mkdtemp(prefix=_WORKSPACE_PREFIX, dir=parent))
        info = os.lstat(workspace)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o777 != 0o700:
            raise _error("workspace_invalid")
        for name, content in files.items():
            _write_file(workspace / name, content)
        _read_workspace_files(workspace)
        read_preview_bundle(workspace)
        _fsync_directory(workspace)
        succeeded = True
        return workspace
    except PreviewWorkspaceError:
        raise
    except PreviewBundleError:
        raise _error("workspace_readback_invalid") from None
    except (OSError, TypeError, ValueError):
        raise _error("workspace_build_failed") from None
    finally:
        if workspace is not None and not succeeded:
            _cleanup_workspace(workspace)


__all__ = ["PreviewWorkspaceError", "build_preview_workspace"]

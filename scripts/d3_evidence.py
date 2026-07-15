"""Pure D3 evidence helpers, including the shared exact-bundle validator."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

FIXED_FILES = ("manifest.json", "report.html", "report.json")
EVIDENCE_VERSION = "qar.d3.build_evidence.v4"
DIST_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s=]+)$")
DEPENDENCY_INVENTORY = [
    ".github/workflows/qar_d3_daily_preview_artifact.yml", "pyproject.toml", "uv.lock",
    "scripts/d3_build_daily_preview.py", "scripts/d3_verify_daily_preview.py", "scripts/d3_evidence.py",
    "src/quant_advisor_research/advisory_report.py", "src/quant_advisor_research/artifact_integrity.py",
    "src/quant_advisor_research/artifacts.py", "src/quant_advisor_research/contracts.py",
    "src/quant_advisor_research/csv_utils.py", "src/quant_advisor_research/period_contract.py",
    "src/quant_advisor_research/preview_bundle.py", "src/quant_advisor_research/preview_workspace.py",
    "src/quant_advisor_research/time_contract.py", "tests/test_d3_exact_bundle.py",
    "examples/political_events.example.csv", "examples/political_watchlist.example.csv",
]


class EvidenceContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BundleMemberSnapshot:
    name: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class BundleSnapshot:
    members: tuple[BundleMemberSnapshot, ...]

    def member(self, name: str) -> BundleMemberSnapshot:
        for item in self.members:
            if item.name == name:
                return item
        raise EvidenceContractError("bundle_member_set_invalid")


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required):
        raise EvidenceContractError("filesystem_unsupported")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW


def _member_flags() -> int:
    if any(not hasattr(os, name) for name in ("O_CLOEXEC", "O_NOFOLLOW")):
        raise EvidenceContractError("filesystem_unsupported")
    return os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW


def validate_exact_bundle(workspace: str | Path) -> BundleSnapshot:
    """Return an immutable FD-bound snapshot after validating all members."""
    root_fd = -1
    try:
        root_fd = os.open(workspace, _directory_flags())
        root_info = os.fstat(root_fd)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise EvidenceContractError("bundle_directory_invalid")
        names = os.listdir(root_fd)
        if set(names) != set(FIXED_FILES) or len(names) != len(FIXED_FILES):
            raise EvidenceContractError("bundle_member_set_invalid")
        result: list[BundleMemberSnapshot] = []
        for name in FIXED_FILES:
            fd = -1
            try:
                fd = os.open(name, _member_flags(), dir_fd=root_fd)
                info = os.fstat(fd)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise EvidenceContractError("bundle_member_invalid")
                chunks: list[bytes] = []
                while chunk := os.read(fd, 1024 * 1024):
                    chunks.append(chunk)
                content = b"".join(chunks)
                result.append(BundleMemberSnapshot(name, content, hashlib.sha256(content).hexdigest()))
            finally:
                if fd >= 0:
                    os.close(fd)
        if set(os.listdir(root_fd)) != set(FIXED_FILES):
            raise EvidenceContractError("bundle_member_set_invalid")
        return BundleSnapshot(tuple(result))
    except EvidenceContractError:
        raise
    except (OSError, TypeError, ValueError):
        raise EvidenceContractError("bundle_member_invalid") from None
    finally:
        if root_fd >= 0:
            os.close(root_fd)


def validate_preview_snapshot(snapshot: BundleSnapshot) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Readback validation using only the immutable member bytes."""
    try:
        from quant_advisor_research.preview_bundle import _canonical_json, _manifest, _render_html, _validated_source
        report_bytes = snapshot.member("report.json").content
        html_bytes = snapshot.member("report.html").content
        manifest_bytes = snapshot.member("manifest.json").content
        report = json.loads(report_bytes.decode("utf-8"))
        if not isinstance(report, Mapping):
            raise EvidenceContractError("readback_invalid")
        validated = _validated_source(report)
        if _canonical_json(validated) != report_bytes:
            raise EvidenceContractError("report_bytes_noncanonical")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, Mapping) or manifest != _manifest(validated, report_bytes, html_bytes):
            raise EvidenceContractError("manifest_mismatch")
        if html_bytes != _render_html(validated, report_bytes) or html_bytes.count(b'href="report.json"') != 1 or html_bytes.count(b'href="manifest.json"') != 1:
            raise EvidenceContractError("html_links_invalid")
        return validated, manifest
    except EvidenceContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError):
        raise EvidenceContractError("readback_invalid") from None


def canonical_distribution_snapshot(values: Iterable[str]) -> tuple[list[str], str]:
    try:
        raw = list(values)
        normalized: dict[str, str] = {}
        for value in raw:
            if type(value) is not str or not (match := DIST_RE.fullmatch(value)):
                raise EvidenceContractError("distribution_snapshot_invalid")
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            item = f"{name}=={match.group(2)}"
            if name in normalized and normalized[name] != item:
                raise EvidenceContractError("distribution_snapshot_conflict")
            normalized[name] = item
        snapshot = sorted(normalized.values())
        digest = hashlib.sha256("\n".join(snapshot).encode()).hexdigest()
        return snapshot, digest
    except EvidenceContractError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise EvidenceContractError("distribution_snapshot_invalid") from None


def locked_environment_evidence(*, lock_sha256: str, uv_version: str, python_version: str, distributions: Iterable[str]) -> dict[str, object]:
    if type(lock_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", lock_sha256):
        raise EvidenceContractError("lock_digest_invalid")
    if type(uv_version) is not str or not uv_version.startswith("uv "):
        raise EvidenceContractError("uv_version_invalid")
    if type(python_version) is not str or not re.fullmatch(r"3\.11(?:\.\d+)?", python_version):
        raise EvidenceContractError("python_version_invalid")
    snapshot, digest = canonical_distribution_snapshot(distributions)
    return {"lock_sha256": lock_sha256, "uv_version": uv_version, "python_version": python_version, "installed_distributions": snapshot, "installed_distributions_sha256": digest}


def repository_file_hashes(repo_root: str | Path, paths: Iterable[str]) -> dict[str, str]:
    root_fd = -1
    opened: list[int] = []
    try:
        root_fd = os.open(repo_root, _directory_flags())
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise EvidenceContractError("dependency_root_invalid")
        result: dict[str, str] = {}
        for raw in paths:
            relative = Path(raw)
            if type(raw) is not str or not raw or relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts) or raw in result:
                raise EvidenceContractError("dependency_path_invalid")
            parent_fd = root_fd
            traversed: list[int] = []
            try:
                for part in relative.parts[:-1]:
                    next_fd = os.open(part, _directory_flags(), dir_fd=parent_fd)
                    traversed.append(next_fd)
                    parent_fd = next_fd
                file_fd = os.open(relative.parts[-1], _member_flags(), dir_fd=parent_fd)
                opened.append(file_fd)
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise EvidenceContractError("dependency_file_invalid")
                digest = hashlib.sha256()
                while chunk := os.read(file_fd, 1024 * 1024):
                    digest.update(chunk)
                result[raw] = digest.hexdigest()
            finally:
                for fd in reversed(traversed):
                    os.close(fd)
        return dict(sorted(result.items()))
    except EvidenceContractError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise EvidenceContractError("dependency_file_invalid") from None
    finally:
        for fd in opened:
            os.close(fd)
        if root_fd >= 0:
            os.close(root_fd)


def require_exact_locked_environment(value: object, expected: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or dict(value) != dict(expected):
        raise EvidenceContractError("locked_environment_mismatch")

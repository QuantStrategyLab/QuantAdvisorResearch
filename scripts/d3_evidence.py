"""Pure D3 evidence helpers, including the shared exact-bundle validator."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable, Mapping
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


def validate_exact_bundle(workspace: str | Path) -> dict[str, Path]:
    """Validate all directory members before any caller reads or hashes them."""
    root = Path(workspace)
    try:
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise EvidenceContractError("bundle_directory_invalid")
        entries = list(os.scandir(root))
        if {entry.name for entry in entries} != set(FIXED_FILES) or len(entries) != len(FIXED_FILES):
            raise EvidenceContractError("bundle_member_set_invalid")
        result: dict[str, Path] = {}
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise EvidenceContractError("bundle_member_invalid")
            result[entry.name] = root / entry.name
        return {name: result[name] for name in FIXED_FILES}
    except EvidenceContractError:
        raise
    except (OSError, TypeError, ValueError):
        raise EvidenceContractError("bundle_member_invalid") from None


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
    root = Path(repo_root)
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise EvidenceContractError("dependency_root_invalid")
        result: dict[str, str] = {}
        for raw in paths:
            relative = Path(raw)
            if type(raw) is not str or not raw or relative.is_absolute() or ".." in relative.parts or raw in result:
                raise EvidenceContractError("dependency_path_invalid")
            target = root / relative
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
                raise EvidenceContractError("dependency_file_invalid")
            result[raw] = hashlib.sha256(target.read_bytes()).hexdigest()
        return dict(sorted(result.items()))
    except EvidenceContractError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise EvidenceContractError("dependency_file_invalid") from None


def require_exact_locked_environment(value: object, expected: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or dict(value) != dict(expected):
        raise EvidenceContractError("locked_environment_mismatch")

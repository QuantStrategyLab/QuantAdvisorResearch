"""Tool-agnostic D3 evidence contracts; no uv/process/filesystem discovery."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
import stat

DIST_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s=]+)$")

DEPENDENCY_INVENTORY = [
    ".github/workflows/qar_d3_daily_preview_artifact.yml", "pyproject.toml", "uv.lock",
    "scripts/d3_build_daily_preview.py", "scripts/d3_verify_daily_preview.py", "scripts/d3_evidence.py",
    "src/quant_advisor_research/advisory_report.py", "src/quant_advisor_research/artifact_integrity.py",
    "src/quant_advisor_research/artifacts.py", "src/quant_advisor_research/contracts.py",
    "src/quant_advisor_research/csv_utils.py", "src/quant_advisor_research/period_contract.py",
    "src/quant_advisor_research/preview_bundle.py", "src/quant_advisor_research/preview_workspace.py",
    "src/quant_advisor_research/time_contract.py", "tests/test_d3_tool_agnostic.py",
    "examples/political_events.example.csv", "examples/political_watchlist.example.csv",
]


class EvidenceContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_distribution_snapshot(values: Iterable[str]) -> tuple[list[str], str]:
    try:
        snapshot = list(values)
    except (TypeError, ValueError):
        raise EvidenceContractError("distribution_snapshot_invalid") from None
    normalized: dict[str, str] = {}
    for value in snapshot:
        if type(value) is not str or not (match := DIST_RE.fullmatch(value)):
            raise EvidenceContractError("distribution_snapshot_invalid")
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        normalized_value = f"{name}=={match.group(2)}"
        if name in normalized and normalized[name] != normalized_value:
            raise EvidenceContractError("distribution_snapshot_conflict")
        normalized[name] = normalized_value
    snapshot = sorted(normalized.values())
    if len(snapshot) != len(normalized):
        raise EvidenceContractError("distribution_snapshot_invalid")
    digest = hashlib.sha256("\n".join(snapshot).encode("utf-8")).hexdigest()
    return snapshot, digest


def locked_environment_evidence(*, lock_sha256: str, uv_version: str, python_version: str, distributions: Iterable[str]) -> dict[str, object]:
    if type(lock_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", lock_sha256):
        raise EvidenceContractError("lock_digest_invalid")
    if type(uv_version) is not str or not uv_version.startswith("uv "):
        raise EvidenceContractError("uv_version_invalid")
    if type(python_version) is not str or not re.fullmatch(r"3\.11(?:\.\d+)?", python_version):
        raise EvidenceContractError("python_version_invalid")
    snapshot, snapshot_sha256 = canonical_distribution_snapshot(distributions)
    return {
        "lock_sha256": lock_sha256,
        "uv_version": uv_version,
        "python_version": python_version,
        "installed_distributions": snapshot,
        "installed_distributions_sha256": snapshot_sha256,
    }


def require_exact_locked_environment(value: object, expected: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or dict(value) != dict(expected):
        raise EvidenceContractError("locked_environment_mismatch")


def repository_file_hashes(repo_root: str | Path, relative_paths: Iterable[str]) -> dict[str, str]:
    root = Path(repo_root)
    try:
        root_info = root.stat()
        if not stat.S_ISDIR(root_info.st_mode):
            raise EvidenceContractError("dependency_root_invalid")
        result: dict[str, str] = {}
        for raw_path in relative_paths:
            if type(raw_path) is not str or not raw_path or Path(raw_path).is_absolute():
                raise EvidenceContractError("dependency_path_invalid")
            relative = Path(raw_path)
            if ".." in relative.parts or raw_path in result:
                raise EvidenceContractError("dependency_path_invalid")
            target = root / relative
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise EvidenceContractError("dependency_file_invalid")
            resolved = target.resolve(strict=True)
            if resolved != target.absolute():
                raise EvidenceContractError("dependency_file_invalid")
            result[raw_path] = hashlib.sha256(target.read_bytes()).hexdigest()
        return dict(sorted(result.items()))
    except EvidenceContractError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise EvidenceContractError("dependency_file_invalid") from None

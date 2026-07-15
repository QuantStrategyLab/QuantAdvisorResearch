"""Tool-agnostic D3 evidence contracts; no uv/process/filesystem discovery."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping

DIST_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^\s=]+$")

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
    if any(type(value) is not str or not DIST_RE.fullmatch(value) for value in snapshot):
        raise EvidenceContractError("distribution_snapshot_invalid")
    snapshot.sort(key=str.casefold)
    if len(snapshot) != len(set(snapshot)):
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

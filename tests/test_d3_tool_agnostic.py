from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from d3_evidence import EvidenceContractError, canonical_distribution_snapshot, locked_environment_evidence, require_exact_locked_environment, repository_file_hashes


def test_environment_contract_is_pure_and_deterministic():
    values = ["pytest==9.1.1", "quant-advisor-research==0.1.3"]
    evidence = locked_environment_evidence(
        lock_sha256="a" * 64,
        uv_version="uv 0.11.19",
        python_version="3.11.9",
        distributions=reversed(values),
    )
    assert evidence["installed_distributions"] == values
    require_exact_locked_environment(dict(evidence), evidence)


@pytest.mark.parametrize("mutation", [
    lambda value: {**value, "unknown": True},
    lambda value: {**value, "lock_sha256": "b" * 64},
    lambda value: {**value, "installed_distributions": ["pytest==9.1.1", "pytest==9.1.1"]},
])
def test_environment_tamper_fails_closed(mutation):
    evidence = locked_environment_evidence(
        lock_sha256="a" * 64,
        uv_version="uv 0.11.19",
        python_version="3.11.9",
        distributions=["pytest==9.1.1"],
    )
    with pytest.raises(EvidenceContractError, match="locked_environment_mismatch"):
        require_exact_locked_environment(mutation(evidence), evidence)


def test_invalid_toolchain_values_are_rejected_without_uv_lookup():
    with pytest.raises(EvidenceContractError, match="uv_version_invalid"):
        locked_environment_evidence(lock_sha256="a" * 64, uv_version="latest", python_version="3.11.9", distributions=[])
    with pytest.raises(EvidenceContractError, match="python_version_invalid"):
        locked_environment_evidence(lock_sha256="a" * 64, uv_version="uv 0.11.19", python_version="3.12.0", distributions=[])


def test_distribution_snapshot_is_sorted_and_hashed():
    snapshot, digest = canonical_distribution_snapshot(["Zed==1.0", "alpha==2.0", "ALPHA==2.0"])
    assert snapshot == ["alpha==2.0", "zed==1.0"]
    assert len(digest) == 64


def test_distribution_snapshot_rejects_pep503_name_version_conflict():
    with pytest.raises(EvidenceContractError, match="distribution_snapshot_conflict"):
        canonical_distribution_snapshot(["alpha_.==1.0", "ALPHA-==2.0"])


def test_repository_file_hashes_is_canonical_and_rejects_unsafe_members(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    assert repository_file_hashes(tmp_path, ["a.txt"]) == repository_file_hashes(tmp_path, ["a.txt"])
    with pytest.raises(EvidenceContractError, match="dependency_path_invalid"):
        repository_file_hashes(tmp_path, ["../a.txt"])
    (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")
    with pytest.raises(EvidenceContractError, match="dependency_file_invalid"):
        repository_file_hashes(tmp_path, ["link.txt"])


def test_d3_workflow_is_triggered_and_uses_locked_tooling():
    workflow = (Path(__file__).parents[1] / ".github/workflows/qar_d3_daily_preview_artifact.yml").read_text()
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "uv sync --locked --extra test" in workflow
    assert "uv run --no-sync python" in workflow
    assert "pip install" not in workflow
    assert "path: ${{ steps.build.outputs.workspace }}/*" not in workflow
    assert "--base-sha" in workflow and "--head-sha" in workflow
    assert "--repo-root \"$GITHUB_WORKSPACE\"" in workflow
    assert "${{ inputs.as_of || '2026-06-20' }}" in workflow
    assert "${{ inputs.frozen_generated_at || '2026-07-15T00:00:00Z' }}" in workflow
    for action in (
        "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131",
    ):
        assert action in workflow

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from d3_evidence import EvidenceContractError, canonical_distribution_snapshot, validate_exact_bundle


def _normal_bundle(path: Path) -> None:
    path.mkdir()
    for name in ("manifest.json", "report.html", "report.json"):
        (path / name).write_text(name)


def test_exact_bundle_validator_returns_only_regular_single_link_members(tmp_path):
    bundle = tmp_path / "bundle"
    _normal_bundle(bundle)
    assert tuple(validate_exact_bundle(bundle)) == ("manifest.json", "report.html", "report.json")


@pytest.mark.parametrize("mutation", [
    lambda p: (p / "extra.txt").write_text("x"),
    lambda p: (p / "report.json").unlink(),
    lambda p: (p / "extra").symlink_to(p / "report.json"),
    lambda p: (p / "report.json").unlink() or (p / "report.json").symlink_to(p / "manifest.json"),
])
def test_exact_bundle_validator_rejects_extra_missing_and_symlink(tmp_path, mutation):
    bundle = tmp_path / "bundle"
    _normal_bundle(bundle)
    mutation(bundle)
    with pytest.raises(EvidenceContractError):
        validate_exact_bundle(bundle)


def test_exact_bundle_validator_rejects_hardlink_and_nonregular(tmp_path):
    bundle = tmp_path / "bundle"
    _normal_bundle(bundle)
    (bundle / "alias").hardlink_to(bundle / "report.json")
    with pytest.raises(EvidenceContractError):
        validate_exact_bundle(bundle)

    bundle = tmp_path / "fifo-bundle"
    _normal_bundle(bundle)
    (bundle / "report.html").unlink()
    (bundle / "report.html").mkdir()
    with pytest.raises(EvidenceContractError):
        validate_exact_bundle(bundle)


def test_distribution_snapshot_uses_pep503_and_rejects_conflict():
    values, _ = canonical_distribution_snapshot(["Zed==1.0", "alpha==2.0", "ALPHA==2.0"])
    assert values == ["alpha==2.0", "zed==1.0"]
    with pytest.raises(EvidenceContractError, match="distribution_snapshot_conflict"):
        canonical_distribution_snapshot(["alpha_.==1.0", "ALPHA-==2.0"])


def test_workflow_uses_exact_paths_and_immutable_actions():
    workflow = (Path(__file__).parents[1] / ".github/workflows/qar_d3_daily_preview_artifact.yml").read_text()
    assert "pull_request:" in workflow and "workflow_dispatch:" in workflow
    assert "uv sync --locked --extra test" in workflow and "pip install" not in workflow
    assert "report.json" in workflow and "report.html" in workflow and "manifest.json" in workflow
    assert "steps.build.outputs.workspace }}/*" not in workflow
    assert "--base-sha" in workflow and "--head-sha" in workflow
    for action in ("actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10", "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1", "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e", "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131"):
        assert action in workflow

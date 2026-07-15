from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

import quant_advisor_research.preview_workspace as preview_workspace
from quant_advisor_research.advisory_report import build_advisory_report
from quant_advisor_research.preview_bundle import PreviewBundleError, read_preview_bundle
from quant_advisor_research.preview_workspace import PreviewWorkspaceError, build_preview_workspace

ROOT = Path(__file__).resolve().parents[1]


def report():
    return build_advisory_report(
        as_of="2026-06-20",
        cadence="daily",
        political_events_path=ROOT / "examples/political_events.example.csv",
        political_watchlist_path=ROOT / "examples/political_watchlist.example.csv",
    )


def test_api_accepts_only_trusted_parent_not_fixed_destination():
    assert list(inspect.signature(build_preview_workspace).parameters) == ["report", "trusted_parent"]


def test_workspace_is_private_exact_three_files_and_readback_valid(tmp_path):
    workspace = build_preview_workspace(report(), tmp_path)

    assert workspace.parent == tmp_path
    assert workspace.name.startswith(".qar-preview-")
    assert os.stat(workspace).st_mode & 0o777 == 0o700
    assert {path.name for path in workspace.iterdir()} == {"report.json", "report.html", "manifest.json"}
    read_preview_bundle(workspace)


def test_equivalent_reports_produce_identical_bytes_in_distinct_workspaces(tmp_path):
    first = build_preview_workspace(report(), tmp_path)
    second = build_preview_workspace(report(), tmp_path)

    assert first != second
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }


def test_symlinked_or_non_directory_parent_fails_closed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(PreviewWorkspaceError, match="parent_invalid"):
        build_preview_workspace(report(), alias)

    file_parent = tmp_path / "file"
    file_parent.write_text("not a directory")
    with pytest.raises(PreviewWorkspaceError, match="parent_invalid"):
        build_preview_workspace(report(), file_parent)


def test_injected_member_symlink_never_touches_external_target(tmp_path, monkeypatch):
    external = tmp_path / "external.json"
    external.write_bytes(b"keep")
    real_mkdtemp = preview_workspace.tempfile.mkdtemp

    def inject_member(**kwargs):
        workspace = real_mkdtemp(**kwargs)
        (Path(workspace) / "report.json").symlink_to(external)
        return workspace

    monkeypatch.setattr(preview_workspace.tempfile, "mkdtemp", inject_member)
    with pytest.raises(PreviewWorkspaceError, match="workspace_write_failed"):
        build_preview_workspace(report(), tmp_path)
    assert external.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".qar-preview-*"))


def test_readback_failure_cleans_only_private_workspace(tmp_path, monkeypatch):
    def fail_readback(_path):
        raise PreviewBundleError("forced_readback_failure")

    monkeypatch.setattr(preview_workspace, "read_preview_bundle", fail_readback)
    with pytest.raises(PreviewWorkspaceError, match="workspace_readback_invalid"):
        build_preview_workspace(report(), tmp_path)
    assert not list(tmp_path.glob(".qar-preview-*"))

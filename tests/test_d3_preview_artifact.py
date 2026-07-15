from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "examples/political_events.example.csv"
WATCHLIST = ROOT / "examples/political_watchlist.example.csv"


def test_d3_harness_builds_two_equal_workspaces_and_verifies_full_evidence(tmp_path):
    evidence = tmp_path / "evidence" / "build_evidence.json"
    workspace_file = tmp_path / "workspace.txt"
    env = {"PYTHONPATH": str(ROOT / "src")}
    uv_version = subprocess.check_output(["uv", "--version"], text=True).strip()
    build = subprocess.run(
        [
            sys.executable,
            "scripts/d3_build_daily_preview.py",
            "--as-of",
            "2026-06-20",
            "--political-events",
            str(EVENTS),
            "--political-watchlist",
            str(WATCHLIST),
            "--frozen-generated-at",
            "2026-07-15T00:00:00Z",
            "--base-sha",
            "a" * 40,
            "--uv-version",
            uv_version,
            "--lock-path",
            str(ROOT / "uv.lock"),
            "--temp-root",
            str(tmp_path),
            "--evidence-path",
            str(evidence),
            "--workspace-path-file",
            str(workspace_file),
        ],
        cwd=ROOT,
        env={**__import__("os").environ, **env},
        check=True,
        capture_output=True,
        text=True,
    )
    workspace = Path(workspace_file.read_text().strip())
    assert {path.name for path in workspace.iterdir()} == {"report.json", "report.html", "manifest.json"}
    assert json.loads(evidence.read_text())["repeat_build"]["bytes_equal"] is True

    downloaded = tmp_path / "downloaded"
    downloaded.mkdir()
    for source in workspace.iterdir():
        (downloaded / source.name).write_bytes(source.read_bytes())
    subprocess.run(
        [
            sys.executable,
            "scripts/d3_verify_daily_preview.py",
            "--workspace",
            str(downloaded),
            "--evidence-path",
            str(evidence),
            "--base-sha",
            "a" * 40,
            "--uv-version",
            uv_version,
            "--lock-path",
            str(ROOT / "uv.lock"),
            "--as-of",
            "2026-06-20",
            "--political-events",
            str(EVENTS),
            "--political-watchlist",
            str(WATCHLIST),
            "--frozen-generated-at",
            "2026-07-15T00:00:00Z",
        ],
        cwd=ROOT,
        env={**__import__("os").environ, **env},
        check=True,
        capture_output=True,
        text=True,
    )

    tampered = json.loads(evidence.read_text())
    tampered["unexpected"] = "reject"
    evidence.write_text(json.dumps(tampered), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    import d3_verify_daily_preview as verifier

    with pytest.raises(ValueError, match="evidence_shape_invalid"):
        verifier.verify(
            workspace=downloaded,
            evidence_path=evidence,
            expected_base_sha="a" * 40,
            expected_as_of="2026-06-20",
            expected_events=str(EVENTS),
            expected_watchlist=str(WATCHLIST),
            frozen_generated_at="2026-07-15T00:00:00Z",
            uv_version=uv_version,
            lock_path=ROOT / "uv.lock",
        )


def test_d3_workflow_requires_pull_request_paths_and_locked_pinned_toolchain():
    workflow = (ROOT / ".github/workflows/qar_d3_daily_preview_artifact.yml").read_text()
    assert "pull_request:" in workflow
    for path in ("pyproject.toml", "uv.lock", "scripts/d3_build_daily_preview.py", "scripts/d3_verify_daily_preview.py", "src/quant_advisor_research/**", "tests/test_d3_preview_artifact.py"):
        assert f'      - "{path}"' in workflow
    assert "uv sync --locked --extra test" in workflow
    assert "uv run --no-sync" in workflow
    assert "pip install" not in workflow
    for action in (
        "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10",
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131",
    ):
        assert action in workflow

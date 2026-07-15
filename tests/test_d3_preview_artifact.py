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
        )

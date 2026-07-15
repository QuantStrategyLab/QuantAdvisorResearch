from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/d3_clock_bound_build.py"
VERIFY = ROOT / "scripts/d3_clock_bound_verify.py"
BASE_SHA = "c5ba801a8696eec63c7ba348f3f125cb52cd06ff"
FROZEN = "2026-07-15T00:00:00Z"


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def build_args(output: Path, evidence: Path) -> tuple[str, ...]:
    return (
        "--as-of", "2026-06-20",
        "--political-events", str(ROOT / "examples/political_events.example.csv"),
        "--political-watchlist", str(ROOT / "examples/political_watchlist.example.csv"),
        "--artifact-dir", str(output), "--evidence-path", str(evidence),
        "--base-sha", BASE_SHA, "--frozen-generated-at", FROZEN,
    )


def test_build_binds_cli_frozen_clock_to_both_independent_outputs(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "build-evidence.json"
    result = run_script(BUILD, *build_args(output, evidence))

    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["frozen_generated_at"] == FROZEN
    assert payload["producer_generated_at_values"] == [FROZEN, FROZEN]
    assert payload["manifest_generated_at_values"] == [FROZEN, FROZEN]
    assert payload["report_generated_at"] == FROZEN


def test_verify_requires_exact_frozen_clock_binding(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "build-evidence.json"
    assert run_script(BUILD, *build_args(output, evidence)).returncode == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["frozen_generated_at"] = "2026-07-15T00:00:01Z"
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    result = run_script(
        VERIFY, "--artifact-dir", str(output), "--build-evidence-path", str(evidence),
        "--evidence-path", str(tmp_path / "download-evidence.json"), "--base-sha", BASE_SHA,
        "--frozen-generated-at", FROZEN,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr


def test_verify_rejects_manifest_clock_drift(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "build-evidence.json"
    assert run_script(BUILD, *build_args(output, evidence)).returncode == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    manifest["source"]["generated_at"] = "2026-07-15T00:00:01Z"
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = run_script(
        VERIFY, "--artifact-dir", str(output), "--build-evidence-path", str(evidence),
        "--evidence-path", str(tmp_path / "download-evidence.json"), "--base-sha", BASE_SHA,
        "--frozen-generated-at", FROZEN,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr

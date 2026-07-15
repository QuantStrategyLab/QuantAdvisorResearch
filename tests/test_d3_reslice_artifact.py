from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/d3_reslice_build_preview.py"
VERIFY = ROOT / "scripts/d3_reslice_verify_preview.py"
BASE_SHA = "c5ba801a8696eec63c7ba348f3f125cb52cd06ff"


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def build_args(output: Path, evidence: Path) -> tuple[str, ...]:
    return (
        "--as-of", "2026-06-20",
        "--political-events", str(ROOT / "examples/political_events.example.csv"),
        "--political-watchlist", str(ROOT / "examples/political_watchlist.example.csv"),
        "--artifact-dir", str(output), "--evidence-path", str(evidence),
        "--base-sha", BASE_SHA, "--frozen-generated-at", "2026-07-15T00:00:00Z",
    )


def test_fresh_reslice_build_binds_two_independent_frozen_producers(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "build-evidence.json"
    result = run_script(BUILD, *build_args(output, evidence))

    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["source_kind"] == "repository_representative_fixture"
    assert payload["deterministic_clock"] == {"mode": "frozen_harness", "generated_at": "2026-07-15T00:00:00Z"}
    assert payload["files"] == ["manifest.json", "report.html", "report.json"]
    assert payload["repeat_build_bytes"] is True


def test_fresh_reslice_verify_rejects_noncanonical_manifest_and_binds_build_evidence(tmp_path):
    output = tmp_path / "preview"
    build_evidence = tmp_path / "build-evidence.json"
    assert run_script(BUILD, *build_args(output, build_evidence)).returncode == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = run_script(
        VERIFY,
        "--artifact-dir", str(output),
        "--build-evidence-path", str(build_evidence),
        "--evidence-path", str(tmp_path / "download-evidence.json"),
        "--base-sha", BASE_SHA,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr


def test_fresh_reslice_verify_rejects_build_evidence_mismatch(tmp_path):
    output = tmp_path / "preview"
    build_evidence = tmp_path / "build-evidence.json"
    assert run_script(BUILD, *build_args(output, build_evidence)).returncode == 0
    payload = json.loads(build_evidence.read_text(encoding="utf-8"))
    payload["base_sha"] = "0" * 40
    build_evidence.write_text(json.dumps(payload), encoding="utf-8")

    result = run_script(
        VERIFY,
        "--artifact-dir", str(output),
        "--build-evidence-path", str(build_evidence),
        "--evidence-path", str(tmp_path / "download-evidence.json"),
        "--base-sha", BASE_SHA,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr


def test_reslice_workflow_paths_cover_fixture_and_transitive_contract_inputs():
    workflow = (ROOT / ".github/workflows/qar_vnext_d3_daily_preview_artifact_reslice.yml").read_text()
    for path in (
        "examples/political_events.example.csv",
        "examples/political_watchlist.example.csv",
        "src/quant_advisor_research/**",
        "pyproject.toml",
        "uv.lock",
    ):
        assert path in workflow

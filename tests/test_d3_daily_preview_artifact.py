from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/d3_build_daily_preview_artifact.py"
VERIFY = ROOT / "scripts/d3_verify_daily_preview_artifact.py"
BASE_SHA = "c5ba801a8696eec63c7ba348f3f125cb52cd06ff"


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def build_args(output: Path, evidence: Path) -> tuple[str, ...]:
    return (
        "--as-of",
        "2026-06-20",
        "--political-events",
        str(ROOT / "examples/political_events.example.csv"),
        "--political-watchlist",
        str(ROOT / "examples/political_watchlist.example.csv"),
        "--artifact-dir",
        str(output),
        "--evidence-path",
        str(evidence),
        "--base-sha",
        BASE_SHA,
        "--frozen-generated-at",
        "2026-07-15T00:00:00Z",
    )


def test_representative_daily_build_emits_deterministic_evidence(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "evidence.json"
    result = run_script(BUILD, *build_args(output, evidence))

    assert result.returncode == 0, result.stderr
    assert {item.name for item in output.iterdir()} == {"report.json", "report.html", "manifest.json"}
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["source_kind"] == "repository_representative_fixture"
    assert payload["base_sha"] == BASE_SHA
    assert payload["bundle_contract"] == "qar.preview_bundle.v1"
    assert payload["source"] == {
        "cadence": "daily",
        "as_of": "2026-06-20",
        "generated_at": "2026-07-15T00:00:00Z",
        "schema_version": "5",
    }
    assert payload["checks"] == [
        "exact_three_files",
        "canonical_json_readback",
        "manifest_hashes",
        "manifest_source_pair",
        "relative_html_links",
        "repeat_build_bytes",
    ]
    assert payload["repeat_build_bytes"] is True


def test_verify_rejects_tampered_artifact(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "evidence.json"
    assert run_script(BUILD, *build_args(output, evidence)).returncode == 0
    (output / "report.html").write_text("tampered", encoding="utf-8")

    result = run_script(
        VERIFY,
        "--artifact-dir",
        str(output),
        "--evidence-path",
        str(tmp_path / "downloaded-evidence.json"),
        "--build-evidence-path",
        str(evidence),
        "--base-sha",
        BASE_SHA,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr


def test_build_rejects_non_daily_source_before_output(tmp_path):
    result = run_script(
        BUILD,
        "--as-of",
        "2026-06-20",
        "--cadence",
        "weekly",
        "--political-events",
        str(ROOT / "examples/political_events.example.csv"),
        "--political-watchlist",
        str(ROOT / "examples/political_watchlist.example.csv"),
        "--artifact-dir",
        str(tmp_path / "preview"),
        "--evidence-path",
        str(tmp_path / "evidence.json"),
        "--base-sha",
        BASE_SHA,
        "--frozen-generated-at",
        "2026-07-15T00:00:00Z",
    )

    assert result.returncode != 0
    assert not (tmp_path / "preview").exists()
    assert "daily_only" in result.stderr


def test_verify_rejects_build_evidence_base_mismatch(tmp_path):
    output = tmp_path / "preview"
    evidence = tmp_path / "evidence.json"
    assert run_script(BUILD, *build_args(output, evidence)).returncode == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["base_sha"] = "0" * 40
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    result = run_script(
        VERIFY,
        "--artifact-dir",
        str(output),
        "--evidence-path",
        str(tmp_path / "downloaded-evidence.json"),
        "--build-evidence-path",
        str(evidence),
        "--base-sha",
        BASE_SHA,
    )

    assert result.returncode != 0
    assert "readback_failed" in result.stderr

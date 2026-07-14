from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import SOURCE_PROJECT
from .time_contract import TimeContractError, contract_version_for_schema


def contract_version_for_report(report: Mapping[str, Any]) -> str:
    schema_version = report.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValueError("schema_version must be a non-empty string")
    try:
        expected = contract_version_for_schema(schema_version)
    except TimeContractError as exc:
        raise ValueError(str(exc)) from exc
    actual = report.get("contract_version")
    if schema_version == "6" and actual is None:
        raise ValueError("schema 6 report requires an explicit contract_version")
    if actual is not None and actual != expected:
        raise ValueError("report schema_version and contract_version do not match")
    return expected


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def write_report_manifest(
    *,
    report: Mapping[str, Any],
    report_path: str | Path,
    markdown_path: str | Path,
    manifest_path: str | Path,
    repository: str | None = None,
    git_sha: str | None = None,
    run_id: str | None = None,
    run_attempt: str | None = None,
) -> Path:
    resolved_report = Path(report_path)
    resolved_markdown = Path(markdown_path)
    if not resolved_report.exists():
        raise FileNotFoundError(f"report JSON artifact not found: {resolved_report}")
    if not resolved_markdown.exists():
        raise FileNotFoundError(f"Markdown report artifact not found: {resolved_markdown}")

    version_parts = [
        str(report.get("as_of") or "unknown"),
        str(report.get("cadence") or "unknown"),
        f"schema-{report.get('schema_version') or 'unknown'}",
    ]
    if run_id:
        version_parts.append(f"run-{run_id}")
    elif git_sha:
        version_parts.append(str(git_sha)[:12])
    else:
        version_parts.append("local")
    if run_attempt:
        version_parts.append(f"attempt-{run_attempt}")

    payload = {
        "manifest_type": "model_recommendation_report",
        "artifact_type": "model_recommendations",
        "contract_version": contract_version_for_report(report),
        "schema_version": str(report.get("schema_version") or ""),
        "version": "-".join(version_parts),
        "mode": str(report.get("mode") or ""),
        "cadence": str(report.get("cadence") or ""),
        "as_of": str(report.get("as_of") or ""),
        "audience_scope": str(report.get("audience_scope") or ""),
        "source_project": SOURCE_PROJECT,
        "producer": {
            "repository": repository or SOURCE_PROJECT,
            "git_sha": git_sha or "",
            "github_run_id": run_id or "",
            "github_run_attempt": run_attempt or "",
        },
        "source_artifacts": dict(report.get("source_artifacts") or {}),
        "summary": dict(report.get("summary") or {}),
        "artifacts": {
            "json": {
                "path": str(resolved_report),
                "sha256": sha256_file(resolved_report),
            },
            "markdown": {
                "path": str(resolved_markdown),
                "sha256": sha256_file(resolved_markdown),
            },
        },
        "policy": dict(report.get("policy") or {}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return write_json(manifest_path, payload)

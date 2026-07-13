from __future__ import annotations

import hashlib
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import REPORT_CONTRACT_VERSION, SOURCE_PROJECT


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
    upstream_repo_shas: Mapping[str, str] | None = None,
    input_paths: Mapping[str, str | Path] | None = None,
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

    source_artifact_metadata = {}
    for name, raw_path in (input_paths or {}).items():
        if raw_path is None:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        metadata: dict[str, Any] = {"path": str(path), "sha256": sha256_file(path)}
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                metadata["schema"] = ",".join(reader.fieldnames or [])
                as_of_values = sorted({str(row.get("as_of", "")).strip() for row in reader if row.get("as_of")})
                if as_of_values:
                    metadata["as_of"] = as_of_values[-1]
        elif path.suffix.lower() == ".json":
            try:
                source = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(source, dict):
                    metadata.update({"schema": "invalid_json", "warning": "invalid_json_metadata"})
                    source = None
                if source is None:
                    source_artifact_metadata[name] = metadata
                    continue
                metadata.update(
                    {
                        "as_of": source.get("as_of", ""),
                        "generated_at": source.get("generated_at", ""),
                        "expires_at": source.get("expires_at", ""),
                        "schema": str(source.get("schema_version", "")),
                    }
                )
            except (OSError, json.JSONDecodeError):
                metadata["schema"] = "invalid_json"
        source_artifact_metadata[name] = metadata

    payload = {
        "manifest_type": "model_recommendation_report",
        "artifact_type": "model_recommendations",
        "contract_version": REPORT_CONTRACT_VERSION,
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
        "source_artifacts_metadata": {
            "schema_version": "1",
            "items": source_artifact_metadata,
        },
        "upstream_repositories": dict(upstream_repo_shas or {}),
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

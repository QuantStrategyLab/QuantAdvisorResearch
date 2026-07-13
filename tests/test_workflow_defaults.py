from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_workflows_default_to_actions_artifact_inputs() -> None:
    for workflow in ("weekly_advisory_review.yml", "publish_advisory_site.yml", "monthly_advisory_review.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "./advisor/.github/actions/download-upstream-artifacts" in text
        assert "secrets.QSL_REPO_SYNC_TOKEN" in text
        assert "steps.upstream.outputs.political_events" in text
        assert "steps.upstream.outputs.political_watchlist" in text
        assert "steps.upstream.outputs.source_lineage" in text
        assert "github.event.inputs.political_events_run_id" in text
        assert "github.event.inputs.theme_momentum_run_id" in text
        assert "--source-lineage" in text
        assert "examples/political_events.example.csv" not in text
        assert "examples/political_watchlist.example.csv" not in text
        assert "steps.upstream.outputs.theme_momentum" in text
        assert "market_confirmation_path" in text
        assert "scripts/build_advisory_artifacts.py" in text
        assert "scripts/build_market_confirmation.py" not in text
        assert "market_data_proxy_urls" in text
        assert "MARKET_DATA_PROXY_POOL_URL" in text
        assert "actions/cache/restore@v5" in text
        assert "actions/cache/save@v5" in text
        assert "--market-cache-dir .cache/market-data" in text
        assert "--recommendation-review" in text


def test_cross_repo_smoke_workflow_uses_live_artifacts_and_no_network_market_fallback() -> None:
    text = (ROOT / ".github" / "workflows" / "cross_repo_smoke.yml").read_text(encoding="utf-8")

    assert "./advisor/.github/actions/download-upstream-artifacts" in text
    assert "secrets.QSL_REPO_SYNC_TOKEN" in text
    assert "steps.upstream.outputs.political_events" in text
    assert "steps.upstream.outputs.political_watchlist" in text
    assert "steps.upstream.outputs.theme_momentum" in text
    assert "steps.upstream.outputs.source_lineage" in text
    assert "github.event.inputs.political_events_run_id" in text
    assert "github.event.inputs.theme_momentum_run_id" in text
    assert "scripts/run_cross_repo_smoke.py" in text


def test_upstream_artifact_action_binds_actions_identity_and_downloaded_hash() -> None:
    text = (ROOT / ".github" / "actions" / "download-upstream-artifacts" / "action.yml").read_text(encoding="utf-8")

    assert "${RUNNER_TEMP}" in text
    assert "gh run download" in text
    assert "event=schedule" in text
    assert "workflow_dispatch" in text
    assert "workflow_run_id" in text
    assert "workflow_head_sha" in text
    assert "artifact_id" in text
    assert "artifact_name" in text
    assert "sha256" in text

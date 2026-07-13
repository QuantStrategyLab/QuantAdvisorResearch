from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_workflows_default_to_live_event_inputs() -> None:
    for workflow in ("weekly_advisory_review.yml", "publish_advisory_site.yml", "monthly_advisory_review.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert "data/live/political_events.csv" in text
        assert "data/live/political_watchlist.csv" in text
        assert "examples/political_events.example.csv" not in text
        assert "examples/political_watchlist.example.csv" not in text
        assert "QuantStrategyLab/ResearchSignalContextPipelines" in text
        assert "research-signal-context" in text
        assert "market_confirmation_path" in text
        assert "scripts/build_advisory_artifacts.py" in text
        assert "scripts/build_market_confirmation.py" not in text
        assert "market_data_proxy_urls" in text
        assert "MARKET_DATA_PROXY_POOL_URL" in text
        assert "actions/cache/restore@v5" in text
        assert "actions/cache/save@v5" in text
        assert "--market-cache-dir .cache/market-data" in text
        assert "--recommendation-review" in text
        assert "reference_time:" in text
        assert "INPUT_REFERENCE_TIME:" in text
        assert 'REFERENCE_TIME="${INPUT_REFERENCE_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"' in text
        assert '--reference-time "${REFERENCE_TIME}"' in text


def test_cross_repo_smoke_workflow_uses_live_artifacts_and_no_network_market_fallback() -> None:
    text = (ROOT / ".github" / "workflows" / "cross_repo_smoke.yml").read_text(encoding="utf-8")

    assert "QuantStrategyLab/PoliticalEventTrackingResearch" in text
    assert "QuantStrategyLab/ResearchSignalContextPipelines" in text
    assert "data/live/political_events.csv" in text
    assert "data/live/political_watchlist.csv" in text
    assert "data/output/latest_signal.json" in text
    assert "data/output/theme_momentum_snapshot.json" in text
    assert "scripts/run_cross_repo_smoke.py" in text
    assert "reference_time:" in text
    assert "INPUT_REFERENCE_TIME:" in text
    assert 'REFERENCE_TIME="${INPUT_REFERENCE_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"' in text
    assert '--reference-time "${REFERENCE_TIME}"' in text

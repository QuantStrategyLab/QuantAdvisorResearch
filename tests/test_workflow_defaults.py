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

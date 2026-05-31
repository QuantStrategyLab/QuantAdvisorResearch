from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from quant_advisor_research.market_confirmation import PriceBar, write_cached_bars
from quant_advisor_research.recommendation_review import (
    build_recommendation_review,
    render_recommendation_review_markdown,
)


def make_bars(start: dt.date, prices: list[float]) -> list[PriceBar]:
    return [
        PriceBar(date=start + dt.timedelta(days=index), close=price, volume=1000 + index)
        for index, price in enumerate(prices)
    ]


def write_report(path: Path, *, as_of: str = "2026-01-05") -> None:
    path.write_text(
        json.dumps(
            {
                "as_of": as_of,
                "cadence": "weekly",
                "final_decisions": {
                    "recommendations": [
                        {
                            "symbol": "MU",
                            "name": "Micron Technology",
                            "primary_horizon": "medium",
                            "primary_horizon_label": "中线",
                            "combined_score": 0.84,
                            "source_score": 0.2,
                            "momentum_score": 0.9,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def test_recommendation_review_calculates_forward_relative_return_from_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", make_bars(dt.date(2026, 1, 5), [100, 102, 105, 108, 112, 116]), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 1, 5), [100, 101, 102, 103, 104, 105]), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path)

    review = build_recommendation_review(
        report_paths=[report_path],
        as_of=dt.date(2026, 1, 10),
        benchmark="SPY",
        cache_dir=cache_dir,
        cache_max_age_days=14,
        use_network=False,
    )

    item = review["review_items"][0]
    assert item["symbol"] == "MU"
    assert item["absolute_return"] == 0.16
    assert item["benchmark_return"] == 0.05
    assert item["relative_return"] == 0.11
    assert item["outcome"] == "outperforming"
    assert review["summary"]["evaluated_count"] == 1
    assert review["summary"]["top_outperformers"] == ["MU"]
    assert "MU" in render_recommendation_review_markdown(review)


def test_recommendation_review_marks_same_day_report_as_pending(tmp_path: Path) -> None:
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path)

    review = build_recommendation_review(
        report_paths=[report_path],
        as_of=dt.date(2026, 1, 5),
        benchmark="SPY",
        cache_dir=tmp_path / "missing-cache",
        cache_max_age_days=14,
        use_network=False,
    )

    assert review["review_items"][0]["outcome"] == "pending"
    assert review["summary"]["pending_count"] == 1
    assert review["summary"]["insufficient_price_data_count"] == 0

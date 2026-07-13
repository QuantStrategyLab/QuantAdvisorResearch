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


def write_report(path: Path, *, as_of: str = "2026-01-05", horizon: str = "medium", symbol: str = "MU") -> None:
    path.write_text(
        json.dumps(
            {
                "as_of": as_of,
                "cadence": "weekly",
                "final_decisions": {
                    "recommendations": [
                        {
                            "symbol": symbol,
                            "name": "Micron Technology",
                            "primary_horizon": horizon,
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


def test_recommendation_review_keeps_short_review_in_progress_until_ten_trading_days(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", make_bars(dt.date(2026, 1, 5), [100, 102, 105, 108, 112, 116]), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 1, 5), [100, 101, 102, 103, 104, 105]), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path, horizon="short")

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
    assert item["maturity_status"] == "in_progress"
    assert item["outcome"] == "in_progress"
    assert review["summary"]["evaluated_count"] == 0
    assert review["summary"]["by_horizon"]["short"]["evaluated_count"] == 0
    assert "MU" in render_recommendation_review_markdown(review)


def test_recommendation_review_reports_matured_metrics_by_horizon(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    prices = [100 + index for index in range(12)]
    write_cached_bars("MU", make_bars(dt.date(2026, 1, 5), prices), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 1, 5), [100] * 12), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path, horizon="short")

    review = build_recommendation_review(
        report_paths=[report_path], as_of=dt.date(2026, 1, 20), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=30, use_network=False,
    )

    item = review["review_items"][0]
    assert item["maturity_status"] == "matured"
    assert item["outcome"] == "outperforming"
    short_summary = review["summary"]["by_horizon"]["short"]
    assert short_summary["sample_size"] == 1
    assert short_summary["median_relative_return"] == short_summary["average_relative_return"]
    assert short_summary["hit_rate"] == 1.0


def test_top_outperformers_are_unique_and_grouped_by_horizon(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", make_bars(dt.date(2026, 1, 5), [100] * 15), cache_dir=cache_dir)
    write_cached_bars("AMD", make_bars(dt.date(2026, 1, 5), [100 + index for index in range(15)]), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 1, 5), [100] * 15), cache_dir=cache_dir)
    reports = []
    for index, (symbol, horizon) in enumerate((("AMD", "short"), ("AMD", "short"), ("MU", "medium"))):
        path = tmp_path / f"report-{index}.json"
        write_report(path, horizon=horizon, symbol=symbol)
        reports.append(path)

    review = build_recommendation_review(
        report_paths=reports, as_of=dt.date(2026, 1, 25), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=14, use_network=False,
    )

    assert review["summary"]["top_outperformers"] == ["AMD"]
    assert review["summary"]["by_horizon"]["short"]["top_outperformers"] == ["AMD"]


def test_long_horizon_cannot_be_labeled_lagging_after_a_few_weeks(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("TSM", make_bars(dt.date(2026, 1, 5), [100, 90, 80, 70, 60]), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 1, 5), [100] * 5), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path, horizon="long", symbol="TSM")

    review = build_recommendation_review(
        report_paths=[report_path], as_of=dt.date(2026, 1, 30), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=30, use_network=False,
    )

    item = review["review_items"][0]
    assert item["elapsed_calendar_days"] > 14
    assert item["maturity_status"] == "in_progress"
    assert item["outcome"] == "in_progress"


def test_review_requires_price_coverage_on_or_before_report_date(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", make_bars(dt.date(2026, 2, 1), [100] * 300), cache_dir=cache_dir)
    write_cached_bars("SPY", make_bars(dt.date(2026, 2, 1), [100] * 300), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path, horizon="long")

    review = build_recommendation_review(
        report_paths=[report_path], as_of=dt.date(2026, 11, 1), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=400, use_network=False,
    )

    item = review["review_items"][0]
    assert item["start_price_date"] == ""
    assert item["maturity_status"] == "insufficient_price_data"
    assert item["outcome"] == "insufficient_price_data"


def test_weekend_report_uses_previous_trading_close(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    trading_dates = [dt.date(2026, 1, 9), dt.date(2026, 1, 12), dt.date(2026, 1, 13)]
    write_cached_bars("MU", [PriceBar(date=date, close=100 + index, volume=1000) for index, date in enumerate(trading_dates)], cache_dir=cache_dir)
    write_cached_bars("SPY", [PriceBar(date=date, close=100, volume=1000) for date in trading_dates], cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-10.json"
    write_report(report_path, as_of="2026-01-10", horizon="short")

    review = build_recommendation_review(
        report_paths=[report_path], as_of=dt.date(2026, 1, 20), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=14, use_network=False,
    )

    assert review["review_items"][0]["start_price_date"] == "2026-01-09"


def test_pre_maturity_item_stays_in_progress_when_benchmark_is_unavailable(tmp_path: Path) -> None:
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", make_bars(dt.date(2026, 1, 5), [100] * 6), cache_dir=cache_dir)
    report_path = tmp_path / "advisory_report_2026-01-05.json"
    write_report(report_path, horizon="short")

    review = build_recommendation_review(
        report_paths=[report_path], as_of=dt.date(2026, 1, 10), benchmark="SPY",
        cache_dir=cache_dir, cache_max_age_days=14, use_network=False,
    )

    item = review["review_items"][0]
    assert item["maturity_status"] == "in_progress"
    assert item["outcome"] == "in_progress"


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

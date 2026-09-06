from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from pathlib import Path
from typing import Any

from .advisory_report import display_percent, write_json, write_text
from .market_confirmation import (
    PriceBar,
    fetch_bars_with_cache,
    load_cached_bars,
    load_proxy_urls,
)


HORIZON_LABELS_ZH = {
    "short": "短线",
    "medium": "中线",
    "long": "长线",
}
MIN_MATURITY_TRADING_DAYS = {"short": 10, "medium": 10, "long": 252}
MAX_START_BAR_DELAY_DAYS = 7


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value.strip())


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def final_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = report.get("final_decisions")
    if not isinstance(decisions, dict):
        return []
    recommendations = decisions.get("recommendations", [])
    return [item for item in recommendations if isinstance(item, dict) and item.get("symbol")]


def first_bar_on_or_after(bars: list[PriceBar], target: dt.date) -> PriceBar | None:
    for bar in sorted(bars, key=lambda item: item.date):
        if bar.date >= target:
            if (bar.date - target).days <= MAX_START_BAR_DELAY_DAYS:
                return bar
            return None
    return None


def start_bar_for_report(bars: list[PriceBar], target: dt.date) -> PriceBar | None:
    ordered = sorted(bars, key=lambda item: item.date)
    exact = next((bar for bar in ordered if bar.date == target), None)
    if exact:
        return exact
    previous = last_bar_on_or_before(ordered, target)
    if previous and (target - previous.date).days <= MAX_START_BAR_DELAY_DAYS:
        return previous
    return first_bar_on_or_after(ordered, target)


def last_bar_on_or_before(bars: list[PriceBar], target: dt.date) -> PriceBar | None:
    candidates = [bar for bar in bars if bar.date <= target]
    return max(candidates, key=lambda item: item.date) if candidates else None


def return_between(start: PriceBar, end: PriceBar) -> float:
    if start.close <= 0:
        return 0.0
    return round(end.close / start.close - 1, 6)


def outcome_label(
    relative_return: float | None,
    *,
    elapsed_days: int,
    has_price_data: bool,
    horizon: str,
    trading_intervals: int,
) -> str:
    if elapsed_days <= 0:
        return "pending"
    if not has_price_data:
        return "insufficient_price_data"
    if trading_intervals < MIN_MATURITY_TRADING_DAYS.get(horizon, MIN_MATURITY_TRADING_DAYS["medium"]):
        return "in_progress"
    if relative_return is None:
        return "insufficient_price_data"
    if relative_return >= 0.02:
        return "outperforming"
    if relative_return <= -0.02:
        return "lagging"
    return "inline"


def load_review_bars(
    symbol: str,
    *,
    as_of: dt.date,
    proxy_urls: list[str],
    cache_dir: str | Path | None,
    cache_max_age_days: int,
    use_network: bool,
) -> tuple[list[PriceBar], str]:
    if use_network:
        bars, data_source, _warning = fetch_bars_with_cache(
            symbol,
            as_of=as_of,
            proxy_urls=proxy_urls,
            cache_dir=cache_dir,
            cache_max_age_days=cache_max_age_days,
        )
        return bars, data_source
    return (
        load_cached_bars(symbol, as_of=as_of, cache_dir=cache_dir, max_age_days=cache_max_age_days),
        "yahoo_chart_cache",
    )



def publicly_available_date(report: dict[str, Any]) -> dt.date:
    """Return the first date the recommendation was publicly available.

    Review returns and maturity must start from publication time (`generated_at`),
    not the research cutoff (`as_of`), to avoid scoring look-ahead before release.
    """

    generated_at = str(report.get("generated_at") or "").strip()
    if generated_at:
        normalized = generated_at.replace("Z", "+00:00")
        try:
            return dt.datetime.fromisoformat(normalized).date()
        except ValueError:
            pass
    return parse_date(str(report.get("as_of", "")))

def build_review_item(
    *,
    pick: dict[str, Any],
    report_as_of: dt.date,
    review_as_of: dt.date,
    symbol_bars: list[PriceBar],
    benchmark_bars: list[PriceBar],
    data_source: str,
) -> dict[str, Any]:
    symbol = str(pick.get("symbol", "")).upper()
    start_bar = start_bar_for_report(symbol_bars, report_as_of)
    end_bar = last_bar_on_or_before(symbol_bars, review_as_of)
    benchmark_start = start_bar_for_report(benchmark_bars, report_as_of)
    benchmark_end = last_bar_on_or_before(benchmark_bars, review_as_of)
    has_price_data = bool(start_bar and end_bar and start_bar.date <= end_bar.date)

    absolute_return: float | None = None
    benchmark_return: float | None = None
    relative_return: float | None = None
    trading_observations = 0
    start_date = ""
    end_date = ""
    if has_price_data and start_bar and end_bar:
        start_date = start_bar.date.isoformat()
        end_date = end_bar.date.isoformat()
        trading_observations = sum(1 for bar in symbol_bars if start_bar.date <= bar.date <= end_bar.date)
        absolute_return = return_between(start_bar, end_bar)
        if benchmark_start and benchmark_end and benchmark_start.date <= benchmark_end.date:
            benchmark_return = return_between(benchmark_start, benchmark_end)
            relative_return = round(absolute_return - benchmark_return, 6)

    elapsed_days = (review_as_of - report_as_of).days
    horizon = str(pick.get("primary_horizon", ""))
    maturity_days = MIN_MATURITY_TRADING_DAYS.get(horizon, MIN_MATURITY_TRADING_DAYS["medium"])
    trading_intervals = max(trading_observations - 1, 0)
    if elapsed_days <= 0:
        maturity_status = "pending"
    elif not has_price_data:
        maturity_status = "insufficient_price_data"
    elif trading_intervals < maturity_days:
        maturity_status = "in_progress"
    else:
        maturity_status = "matured"
    return {
        "report_as_of": report_as_of.isoformat(),
        "review_as_of": review_as_of.isoformat(),
        "symbol": symbol,
        "name": str(pick.get("name", "")),
        "primary_horizon": horizon,
        "primary_horizon_label": str(pick.get("primary_horizon_label", "")),
        "start_price_date": start_date,
        "end_price_date": end_date,
        "elapsed_calendar_days": elapsed_days,
        "trading_observations": trading_observations,
        "trading_intervals": trading_intervals,
        "maturity_required_trading_days": maturity_days,
        "maturity_status": maturity_status,
        "absolute_return": absolute_return,
        "benchmark_return": benchmark_return,
        "relative_return": relative_return,
        "outcome": outcome_label(
            relative_return,
            elapsed_days=elapsed_days,
            has_price_data=has_price_data,
            horizon=horizon,
            trading_intervals=trading_intervals,
        ),
        "market_data_source": data_source if has_price_data else "",
        "combined_score": pick.get("combined_score"),
        "source_score": pick.get("source_score"),
        "momentum_score": pick.get("momentum_score"),
    }


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None


def summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        item
        for item in items
        if item.get("maturity_status") == "matured" and isinstance(item.get("relative_return"), (int, float))
    ]
    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in ("short", "medium", "long"):
        horizon_items = [item for item in items if item.get("primary_horizon") == horizon]
        horizon_evaluated = [item for item in evaluated if item.get("primary_horizon") == horizon]
        horizon_returns = [float(item["relative_return"]) for item in horizon_evaluated]
        horizon_ranked = sorted(
            [item for item in horizon_evaluated if item.get("outcome") == "outperforming"],
            key=lambda item: (float(item.get("relative_return", 0)), str(item.get("symbol", ""))),
            reverse=True,
        )
        by_horizon[horizon] = {
            "label": HORIZON_LABELS_ZH[horizon],
            "item_count": len(horizon_items),
            "evaluated_count": len(horizon_evaluated),
            "sample_size": len(horizon_evaluated),
            "pending_count": sum(1 for item in horizon_items if item.get("outcome") == "pending"),
            "in_progress_count": sum(1 for item in horizon_items if item.get("outcome") == "in_progress"),
            "matured_count": sum(1 for item in horizon_items if item.get("maturity_status") == "matured"),
            "insufficient_price_data_count": sum(
                1 for item in horizon_items if item.get("outcome") == "insufficient_price_data"
            ),
            "average_relative_return": average(horizon_returns),
            "median_relative_return": median(horizon_returns),
            "hit_rate": round(
                sum(1 for item in horizon_evaluated if item.get("outcome") == "outperforming") / len(horizon_evaluated),
                6,
            )
            if horizon_evaluated
            else None,
            "top_outperformers": unique_symbols(horizon_ranked),
        }
    ranked = sorted(
        [item for item in evaluated if item.get("outcome") == "outperforming"],
        key=lambda item: (float(item.get("relative_return", 0)), str(item.get("symbol", ""))),
        reverse=True,
    )
    return {
        "item_count": len(items),
        "evaluated_count": len(evaluated),
        "pending_count": sum(1 for item in items if item.get("outcome") == "pending"),
        "insufficient_price_data_count": sum(1 for item in items if item.get("outcome") == "insufficient_price_data"),
        # Do not pool short-, medium-, and long-horizon performance into one statistic.
        "average_relative_return": None,
        "median_relative_return": None,
        "hit_rate": None,
        "by_horizon": by_horizon,
        "top_outperformers": unique_symbols(ranked)[:5],
    }


def unique_symbols(items: list[dict[str, Any]]) -> list[str]:
    symbols: list[str] = []
    for item in items:
        symbol = str(item.get("symbol", ""))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:5]


def build_recommendation_review(
    *,
    report_paths: list[str | Path],
    as_of: dt.date,
    benchmark: str = "SPY",
    cache_dir: str | Path | None = None,
    cache_max_age_days: int = 14,
    proxy_urls: list[str] | None = None,
    use_network: bool = False,
) -> dict[str, Any]:
    proxy_urls = proxy_urls or []
    reports = [load_report(path) for path in report_paths]
    benchmark_bars, benchmark_source = load_review_bars(
        benchmark,
        as_of=as_of,
        proxy_urls=proxy_urls,
        cache_dir=cache_dir,
        cache_max_age_days=cache_max_age_days,
        use_network=use_network,
    )
    bars_by_symbol: dict[str, tuple[list[PriceBar], str]] = {}
    items: list[dict[str, Any]] = []
    data_quality_warnings: list[str] = []
    if not benchmark_bars:
        data_quality_warnings.append(f"Benchmark {benchmark} price bars are unavailable; relative returns may be missing.")

    for report in reports:
        report_as_of = publicly_available_date(report)
        for pick in final_recommendations(report):
            symbol = str(pick.get("symbol", "")).upper()
            if symbol not in bars_by_symbol:
                try:
                    bars_by_symbol[symbol] = load_review_bars(
                        symbol,
                        as_of=as_of,
                        proxy_urls=proxy_urls,
                        cache_dir=cache_dir,
                        cache_max_age_days=cache_max_age_days,
                        use_network=use_network,
                    )
                except Exception as exc:  # noqa: BLE001 - review artifacts should degrade gracefully.
                    data_quality_warnings.append(f"{symbol}: price bars unavailable ({type(exc).__name__}).")
                    bars_by_symbol[symbol] = ([], "")
            symbol_bars, data_source = bars_by_symbol[symbol]
            items.append(
                build_review_item(
                    pick=pick,
                    report_as_of=report_as_of,
                    review_as_of=as_of,
                    symbol_bars=symbol_bars,
                    benchmark_bars=benchmark_bars,
                    data_source=data_source,
                )
            )

    return {
        "schema_version": "2",
        "mode": "recommendation_review",
        "as_of": as_of.isoformat(),
        "generated_at": utc_now_iso(),
        "benchmark": benchmark,
        "benchmark_data_source": benchmark_source if benchmark_bars else "",
        "source_reports": [str(path) for path in report_paths],
        "summary": summarize_items(items),
        "review_items": items,
        "data_quality_warnings": data_quality_warnings,
        "policy": {
            "execution_allowed": False,
            "portfolio_allocation_allowed": False,
            "personalized_advice_allowed": False,
            "downstream_use": "Point-in-time recommendation follow-up review only.",
        },
    }


def render_recommendation_review_markdown(review: dict[str, Any]) -> str:
    lines = [f"# 推荐复盘 - {review.get('as_of', '')}", ""]
    summary = review.get("summary", {})
    lines.extend(
        [
            "## 汇总",
            "",
            f"- 复盘条目：{summary.get('item_count', 0)}",
            f"- 已可评估：{summary.get('evaluated_count', 0)}",
            f"- 待观察：{summary.get('pending_count', 0)}",
            f"- 进行中：{sum(item.get('in_progress_count', 0) for item in summary.get('by_horizon', {}).values())}",
            f"- 缺少价格数据：{summary.get('insufficient_price_data_count', 0)}",
            "- 不同持有期不合并计算平均收益；以下按周期分别统计。",
            "",
            "## 周期分布",
            "",
        ]
    )
    for horizon in ("long", "medium", "short"):
        item = summary.get("by_horizon", {}).get(horizon, {})
        lines.append(
            f"- {item.get('label', horizon)}：{item.get('evaluated_count', 0)}/{item.get('item_count', 0)} 已评估，"
            f"样本量 {item.get('sample_size', 0)}，平均 {display_percent(item.get('average_relative_return'))}，"
            f"中位数 {display_percent(item.get('median_relative_return'))}，命中率 {display_percent(item.get('hit_rate'))}，"
            f"领先标的 {', '.join(item.get('top_outperformers', [])) or '暂无'}"
        )
    warnings = review.get("data_quality_warnings", [])
    if warnings:
        lines.extend(["", "## 数据质量提示", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "## 明细", ""])
    for item in review.get("review_items", []):
        lines.extend(
            [
                f"### {item.get('symbol')} - {item.get('name')}",
                f"- 推荐日期：{item.get('report_as_of')}；复盘日期：{item.get('review_as_of')}",
                f"- 周期：{item.get('primary_horizon_label') or item.get('primary_horizon')}",
                f"- 价格区间：{item.get('start_price_date') or '无'} 到 {item.get('end_price_date') or '无'}",
                f"- 绝对收益：{display_percent(item.get('absolute_return'))}",
                f"- 相对 {review.get('benchmark')}：{display_percent(item.get('relative_return'))}",
                f"- 成熟度：{item.get('maturity_status')}（需要 {item.get('maturity_required_trading_days', 0)} 个交易日，"
                f"当前 {item.get('trading_observations', 0)} 个）",
                f"- 状态：{item.get('outcome')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build recommendation follow-up review from advisory reports.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--reports", nargs="+", required=True, help="Advisory report JSON files to review.")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--cache-dir")
    parser.add_argument("--cache-max-age-days", type=int, default=14)
    parser.add_argument("--proxy-list")
    parser.add_argument("--proxy-urls", default="")
    parser.add_argument("--proxy-pool-url", default="")
    parser.add_argument("--use-network", action="store_true", help="Fetch missing bars instead of cache-only review.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    proxy_urls = load_proxy_urls(
        proxy_list_path=args.proxy_list,
        proxy_urls_text=args.proxy_urls,
        proxy_pool_url=args.proxy_pool_url,
    )
    review = build_recommendation_review(
        report_paths=args.reports,
        as_of=parse_date(args.as_of),
        benchmark=args.benchmark,
        cache_dir=args.cache_dir,
        cache_max_age_days=args.cache_max_age_days,
        proxy_urls=proxy_urls,
        use_network=args.use_network,
    )
    write_json(args.output_json, review)
    write_text(args.output_md, render_recommendation_review_markdown(review))


if __name__ == "__main__":
    main()

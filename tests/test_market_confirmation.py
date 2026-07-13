from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from urllib.error import URLError

import pytest
import quant_advisor_research.market_confirmation as market_confirmation_module
from quant_advisor_research.market_confirmation import (
    PriceBar,
    build_market_confirmation_rows,
    collect_symbols,
    compute_market_confirmation,
    load_proxy_urls,
    write_cached_bars,
    write_market_confirmation_csv,
)


def make_bars(start: dt.date, prices: list[float], *, base_volume: float = 100.0) -> list[PriceBar]:
    return [
        PriceBar(date=start + dt.timedelta(days=index), close=price, volume=base_volume + index)
        for index, price in enumerate(prices)
    ]


def test_compute_market_confirmation_uses_relative_strength_volume_drawdown_and_volatility() -> None:
    start = dt.date(2026, 1, 1)
    symbol_prices = [100 + index * 1.2 for index in range(70)]
    benchmark_prices = [100 + index * 0.2 for index in range(70)]
    symbol_bars = make_bars(start, symbol_prices, base_volume=100)
    # Make recent volume visibly higher than the baseline.
    symbol_bars = symbol_bars[:-5] + [
        PriceBar(date=bar.date, close=bar.close, volume=260 + index * 5)
        for index, bar in enumerate(symbol_bars[-5:])
    ]
    benchmark_bars = make_bars(start, benchmark_prices, base_volume=1000)

    row = compute_market_confirmation(
        "MU",
        symbol_bars,
        benchmark_bars,
        data_source="unit_test",
        requested_as_of=dt.date(2026, 3, 15),
    )

    assert row is not None
    assert row.symbol == "MU"
    assert row.return_20d > 0
    assert row.relative_return_20d > 0
    assert row.relative_return_63d > 0
    assert row.volume_zscore > 0
    assert row.drawdown_63d == 0
    assert 0 <= row.market_score <= 1
    assert row.market_score > 0.5
    assert row.price_age_days == 4
    assert row.confirmation_quality == "price_observed"


def test_extreme_return_is_marked_as_data_quality_anomaly() -> None:
    start = dt.date(2026, 1, 1)
    symbol_bars = make_bars(start, [100.0] * 69 + [350.0])
    benchmark_bars = make_bars(start, [100.0] * 70)

    row = compute_market_confirmation("MU", symbol_bars, benchmark_bars, data_source="unit_test")

    assert row is not None
    assert row.confirmation_quality == "anomalous"
    assert "extreme_return_63d" in row.warnings


def test_market_confirmation_falls_back_to_theme_momentum_without_network(tmp_path: Path) -> None:
    theme_payload = {
        "as_of": "2026-05-29",
        "theme_ranks": [
            {
                "theme_id": "hbm_memory",
                "top_symbols": [
                    {"symbol": "MU", "return_3m": 0.42, "momentum_score": 1.2},
                    {"symbol": "SOXX", "return_3m": 0.15, "momentum_score": 0.5},
                ],
            }
        ],
    }
    rows = build_market_confirmation_rows(
        symbols=["MU", "SOXX"],
        as_of=dt.date(2026, 5, 31),
        theme_momentum=theme_payload,
        use_network=False,
    )

    assert [row.symbol for row in rows] == ["MU", "SOXX"]
    assert rows[0].data_source == "theme_momentum_fallback"
    assert rows[0].return_63d == 0.42
    assert rows[0].market_score == 0.8
    assert rows[0].price_age_days == 2
    assert rows[0].confirmation_quality == "fallback_only"

    output = tmp_path / "market_confirmation.csv"
    write_market_confirmation_csv(output, rows)
    text = output.read_text(encoding="utf-8")
    assert "market_score" in text
    assert "confirmation_quality" in text
    assert "theme_momentum_fallback" in text


def test_collect_symbols_reads_watchlist_signal_and_theme_momentum(tmp_path: Path) -> None:
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text(
        "symbol,name,bucket,research_status,thesis,source_url\nMU,Micron,policy_capital,watch,x,https://example.invalid\n",
        encoding="utf-8",
    )
    signal = tmp_path / "latest_signal.json"
    signal.write_text(
        json.dumps(
            {
                "universe": ["QQQ", "AMD"],
                "symbol_bias": {"VRT": {"bias": "positive"}},
                "symbol_theme_exposure": {"DELL": ["ai_server_infrastructure"]},
            }
        ),
        encoding="utf-8",
    )
    theme = {
        "theme_ranks": [
            {"top_symbols": [{"symbol": "INTC"}, {"symbol": "SPY"}]},
        ]
    }

    symbols = collect_symbols(political_watchlist_path=watchlist, ai_signal_path=signal, theme_momentum=theme)

    assert symbols == ["AMD", "DELL", "INTC", "MU", "VRT"]


def test_load_proxy_urls_normalizes_dedupes_local_and_inline_inputs(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "\n".join(
            [
                "# comment",
                "1.2.3.4:8080",
                "http://5.6.7.8:3128 extra-column",
                "1.2.3.4:8080",
            ]
        ),
        encoding="utf-8",
    )

    proxies = load_proxy_urls(proxy_list_path=proxy_file, proxy_urls_text="https://9.9.9.9:9443, 5.6.7.8:3128")

    assert proxies == [
        "https://9.9.9.9:9443",
        "http://5.6.7.8:3128",
        "http://1.2.3.4:8080",
    ]


def test_market_confirmation_retries_with_proxy_when_direct_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    start = dt.date(2026, 1, 1)
    bars = make_bars(start, [100 + index for index in range(70)], base_volume=100)
    calls: list[tuple[str, str | None]] = []

    def fake_fetch_yahoo_bars(
        symbol: str,
        *,
        as_of: dt.date,
        lookback_days: int = 460,
        timeout: int = 20,
        proxy_url: str | None = None,
    ) -> list[PriceBar]:
        calls.append((symbol, proxy_url))
        if proxy_url is None:
            raise URLError("rate limited")
        return bars

    monkeypatch.setattr(market_confirmation_module, "fetch_yahoo_bars", fake_fetch_yahoo_bars)

    rows = build_market_confirmation_rows(
        symbols=["MU"],
        as_of=dt.date(2026, 5, 31),
        benchmark="SPY",
        proxy_urls=["http://127.0.0.1:8080"],
        request_pause_seconds=0,
    )

    assert rows[0].symbol == "MU"
    assert rows[0].data_source == "yahoo_chart_proxy"
    assert ("MU", None) in calls
    assert ("MU", "http://127.0.0.1:8080") in calls


def test_market_confirmation_uses_cached_price_bars_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = dt.date(2026, 1, 1)
    symbol_bars = make_bars(start, [100 + index for index in range(70)], base_volume=100)
    benchmark_bars = make_bars(start, [100 + index * 0.2 for index in range(70)], base_volume=1000)
    cache_dir = tmp_path / "market-cache"
    write_cached_bars("MU", symbol_bars, cache_dir=cache_dir)
    write_cached_bars("SPY", benchmark_bars, cache_dir=cache_dir)

    def fail_fetch(*args: object, **kwargs: object) -> tuple[list[PriceBar], str]:
        raise URLError("temporary outage")

    monkeypatch.setattr(market_confirmation_module, "fetch_yahoo_bars_with_fallback", fail_fetch)

    rows = build_market_confirmation_rows(
        symbols=["MU"],
        as_of=dt.date(2026, 3, 15),
        benchmark="SPY",
        request_pause_seconds=0,
        cache_dir=cache_dir,
        cache_max_age_days=14,
    )

    assert rows[0].symbol == "MU"
    assert rows[0].data_source == "yahoo_chart_cache"
    assert rows[0].confirmation_quality == "price_observed"
    assert rows[0].warnings == "price_cache_used"

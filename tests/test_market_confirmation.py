from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from quant_advisor_research.market_confirmation import (
    PriceBar,
    build_market_confirmation_rows,
    collect_symbols,
    compute_market_confirmation,
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

    row = compute_market_confirmation("MU", symbol_bars, benchmark_bars, data_source="unit_test")

    assert row is not None
    assert row.symbol == "MU"
    assert row.return_20d > 0
    assert row.relative_return_20d > 0
    assert row.relative_return_63d > 0
    assert row.volume_zscore > 0
    assert row.drawdown_63d == 0
    assert 0 <= row.market_score <= 1
    assert row.market_score > 0.5


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

    output = tmp_path / "market_confirmation.csv"
    write_market_confirmation_csv(output, rows)
    text = output.read_text(encoding="utf-8")
    assert "market_score" in text
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

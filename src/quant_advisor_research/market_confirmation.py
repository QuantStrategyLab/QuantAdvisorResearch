from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .advisory_report import as_float, clamp
from .csv_utils import read_csv_rows


DEFAULT_OUTPUT_FIELDS = [
    "symbol",
    "as_of",
    "return_5d",
    "return_20d",
    "return_63d",
    "relative_return_20d",
    "relative_return_63d",
    "volume_zscore",
    "drawdown_63d",
    "volatility_21d",
    "market_score",
    "data_source",
    "price_observation_count",
    "price_age_days",
    "confirmation_quality",
    "warnings",
]

EXCLUDED_SYMBOLS = {
    "BIL",
    "BOXX",
    "DIA",
    "IWM",
    "QQQ",
    "SMH",
    "SOXL",
    "SOXX",
    "SPY",
    "TQQQ",
    "XLE",
    "XLK",
}


@dataclass(frozen=True)
class PriceBar:
    date: dt.date
    close: float
    volume: float


@dataclass(frozen=True)
class MarketConfirmationRow:
    symbol: str
    as_of: dt.date
    return_5d: float
    return_20d: float
    return_63d: float
    relative_return_20d: float
    relative_return_63d: float
    volume_zscore: float
    drawdown_63d: float
    volatility_21d: float
    market_score: float
    data_source: str
    price_observation_count: int
    price_age_days: int = 0
    confirmation_quality: str = "price_observed"
    warnings: str = ""

    def as_csv_row(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "return_5d": format_float(self.return_5d),
            "return_20d": format_float(self.return_20d),
            "return_63d": format_float(self.return_63d),
            "relative_return_20d": format_float(self.relative_return_20d),
            "relative_return_63d": format_float(self.relative_return_63d),
            "volume_zscore": format_float(self.volume_zscore),
            "drawdown_63d": format_float(self.drawdown_63d),
            "volatility_21d": format_float(self.volatility_21d),
            "market_score": format_float(self.market_score),
            "data_source": self.data_source,
            "price_observation_count": str(self.price_observation_count),
            "price_age_days": str(self.price_age_days),
            "confirmation_quality": self.confirmation_quality,
            "warnings": self.warnings,
        }


def format_float(value: float) -> str:
    return f"{value:.6f}"


def pct_return(bars: list[PriceBar], lookback: int) -> float:
    if len(bars) <= lookback:
        return 0.0
    start = bars[-lookback - 1].close
    end = bars[-1].close
    if start <= 0:
        return 0.0
    return end / start - 1


def daily_returns(bars: list[PriceBar]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        if previous.close > 0:
            returns.append(current.close / previous.close - 1)
    return returns


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def volume_zscore(bars: list[PriceBar]) -> float:
    if len(bars) < 25:
        return 0.0
    recent = bars[-5:]
    baseline = bars[-65:-5] if len(bars) >= 65 else bars[:-5]
    baseline_values = [bar.volume for bar in baseline if bar.volume > 0]
    if not baseline_values:
        return 0.0
    recent_avg = sum(bar.volume for bar in recent) / len(recent)
    baseline_avg = sum(baseline_values) / len(baseline_values)
    baseline_stdev = stdev(baseline_values)
    if baseline_stdev <= 0:
        return 0.0
    return (recent_avg - baseline_avg) / baseline_stdev


def drawdown(bars: list[PriceBar], lookback: int = 63) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    if not window:
        return 0.0
    high = max(bar.close for bar in window)
    if high <= 0:
        return 0.0
    return bars[-1].close / high - 1


def annualized_volatility(bars: list[PriceBar], lookback: int = 21) -> float:
    window = bars[-(lookback + 1) :] if len(bars) > lookback else bars
    return stdev(daily_returns(window)) * math.sqrt(252)


def compute_market_score(
    *,
    return_20d: float,
    return_63d: float,
    relative_return_20d: float,
    relative_return_63d: float,
    volume_zscore_value: float,
    drawdown_63d: float,
    volatility_21d: float,
) -> float:
    relative_20d = clamp(relative_return_20d / 0.20, -1, 1)
    relative_63d = clamp(relative_return_63d / 0.35, -1, 1)
    absolute_20d = clamp(return_20d / 0.20, -1, 1)
    absolute_63d = clamp(return_63d / 0.35, -1, 1)
    volume = clamp(volume_zscore_value / 3, 0, 1)
    drawdown_penalty = clamp(abs(min(drawdown_63d, 0)) / 0.30, 0, 1)
    volatility_penalty = clamp((volatility_21d - 0.35) / 0.45, 0, 1)
    score = (
        0.50
        + relative_20d * 0.20
        + relative_63d * 0.16
        + absolute_20d * 0.08
        + absolute_63d * 0.08
        + volume * 0.10
        - drawdown_penalty * 0.07
        - volatility_penalty * 0.06
    )
    return round(clamp(score, 0, 1), 6)


def compute_market_confirmation(
    symbol: str,
    bars: list[PriceBar],
    benchmark_bars: list[PriceBar],
    *,
    data_source: str,
    requested_as_of: dt.date | None = None,
    warning: str = "",
) -> MarketConfirmationRow | None:
    bars = sorted((bar for bar in bars if bar.close > 0), key=lambda bar: bar.date)
    benchmark_bars = sorted((bar for bar in benchmark_bars if bar.close > 0), key=lambda bar: bar.date)
    if len(bars) < 22:
        return None
    return_5d = pct_return(bars, 5)
    return_20d = pct_return(bars, 20)
    return_63d = pct_return(bars, 63)
    benchmark_20d = pct_return(benchmark_bars, 20) if len(benchmark_bars) >= 22 else 0.0
    benchmark_63d = pct_return(benchmark_bars, 63) if len(benchmark_bars) >= 65 else 0.0
    volume_signal = volume_zscore(bars)
    drawdown_63d = drawdown(bars, 63)
    volatility_21d = annualized_volatility(bars, 21)
    relative_return_20d = return_20d - benchmark_20d
    relative_return_63d = return_63d - benchmark_63d
    market_score = compute_market_score(
        return_20d=return_20d,
        return_63d=return_63d,
        relative_return_20d=relative_return_20d,
        relative_return_63d=relative_return_63d,
        volume_zscore_value=volume_signal,
        drawdown_63d=drawdown_63d,
        volatility_21d=volatility_21d,
    )
    price_age_days = max(((requested_as_of or bars[-1].date) - bars[-1].date).days, 0)
    confirmation_quality = "price_observed" if price_age_days <= 7 else "stale_price"
    return MarketConfirmationRow(
        symbol=symbol.upper(),
        as_of=bars[-1].date,
        return_5d=round(return_5d, 6),
        return_20d=round(return_20d, 6),
        return_63d=round(return_63d, 6),
        relative_return_20d=round(relative_return_20d, 6),
        relative_return_63d=round(relative_return_63d, 6),
        volume_zscore=round(volume_signal, 6),
        drawdown_63d=round(drawdown_63d, 6),
        volatility_21d=round(volatility_21d, 6),
        market_score=market_score,
        data_source=data_source,
        price_observation_count=len(bars),
        price_age_days=price_age_days,
        confirmation_quality=confirmation_quality,
        warnings=warning,
    )


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").upper()


def normalize_proxy_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return text


def parse_proxy_lines(text: str) -> list[str]:
    proxies: list[str] = []
    seen: set[str] = set()
    for raw_line in text.replace(",", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Common public proxy lists may add comments or extra columns after whitespace.
        candidate = normalize_proxy_url(line.split()[0])
        if candidate and candidate not in seen:
            seen.add(candidate)
            proxies.append(candidate)
    return proxies


def fetch_text_url(url: str, *, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; QuantAdvisorResearch/0.1; +https://github.com/QuantStrategyLab)",
            "Accept": "text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-supplied public proxy-list URL.
        return response.read().decode("utf-8", errors="replace")


def load_proxy_urls(
    *,
    proxy_list_path: str | Path | None = None,
    proxy_urls_text: str = "",
    proxy_pool_url: str = "",
    timeout: int = 20,
) -> list[str]:
    proxies: list[str] = []
    if proxy_urls_text.strip():
        proxies.extend(parse_proxy_lines(proxy_urls_text))
    if proxy_list_path:
        path = Path(proxy_list_path)
        if path.exists():
            proxies.extend(parse_proxy_lines(path.read_text(encoding="utf-8")))
    if proxy_pool_url.strip():
        try:
            proxies.extend(parse_proxy_lines(fetch_text_url(proxy_pool_url.strip(), timeout=timeout)))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"market_data_notice: proxy_pool_unavailable reason={type(exc).__name__}")
    seen: set[str] = set()
    result: list[str] = []
    for proxy in proxies:
        if proxy not in seen:
            seen.add(proxy)
            result.append(proxy)
    return result


def open_request(request: Request, *, timeout: int, proxy_url: str | None = None) -> bytes:
    if proxy_url:
        opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - public market-data endpoint only.
            return response.read()
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public market-data endpoint only.
        return response.read()


def fetch_yahoo_bars(
    symbol: str,
    *,
    as_of: dt.date,
    lookback_days: int = 460,
    timeout: int = 20,
    proxy_url: str | None = None,
) -> list[PriceBar]:
    end_date = as_of + dt.timedelta(days=2)
    start_date = as_of - dt.timedelta(days=lookback_days)
    params = urlencode(
        {
            "period1": int(dt.datetime.combine(start_date, dt.time(), tzinfo=dt.UTC).timestamp()),
            "period2": int(dt.datetime.combine(end_date, dt.time(), tzinfo=dt.UTC).timestamp()),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol(symbol)}?{params}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; QuantAdvisorResearch/0.1; +https://github.com/QuantStrategyLab)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    payload = json.loads(open_request(request, timeout=timeout, proxy_url=proxy_url).decode("utf-8"))
    result = payload.get("chart", {}).get("result", [])
    if not result:
        return []
    data = result[0]
    timestamps = data.get("timestamp") or []
    quote = (data.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    adjclose_blocks = data.get("indicators", {}).get("adjclose") or []
    adjcloses = adjclose_blocks[0].get("adjclose") if adjclose_blocks else None
    bars: list[PriceBar] = []
    for index, timestamp in enumerate(timestamps):
        close = None
        if isinstance(adjcloses, list) and index < len(adjcloses):
            close = adjcloses[index]
        if close is None and index < len(closes):
            close = closes[index]
        if close is None:
            continue
        bar_date = dt.datetime.fromtimestamp(int(timestamp), tz=dt.UTC).date()
        if bar_date > as_of:
            continue
        volume = volumes[index] if index < len(volumes) and volumes[index] is not None else 0
        bars.append(PriceBar(date=bar_date, close=float(close), volume=float(volume)))
    return bars


def fetch_yahoo_bars_with_fallback(
    symbol: str,
    *,
    as_of: dt.date,
    proxy_urls: list[str],
) -> tuple[list[PriceBar], str]:
    attempts = [None, *proxy_urls]
    last_error: Exception | None = None
    for proxy_index, proxy_url in enumerate(attempts):
        try:
            bars = fetch_yahoo_bars(symbol, as_of=as_of, proxy_url=proxy_url)
            if bars:
                return bars, "yahoo_chart_proxy" if proxy_url else "yahoo_chart"
            last_error = ValueError("empty_price_bars")
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if proxy_url:
                print(
                    "market_data_notice: proxy_fetch_unavailable "
                    f"symbol={symbol} proxy_index={proxy_index} reason={type(exc).__name__}"
                )
    if last_error:
        raise last_error
    raise ValueError("price_fetch_unavailable")


def load_theme_momentum(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def fallback_rows_from_theme_momentum(
    theme_momentum: dict[str, Any] | None,
    *,
    symbols: set[str],
    as_of: dt.date,
) -> dict[str, MarketConfirmationRow]:
    if not theme_momentum:
        return {}
    benchmark_return_63d = 0.0
    symbol_payloads: dict[str, dict[str, Any]] = {}
    for theme in theme_momentum.get("theme_ranks", []):
        if not isinstance(theme, dict):
            continue
        for item in theme.get("top_symbols", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).upper()
            current = symbol_payloads.get(symbol)
            if current is None or as_float(item.get("momentum_score")) > as_float(current.get("momentum_score")):
                symbol_payloads[symbol] = item
            if symbol == "SPY":
                benchmark_return_63d = as_float(item.get("return_3m"))
    rows: dict[str, MarketConfirmationRow] = {}
    fallback_as_of = as_of
    try:
        fallback_as_of = dt.date.fromisoformat(str(theme_momentum.get("as_of", as_of.isoformat())))
    except ValueError:
        fallback_as_of = as_of
    for symbol in sorted(symbols):
        item = symbol_payloads.get(symbol)
        if not item:
            continue
        return_63d = as_float(item.get("return_3m"))
        market_score = round(clamp(as_float(item.get("momentum_score")) / 1.5, 0, 1), 6)
        rows[symbol] = MarketConfirmationRow(
            symbol=symbol,
            as_of=fallback_as_of,
            return_5d=0.0,
            return_20d=0.0,
            return_63d=round(return_63d, 6),
            relative_return_20d=0.0,
            relative_return_63d=round(return_63d - benchmark_return_63d, 6),
            volume_zscore=0.0,
            drawdown_63d=0.0,
            volatility_21d=0.0,
            market_score=market_score,
            data_source="theme_momentum_fallback",
            price_observation_count=0,
            price_age_days=max((as_of - fallback_as_of).days, 0),
            confirmation_quality="fallback_only",
            warnings="price_api_unavailable_or_not_requested",
        )
    return rows


def collect_symbols(
    *,
    political_watchlist_path: str | Path | None = None,
    ai_signal_path: str | Path | None = None,
    theme_momentum: dict[str, Any] | None = None,
    max_symbols: int = 80,
) -> list[str]:
    symbols: set[str] = set()
    if political_watchlist_path and Path(political_watchlist_path).exists():
        for row in read_csv_rows(political_watchlist_path):
            symbol = str(row.get("symbol", "")).upper().strip()
            if symbol:
                symbols.add(symbol)
    if ai_signal_path and Path(ai_signal_path).exists():
        with Path(ai_signal_path).open(encoding="utf-8") as handle:
            ai_signal = json.load(handle)
        for symbol in ai_signal.get("universe", []):
            if isinstance(symbol, str) and symbol.strip():
                symbols.add(symbol.upper())
        for key in ("candidate_bias", "research_bias", "symbol_bias", "symbol_theme_exposure"):
            value = ai_signal.get(key)
            if isinstance(value, dict):
                symbols.update(str(symbol).upper() for symbol in value if str(symbol).strip())
    if theme_momentum:
        for theme in theme_momentum.get("theme_ranks", []):
            if not isinstance(theme, dict):
                continue
            for item in theme.get("top_symbols", []):
                if isinstance(item, dict) and item.get("symbol"):
                    symbols.add(str(item["symbol"]).upper())
    symbols = {symbol for symbol in symbols if symbol and symbol not in EXCLUDED_SYMBOLS}
    return sorted(symbols)[:max_symbols]


def build_market_confirmation_rows(
    *,
    symbols: list[str],
    as_of: dt.date,
    benchmark: str = "SPY",
    theme_momentum: dict[str, Any] | None = None,
    use_network: bool = True,
    request_pause_seconds: float = 0.2,
    proxy_urls: list[str] | None = None,
) -> list[MarketConfirmationRow]:
    symbol_set = set(symbols)
    fallback_rows = fallback_rows_from_theme_momentum(theme_momentum, symbols=symbol_set, as_of=as_of)
    rows: dict[str, MarketConfirmationRow] = {}
    proxy_urls = proxy_urls or []
    if use_network:
        benchmark_bars: list[PriceBar] = []
        try:
            benchmark_bars, _ = fetch_yahoo_bars_with_fallback(benchmark, as_of=as_of, proxy_urls=proxy_urls)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
            benchmark_bars = []
            print(f"market_data_notice: benchmark_fetch_unavailable benchmark={benchmark} reason={type(exc).__name__}")
        for index, symbol in enumerate(symbols):
            if index and request_pause_seconds > 0:
                time.sleep(request_pause_seconds)
            try:
                bars, data_source = fetch_yahoo_bars_with_fallback(symbol, as_of=as_of, proxy_urls=proxy_urls)
                row = compute_market_confirmation(
                    symbol,
                    bars,
                    benchmark_bars,
                    data_source=data_source,
                    requested_as_of=as_of,
                    warning="" if len(benchmark_bars) >= 22 else "benchmark_unavailable",
                )
                if row:
                    rows[symbol] = row
                    continue
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
                print(f"market_data_notice: symbol_fetch_unavailable symbol={symbol} reason={type(exc).__name__}")
            if symbol in fallback_rows:
                rows[symbol] = fallback_rows[symbol]
    else:
        rows.update(fallback_rows)
    for symbol, row in fallback_rows.items():
        rows.setdefault(symbol, row)
    return [rows[symbol] for symbol in sorted(rows)]


def write_market_confirmation_csv(path: str | Path, rows: list[MarketConfirmationRow]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DEFAULT_OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build point-in-time market confirmation CSV for advisor scoring.")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--political-watchlist", help="Political watchlist CSV used to collect symbols.")
    parser.add_argument("--ai-signal", help="Research signal context JSON used to collect symbols.")
    parser.add_argument("--theme-momentum", help="Theme momentum snapshot JSON used to collect symbols and fallback rows.")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark symbol for relative returns. Defaults to SPY.")
    parser.add_argument("--max-symbols", type=int, default=80)
    parser.add_argument("--request-pause-seconds", type=float, default=0.2)
    parser.add_argument("--proxy-list", help="Optional local text file with one HTTP/HTTPS proxy per line.")
    parser.add_argument("--proxy-urls", default="", help="Optional comma/newline-separated HTTP/HTTPS proxy URLs.")
    parser.add_argument("--proxy-pool-url", default="", help="Optional public text URL returning one proxy per line.")
    parser.add_argument("--no-network", action="store_true", help="Skip price API calls and use theme momentum fallback only.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    as_of = dt.date.fromisoformat(args.as_of)
    theme_momentum = load_theme_momentum(args.theme_momentum)
    symbols = collect_symbols(
        political_watchlist_path=args.political_watchlist,
        ai_signal_path=args.ai_signal,
        theme_momentum=theme_momentum,
        max_symbols=args.max_symbols,
    )
    proxy_urls = load_proxy_urls(
        proxy_list_path=args.proxy_list,
        proxy_urls_text=args.proxy_urls,
        proxy_pool_url=args.proxy_pool_url,
    )
    if proxy_urls:
        print(f"market_data_notice: proxy_pool_loaded count={len(proxy_urls)}")
    rows = build_market_confirmation_rows(
        symbols=symbols,
        as_of=as_of,
        benchmark=args.benchmark,
        theme_momentum=theme_momentum,
        use_network=not args.no_network,
        request_pause_seconds=args.request_pause_seconds,
        proxy_urls=proxy_urls,
    )
    write_market_confirmation_csv(args.output, rows)
    print(f"market_confirmation_rows={len(rows)} symbols_requested={len(symbols)} output={args.output}")


if __name__ == "__main__":
    main()

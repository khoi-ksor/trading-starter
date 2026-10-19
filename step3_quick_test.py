"""Step 3: quick backtest of the signals with vectorbt, compared with simply buying and holding.

    python step3_quick_test.py          # test the AI signals from step 2
    python step3_quick_test.py --demo   # test the free demo signals instead

Fast and rough: good for a first look before the realistic test in step 4.
"""

from __future__ import annotations

import argparse

import pandas as pd
import vectorbt as vbt

import common
import config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="use the demo signals")
    args = parser.parse_args()

    source = "demo" if args.demo else "ai"
    with common.Progress("step3", f"Quick test ({source} signals)") as progress:
        signals = common.load_signals(common.DEMO_SIGNALS if args.demo else common.AI_SIGNALS)
        symbols = list(signals["symbol"].unique())
        progress.update(total=len(symbols), source=source)
        rows = []
        for symbol in symbols:
            progress.update(current=symbol)
            row = quick_test(symbol, signals)
            if row:
                rows.append(row)
                progress.log(f"{symbol}: {row['return %']:+.2f}% (buy & hold {row['buy & hold %']:+.2f}%)")
            progress.advance()

        report = pd.DataFrame(rows)
        common.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = common.REPORTS_DIR / f"quick_test_{source}.csv"
        report.to_csv(out, index=False)
        with pd.option_context("display.width", 200, "display.max_columns", None):
            print(report.to_string(index=False))
        print(f"\nSaved to {out}")
        progress.finish(f"{len(rows)} symbols tested")


def quick_test(symbol: str, signals: pd.DataFrame) -> dict | None:
    targets = common.signal_targets(signals, symbol)
    close = common.load_prices(symbol)["close"]
    close = close[close.index > targets[0][0]]  # start the day after the first signal
    if close.empty:
        print(f"{symbol}: no prices after the first signal yet, skipped")
        return None
    held = common.target_positions(targets, close.index)
    before = held.shift(1, fill_value=0)
    strategy = vbt.Portfolio.from_signals(
        close,
        entries=(held == 1) & (before == 0),
        exits=(held == 0) & (before == 1),
        init_cash=config.POSITION_SIZE_USD,
        fees=config.FEE_RATE,
        freq="1D",
    )
    hold = vbt.Portfolio.from_holding(close, init_cash=config.POSITION_SIZE_USD, fees=config.FEE_RATE, freq="1D")
    return {
        "symbol": symbol,
        "from": close.index[0].date(),
        "to": close.index[-1].date(),
        "signals": len(targets),
        "trades": int(strategy.trades.count()),
        "days invested %": round(100 * held.mean(), 1),
        "return %": round(100 * strategy.total_return(), 2),
        "buy & hold %": round(100 * hold.total_return(), 2),
        "max drawdown %": round(100 * strategy.max_drawdown(), 2),
    }


if __name__ == "__main__":
    main()

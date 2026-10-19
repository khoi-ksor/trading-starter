"""Step 4: realistic backtest of the signals with NautilusTrader.

    python step4_nautilus_backtest.py          # test the AI signals from step 2
    python step4_nautilus_backtest.py --demo   # test the free demo signals instead

Each symbol runs through Nautilus' event-driven engine: real orders, fills, fees and an
account balance. When a signal says buy, it buys POSITION_SIZE_USD worth; when it says
sell, it closes the position. Hold keeps whatever is held.
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from decimal import Decimal

import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, StrategyConfig
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    Bar,
    BarType,
    Currency,
    CurrencyPair,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.trading import Strategy

import common
import config

VENUE = Venue("SIM")
USD = Currency.from_str("USD")
STARTING_BALANCE = config.POSITION_SIZE_USD * 2  # room for the position plus fees
END_OF_DAY_NS = (23 * 3600 + 59 * 60) * 1_000_000_000  # daily bars are stamped at 23:59 UTC


class FollowSignalsConfig(StrategyConfig):
    def __init__(self, *, instrument_id: InstrumentId, bar_type: BarType, size_usd: float,
                 size_precision: int, targets: list[tuple[date, int | None]], **_kwargs: object) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.size_usd = size_usd
        self.size_precision = size_precision
        self.targets = targets


class FollowSignals(Strategy):
    """Holds the symbol while the latest signal says buy; a signal dated D acts on the next day's bar."""

    def __init__(self, config: FollowSignalsConfig) -> None:
        super().__init__(config)
        self.next_target = 0
        self.want_long = False

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        day = pd.Timestamp(bar.ts_event, unit="ns").date()
        targets = self.config.targets
        while self.next_target < len(targets) and targets[self.next_target][0] < day:
            if targets[self.next_target][1] is not None:
                self.want_long = bool(targets[self.next_target][1])
            self.next_target += 1

        instrument_id = self.config.instrument_id
        if self.want_long and self.portfolio.is_net_flat(instrument_id):
            units = self.config.size_usd / float(bar.close)
            step = 10 ** self.config.size_precision
            qty = math.floor(units * step) / step
            if qty > 0:
                order = self.order_factory.market(
                    instrument_id, OrderSide.BUY, Quantity(qty, self.config.size_precision)
                )
                self.submit_order(order)
        elif not self.want_long and self.portfolio.is_net_long(instrument_id):
            self.close_all_positions(instrument_id)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)


def price_precision(prices: pd.DataFrame) -> int:
    low = prices["close"].min()
    return 2 if low >= 10 else 4 if low >= 0.1 else 6


def make_instrument(symbol: str, precision: int) -> tuple[Equity | CurrencyPair, int, str]:
    """The Nautilus instrument, its size precision, and the symbol name used inside Nautilus."""
    increment = Price(10 ** -precision, precision)
    if common.is_crypto(symbol):
        base = symbol.split("-")[0]
        name = f"{base}USD"  # Nautilus bar names can't contain "-"
        instrument = CurrencyPair(
            instrument_id=InstrumentId(Symbol(name), VENUE),
            raw_symbol=Symbol(name),
            base_currency=Currency.from_str(base),
            quote_currency=USD,
            price_precision=precision,
            size_precision=6,
            price_increment=increment,
            size_increment=Quantity(1e-06, 6),
            ts_event=0,
            ts_init=0,
            min_quantity=Quantity(1e-06, 6),
            margin_init=Decimal(1),
            margin_maint=Decimal(1),
        )
        return instrument, 6, name
    instrument = Equity(
        instrument_id=InstrumentId(Symbol(symbol), VENUE),
        raw_symbol=Symbol(symbol),
        currency=USD,
        price_precision=precision,
        price_increment=increment,
        ts_event=0,
        ts_init=0,
        lot_size=Quantity.from_int(1),
    )
    return instrument, 0, symbol


def make_bars(prices: pd.DataFrame, bar_type: BarType, precision: int, size_precision: int,
              crypto: bool) -> list[Bar]:
    bars = []
    for day, row in prices.iterrows():
        ts = pd.Timestamp(day).value + END_OF_DAY_NS
        # Yahoo reports crypto volume in dollars; Nautilus wants it in coins.
        volume = row["volume"] / row["close"] if crypto else row["volume"]
        bars.append(Bar(
            bar_type=bar_type,
            open=Price(row["open"], precision),
            high=Price(row["high"], precision),
            low=Price(row["low"], precision),
            close=Price(row["close"], precision),
            volume=Quantity(min(volume, 1e9), size_precision),
            ts_event=ts,
            ts_init=ts,
        ))
    return bars


def money(value: object) -> float:
    """Nautilus reports amounts as text like '10123.45 USD'."""
    return float(str(value).split()[0])


def backtest(symbol: str, signals: pd.DataFrame) -> dict | None:
    targets = [(d.date(), t) for d, t in common.signal_targets(signals, symbol)]
    prices = common.load_prices(symbol)
    prices = prices[prices.index.date > targets[0][0]]  # start the day after the first signal
    if prices.empty:
        print(f"{symbol}: no prices after the first signal yet, skipped")
        return None

    precision = price_precision(prices)
    instrument, size_precision, name = make_instrument(symbol, precision)
    bar_type = BarType.from_str(f"{name}.{VENUE}-1-DAY-LAST-EXTERNAL")

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId.from_str("STARTER-001"),
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
    ))
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(STARTING_BALANCE, USD)],
        default_leverage=Decimal(1),
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(str(config.FEE_RATE)),
                                     taker_rate=Decimal(str(config.FEE_RATE))),
    )
    engine.add_instrument(instrument)
    engine.add_data(make_bars(prices, bar_type, precision, size_precision, common.is_crypto(symbol)))
    engine.add_strategy(FollowSignals(FollowSignalsConfig(
        instrument_id=instrument.id,
        bar_type=bar_type,
        size_usd=config.POSITION_SIZE_USD,
        size_precision=size_precision,
        targets=targets,
    )))
    engine.run()

    account = engine.generate_account_report(VENUE)
    fills = engine.generate_order_fills_report()
    final_balance = money(account["total"].iloc[-1])
    engine.dispose()

    pnl = final_balance - STARTING_BALANCE
    return {
        "symbol": symbol,
        "from": prices.index[0].date(),
        "to": prices.index[-1].date(),
        "orders filled": len(fills),
        "profit $ (after fees)": round(pnl, 2),
        "return %": round(100 * pnl / config.POSITION_SIZE_USD, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="use the demo signals")
    args = parser.parse_args()

    source = "demo" if args.demo else "ai"
    with common.Progress("step4", f"Realistic test ({source} signals)") as progress:
        signals = common.load_signals(common.DEMO_SIGNALS if args.demo else common.AI_SIGNALS)
        symbols = list(signals["symbol"].unique())
        progress.update(total=len(symbols), source=source)
        rows = []
        for symbol in symbols:
            progress.update(current=symbol)
            row = backtest(symbol, signals)
            if row:
                rows.append(row)
                progress.log(f"{symbol}: {row['return %']:+.2f}%, "
                             f"{row['orders filled']} orders filled, ${row['profit $ (after fees)']:,.2f}")
            progress.advance()

        report = pd.DataFrame(rows)
        common.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = common.REPORTS_DIR / f"nautilus_backtest_{source}.csv"
        report.to_csv(out, index=False)
        with pd.option_context("display.width", 200, "display.max_columns", None):
            print(report.to_string(index=False))
        print(f"\nReturn % is profit divided by the {config.POSITION_SIZE_USD:,} USD position size.")
        print(f"Saved to {out}")
        progress.finish(f"{len(rows)} symbols tested")


if __name__ == "__main__":
    main()

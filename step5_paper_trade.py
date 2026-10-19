"""Step 5: act on the latest signals in your Alpaca PAPER account (fake money only).

    python step5_paper_trade.py            # show what it would do; sends nothing
    python step5_paper_trade.py --submit   # send the orders to the paper account
    python step5_paper_trade.py --demo     # use the demo signals (handy for testing your keys)

Usual daily routine: python step2_ai_signals.py --today, then this script.
Buy / Overweight -> buy PAPER_POSITION_SIZE_USD worth if not already held.
Sell / Underweight -> close the position. Hold -> do nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

import common
import config


def alpaca_symbols(symbol: str) -> tuple[str, str]:
    """(symbol for orders, symbol Alpaca uses for positions). Crypto: BTC-USD -> BTC/USD, BTCUSD."""
    if common.is_crypto(symbol):
        base = symbol.split("-")[0]
        return f"{base}/USD", f"{base}USD"
    return symbol, symbol


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--submit", action="store_true", help="actually send the orders (paper account)")
    parser.add_argument("--demo", action="store_true", help="use the demo signals")
    args = parser.parse_args()

    title = "Paper trading" + ("" if args.submit else " (dry run)")
    with common.Progress("step5", title) as progress:
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            sys.exit("ALPACA_API_KEY / ALPACA_SECRET_KEY are empty. Add your paper keys to starter/.env first.")

        # paper=True is fixed on purpose: this script never touches a real-money account.
        client = TradingClient(key, secret, paper=True)
        account = client.get_account()
        equity, cash = float(account.equity), float(account.cash)
        print(f"Alpaca PAPER account: equity ${equity:,.2f}, cash ${cash:,.2f}")
        progress.update(equity=equity, cash=cash)
        progress.log(f"Paper account: equity ${equity:,.2f}, cash ${cash:,.2f}")
        held = {p.symbol: p for p in client.get_all_positions()}

        signals = common.load_signals(common.DEMO_SIGNALS if args.demo else common.AI_SIGNALS)
        latest = signals.sort_values("date").groupby("symbol").tail(1)
        progress.update(total=len(latest))

        plan = []
        for row in latest.itertuples():
            age = (date.today() - row.date.date()).days
            order_symbol, position_symbol = alpaca_symbols(row.symbol)
            target = common.RATING_TO_TARGET.get(row.rating)
            status = f"{row.symbol:8} {row.rating:11} from {row.date.date()}"
            if age > config.PAPER_MAX_SIGNAL_AGE_DAYS:
                decision = f"skipped, signal is {age} days old"
            elif target == 1 and position_symbol not in held:
                decision = f"BUY ${config.PAPER_POSITION_SIZE_USD:,} worth"
                plan.append(("buy", order_symbol, position_symbol, row.symbol))
            elif target == 0 and position_symbol in held:
                decision = "SELL the whole position"
                plan.append(("sell", order_symbol, position_symbol, row.symbol))
            else:
                decision = f"nothing to do ({'held' if position_symbol in held else 'not held'})"
            print(f"{status}: {decision}")
            progress.log(f"{row.symbol} ({row.rating}): {decision}")
            progress.advance(current=row.symbol)

        if not plan:
            print("\nNo orders needed.")
            progress.finish("no orders needed")
            return
        if not args.submit:
            print("\nDry run: nothing sent. Add --submit to place these orders in the paper account.")
            progress.finish(f"dry run: {len(plan)} orders planned, none sent")
            return

        for action, order_symbol, position_symbol, symbol in plan:
            if action == "buy":
                # Crypto trades around the clock (GTC); stock orders by dollar amount must be DAY orders.
                tif = TimeInForce.GTC if common.is_crypto(symbol) else TimeInForce.DAY
                order = client.submit_order(MarketOrderRequest(
                    symbol=order_symbol, notional=config.PAPER_POSITION_SIZE_USD,
                    side=OrderSide.BUY, time_in_force=tif,
                ))
            else:
                order = client.close_position(position_symbol)
            print(f"Sent {action} {order_symbol}: order {order.id}, status {order.status}")
            progress.log(f"Sent {action} {order_symbol} to the paper account ({order.status})")
        progress.finish(f"{len(plan)} paper orders sent")


if __name__ == "__main__":
    main()

"""Settings for the starter pipeline. Edit these, then run the steps in order (see README.md)."""

from datetime import date

# What to analyse. Stocks use their normal ticker; crypto uses Yahoo-style "BASE-USD".
STOCKS = ["AAPL", "NVDA"]
CRYPTO = ["BTC-USD", "ETH-USD"]

# Daily price history to download (step 1). It starts before the signal window so
# the demo signals in step 2 have enough history to warm up.
PRICE_START = "2026-01-01"
PRICE_END = date.today().isoformat()

# AI signal window (step 2). Keep it after the AI models' training cutoff: on older
# dates the models may already "know" what happened next, which makes a backtest
# look better than it really is.
SIGNAL_START = "2026-07-01"
SIGNAL_END = date.today().isoformat()
SIGNAL_EVERY_N_DAYS = 7  # one analysis per symbol per week

# Backtest money settings (steps 3 and 4).
POSITION_SIZE_USD = 10_000  # how much goes into a symbol when the AI says buy
FEE_RATE = 0.001  # 0.1% per trade, a rough stand-in for fees and slippage

# Paper trading (step 5). Orders only ever go to Alpaca's paper (fake money) account.
PAPER_POSITION_SIZE_USD = 250  # 4 symbols x $250 fits the $1,000 paper account
# Skip a signal older than this many days instead of trading on stale advice.
PAPER_MAX_SIGNAL_AGE_DAYS = 3

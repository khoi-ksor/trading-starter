# Starter trading pipeline

AI ideas → data → quick test → realistic test → paper trading, for stocks and crypto.

| Step | Script | Tool | What it does |
|---|---|---|---|
| 1 | `step1_get_data.py` | OpenBB | Downloads daily prices (free Yahoo Finance data) |
| 2 | `step2_ai_signals.py` | TradingAgents + Claude | A team of AI agents rates each symbol: Buy, Overweight, Hold, Underweight or Sell |
| 3 | `step3_quick_test.py` | vectorbt | Fast, rough backtest of those ratings vs. just buying and holding |
| 4 | `step4_nautilus_backtest.py` | NautilusTrader | Realistic backtest with real orders, fills and fees |
| 5 | `step5_paper_trade.py` | Alpaca | Places the latest ratings as orders in a **paper (fake money)** account |

How ratings become trades (same in steps 3, 4 and 5):

- **Buy / Overweight**: hold the symbol
- **Underweight / Sell**: hold nothing (no short selling)
- **Hold**: keep whatever is held now
- A rating made for day D is traded at the close of the next trading day.

## Setup (once)

1. Open `.env` in this folder and fill in:
   - `ANTHROPIC_API_KEY`, from https://console.anthropic.com
   - `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`, from https://app.alpaca.markets. Switch to your **Paper** account first, then create the keys.
2. Choose your symbols and dates in `config.py`.

The Python environment is already set up in `.venv`. Run every command from this folder:

```powershell
cd "d:\Trading V3\starter"
```

## Live dashboard

To watch what's happening, open a second terminal in this folder and run:

```powershell
.venv\Scripts\python dashboard.py
```

It opens http://127.0.0.1:8765 in your browser and updates every 2 seconds. It shows:

- each step's status and progress bar
- while the AI works: which agents are busy, AI calls, tokens and a rough cost
- a live activity feed
- price charts with every Buy/Hold/Sell signal and the periods you'd have been invested
- the backtest results

Leave it running while you run the steps in your first terminal. It only reads files and is visible on this computer only. Press Ctrl+C to stop it.

## 1. Try it for free first (demo signals, no AI)

```powershell
.venv\Scripts\python step1_get_data.py
.venv\Scripts\python step2_ai_signals.py --demo
.venv\Scripts\python step3_quick_test.py --demo
.venv\Scripts\python step4_nautilus_backtest.py --demo
```

The demo uses a simple moving-average rule in place of the AI. It only checks that the pipeline works.

## 2. Real AI signals

Every analysis costs real Claude API money, so start small:

```powershell
.venv\Scripts\python step2_ai_signals.py --dry-run    # list what would run; spends nothing
.venv\Scripts\python step2_ai_signals.py --limit 1    # one analysis; then check usage in the Anthropic console
.venv\Scripts\python step2_ai_signals.py              # the full window; safe to stop and re-run, it resumes
.venv\Scripts\python step3_quick_test.py
.venv\Scripts\python step4_nautilus_backtest.py
```

## 3. Daily paper trading (automatic, in the cloud)

GitHub runs `run_daily.py` every day at 21:15 UTC (5:15 PM New York time in summer, 4:15 PM in winter), so your PC can be off. It's the **Daily trading bot** workflow in https://github.com/khoi-ksor/trading-starter:

1. Get fresh prices.
2. Get today's AI ratings. On weekends only crypto is rated, since stock markets are closed.
3. Place the matching paper trades.

Each run saves its signals, the AI's memory and its log back to the repo.

- **See the results on your PC:** run `git pull` in this folder, then open the dashboard.
- **Self-learning:** daily runs share one memory, `signals/tradingagents/live_memory.md`. TradingAgents scores each call after about 5 trading days and feeds the lessons into later analyses.
- **Pause it:** GitHub repo → Actions → Daily trading bot → "Disable workflow".
- **Test it without spending:** Actions → Daily trading bot → "Run workflow" with "Dry run" ticked.
- **Keys:** stored as encrypted repo secrets (Settings → Secrets and variables → Actions). If you change a key in `.env`, update it there too.
- **Windows task:** the old "Trading starter daily run" task is disabled so the bot doesn't trade twice. Re-enable it only if you stop the cloud workflow.

To do the same by hand:

```powershell
.venv\Scripts\python run_daily.py --dry-run           # same steps, but no AI calls and no orders
.venv\Scripts\python step2_ai_signals.py --today      # today's ratings
.venv\Scripts\python step5_paper_trade.py             # shows the orders; sends nothing
.venv\Scripts\python step5_paper_trade.py --submit    # sends them to the paper account
```

## Where results go

- `data/prices/`: downloaded prices
- `signals/ai_signals.csv`: every AI rating
- `signals/tradingagents/decisions/`: the AI's full reasoning for each rating
- `reports/`: backtest results as CSV files
- `status/`: live progress for the dashboard (safe to delete; it's rebuilt on the next run)

## Things to know

- **Cost.** One analysis is many Claude calls. Models are set in `.env`:
  - "deep" `claude-opus-5-5` makes the final calls.
  - "quick" `claude-haiku-5-5` does the bulk of the work cheaply.
  - For deeper analysis at about 20 times the price per token, set the quick model to `claude-sonnet-5-5`.
- **Backtests of AI signals can look too good.** On dates before the models' training cutoff, the AI may already "know" what happened next. Keep `SIGNAL_START` in `config.py` after that cutoff. Yahoo's news for older dates can also be incomplete.
- **Paper only.** Step 5 is fixed to Alpaca's paper account. Nothing here trades real money.
- **Not financial advice.** TradingAgents is a research project, and so is this starter.

## Versions

- **TradingAgents** is installed straight from `..\TradingAgents`. Running `git -C ..\TradingAgents pull` updates it.
- **NautilusTrader** is `2.0.0rc7`, the newest v2 release on PyPI. Its examples and docs are at https://github.com/nautechsystems/nautilus_trader.
- **Rebuilding the environment:** `requirements.txt` lists every package, if you ever need to set up `.venv` again.

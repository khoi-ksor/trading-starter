"""Step 2: ask TradingAgents (Claude) for a Buy / Hold / Sell rating per symbol per date.

Every analysis runs a team of AI agents and costs real API money, so start small:

    python step2_ai_signals.py --dry-run   # list what would run; spends nothing
    python step2_ai_signals.py --limit 1   # one analysis, then check the cost in your Anthropic console
    python step2_ai_signals.py             # the whole window in config.py; resumes where it stopped
    python step2_ai_signals.py --today     # today's ratings, for paper trading (step 5)
    python step2_ai_signals.py --demo      # free fake signals from a moving-average rule, to test steps 3-5
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from datetime import date, datetime, timedelta

import pandas as pd
from langchain_core.callbacks import BaseCallbackHandler

import common
import config

TA_DIR = common.SIGNALS_DIR / "tradingagents"

# List prices in USD per million tokens (input, output), only for the dashboard's rough
# cost estimate. It ignores caching discounts, so real bills are usually a bit lower.
PRICES_PER_MTOK = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}


class AgentWatcher(BaseCallbackHandler):
    """Tells the dashboard which agents are working, what data they fetch, and the token use."""

    def __init__(self, progress: common.Progress) -> None:
        super().__init__()
        self.progress = progress
        self.lock = threading.Lock()
        self.calls: dict = {}  # run id -> (agent, model)
        self.llm_calls = self.tokens_in = self.tokens_out = 0
        self.cost = 0.0
        self.cost_complete = True
        self.start_analysis()

    def start_analysis(self) -> None:
        with self.lock:
            self.seen: list[str] = []
            self.active: dict[str, int] = {}  # agent -> calls in flight
        self._publish()

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs) -> None:
        metadata = metadata or {}
        agent = metadata.get("langgraph_node") or "Memory review"
        if agent in ("agent", "wrap_up"):
            # Analysts run as small sub-graphs whose inner step is just "agent"; the
            # outer step name ("Market Analyst:<id>|agent:<id>") says which analyst it is.
            namespace = metadata.get("langgraph_checkpoint_ns") or metadata.get("checkpoint_ns") or ""
            agent = namespace.split("|")[0].split(":")[0] or agent
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or "?"
        with self.lock:
            self.calls[run_id] = (agent, model)
            self.llm_calls += 1
            self.active[agent] = self.active.get(agent, 0) + 1
            first_time = agent not in self.seen
            if first_time:
                self.seen.append(agent)
        if first_time:
            self.progress.log(f"{agent} is working")
        self._publish()

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        tools = []
        with self.lock:
            agent, model = self.calls.pop(run_id, ("?", "?"))
            self._finish_call(agent)
            try:
                message = response.generations[0][0].message
                usage = message.usage_metadata or {}
                tools = [call["name"] for call in getattr(message, "tool_calls", None) or []]
            except (AttributeError, IndexError, TypeError):
                usage = {}
            tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            if model in PRICES_PER_MTOK:
                price_in, price_out = PRICES_PER_MTOK[model]
                self.cost += (tokens_in * price_in + tokens_out * price_out) / 1_000_000
            elif tokens_in or tokens_out:
                self.cost_complete = False
        if tools:
            self.progress.log(f"{agent} is fetching data: {', '.join(tools)}")
        self._publish()

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        with self.lock:
            agent, _ = self.calls.pop(run_id, ("?", "?"))
            self._finish_call(agent)
        self._publish()

    def _finish_call(self, agent: str) -> None:
        if self.active.get(agent, 0) <= 1:
            self.active.pop(agent, None)
        else:
            self.active[agent] -= 1

    def _publish(self) -> None:
        with self.lock:
            fields = {
                "agents_seen": list(self.seen),
                "agents_active": list(self.active),
                "llm_calls": self.llm_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "est_cost": round(self.cost, 4),
                "est_cost_complete": self.cost_complete,
            }
        self.progress.update(**fields)


def grid_dates(start: str, end: str, every: int) -> list[str]:
    """Dates from start to end (never past today), every N days."""
    day = datetime.strptime(start, "%Y-%m-%d").date()
    last = min(datetime.strptime(end, "%Y-%m-%d").date(), date.today())
    dates = []
    while day <= last:
        dates.append(day.isoformat())
        day += timedelta(days=every)
    return dates


def make_demo_signals(symbols: list[str], dates: list[str]) -> None:
    """Stand-in signals: Buy when the 20-day average is above the 50-day, else Sell."""
    rows = []
    with common.Progress("step2", "Demo signals (free, no AI)", total=len(symbols)) as progress:
        for symbol in symbols:
            progress.update(current=symbol)
            close = common.load_prices(symbol)["close"]
            for day in dates:
                history = close[close.index <= day]
                if len(history) < 50:
                    continue
                fast, slow = history.iloc[-20:].mean(), history.iloc[-50:].mean()
                rows.append({"date": day, "symbol": symbol, "rating": "Buy" if fast > slow else "Sell",
                             "source": "demo:sma20/50"})
            progress.advance()
        common.SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=common.SIGNAL_COLUMNS).to_csv(common.DEMO_SIGNALS, index=False)
        print(f"Wrote {len(rows)} demo signals to {common.DEMO_SIGNALS}")
        progress.finish(f"{len(rows)} demo signals written")


def run_ai(symbols: list[str], dates: list[str], limit: int | None, live: bool, dry_run: bool) -> None:
    done = set()
    if common.AI_SIGNALS.exists():
        existing = pd.read_csv(common.AI_SIGNALS)
        done = set(zip(existing["symbol"], existing["date"]))
    # Oldest date first, so an interrupted run leaves a clean history behind it.
    todo = [(s, d) for d in dates for s in symbols if (s, d) not in done]
    if limit:
        todo = todo[:limit]

    deep = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "?")
    quick = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "?")
    print(f"{len(todo)} analyses to run ({len(done)} already done). Models: deep={deep}, quick={quick}")
    for symbol, day in todo:
        print(f"  {day}  {symbol}")
    if dry_run or not todo:
        return

    with common.Progress("step2", "AI signals (TradingAgents + Claude)", total=len(todo)) as progress:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is empty. Add it to starter/.env first.")
        progress.update(models={"deep": deep, "quick": quick})

        from tradingagents.default_config import build_default_config
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        watcher = AgentWatcher(progress)
        finished = 0
        for n, (symbol, day) in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {symbol} on {day}: the agents are working (a few minutes)...")
            progress.update(current=f"{symbol} on {day}")
            watcher.start_analysis()
            cfg = build_default_config()
            cfg["results_dir"] = str(TA_DIR / "logs")
            # A past-date run starts with an empty memory, so it can't learn from outcomes
            # that came after its date. Today's runs share one memory and learn over time.
            memory = "live_memory.md" if live else f"history_memory/{symbol}_{day}.md"
            cfg["memory_log_path"] = str(TA_DIR / memory)
            try:
                graph = TradingAgentsGraph(config=cfg, callbacks=[watcher])
                state, rating = graph.propagate(
                    symbol, day, asset_type="crypto" if common.is_crypto(symbol) else "stock"
                )
            except Exception as exc:  # one failed analysis shouldn't stop the rest
                print(f"  failed: {exc}")
                progress.log(f"{symbol} on {day} failed: {exc}", level="error")
                progress.advance()
                continue
            common.append_signal(common.AI_SIGNALS, {"date": day, "symbol": symbol, "rating": rating,
                                                     "source": f"ai:{deep}/{quick}"})
            decision_file = TA_DIR / "decisions" / f"{symbol}_{day}.md"
            decision_file.parent.mkdir(parents=True, exist_ok=True)
            decision_file.write_text(state.get("final_trade_decision") or "", encoding="utf-8")
            print(f"  rating: {rating}  (full reasoning: {decision_file})")
            progress.log(f"{symbol} on {day}: rated {rating}")
            finished += 1
            progress.advance(last=f"{symbol} on {day}: {rating}")
        cost = f"${watcher.cost:.2f}" + ("" if watcher.cost_complete else "+")
        progress.finish(f"{finished} of {len(todo)} analyses done, about {cost} estimated")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=common.watchlist())
    parser.add_argument("--today", action="store_true", help="rate each symbol for today only")
    parser.add_argument("--limit", type=int, help="run at most this many analyses")
    parser.add_argument("--dry-run", action="store_true", help="list the analyses without running them")
    parser.add_argument("--demo", action="store_true", help="write free moving-average signals instead")
    args = parser.parse_args()

    if args.today:
        dates = [date.today().isoformat()]
    else:
        dates = grid_dates(config.SIGNAL_START, config.SIGNAL_END, config.SIGNAL_EVERY_N_DAYS)

    if args.demo:
        make_demo_signals(args.symbols, dates)
    else:
        run_ai(args.symbols, dates, args.limit, live=args.today, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

"""Shared helpers: paths, symbols, loading prices and signals, and turning ratings into positions."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import config

ROOT = Path(__file__).resolve().parent
PRICES_DIR = ROOT / "data" / "prices"
SIGNALS_DIR = ROOT / "signals"
REPORTS_DIR = ROOT / "reports"
STATUS_DIR = ROOT / "status"
EVENTS_FILE = STATUS_DIR / "events.jsonl"
AI_SIGNALS = SIGNALS_DIR / "ai_signals.csv"
DEMO_SIGNALS = SIGNALS_DIR / "demo_signals.csv"
SIGNAL_COLUMNS = ["date", "symbol", "rating", "source"]

# Load API keys before anything (TradingAgents included) reads the environment.
load_dotenv(ROOT / ".env")

# TradingAgents rates on a 5-step scale. 1 = hold the symbol, 0 = hold nothing,
# None = keep whatever is held now. REVIEW means the AI's answer had no readable rating.
RATING_TO_TARGET = {
    "Buy": 1,
    "Overweight": 1,
    "Hold": None,
    "Underweight": 0,
    "Sell": 0,
    "REVIEW": None,
}


def watchlist() -> list[str]:
    return config.STOCKS + config.CRYPTO


def is_crypto(symbol: str) -> bool:
    return symbol in config.CRYPTO


def price_path(symbol: str) -> Path:
    return PRICES_DIR / f"{symbol}.csv"


def load_prices(symbol: str) -> pd.DataFrame:
    """Daily OHLCV saved by step 1, indexed by date."""
    path = price_path(symbol)
    if not path.exists():
        raise FileNotFoundError(f"No prices for {symbol} at {path}. Run step1_get_data.py first.")
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return df.sort_index()


def load_signals(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No signals at {path}. Run step2_ai_signals.py first.")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def append_signal(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row], columns=SIGNAL_COLUMNS).to_csv(
        path, mode="a", header=not path.exists(), index=False
    )


def signal_targets(signals: pd.DataFrame, symbol: str) -> list[tuple[pd.Timestamp, int | None]]:
    """(signal date, target) pairs for one symbol, oldest first."""
    rows = signals[signals["symbol"] == symbol].sort_values("date")
    return [(r.date, RATING_TO_TARGET.get(r.rating)) for r in rows.itertuples()]


def target_positions(targets: list[tuple[pd.Timestamp, int | None]], dates: pd.DatetimeIndex) -> pd.Series:
    """The 0/1 position to hold at the close of each price date.

    A signal dated D is acted on at the close of the first trading day after D,
    because TradingAgents' analysis for D can include news published after D's close.
    """
    held, i, out = 0, 0, []
    for day in dates:
        while i < len(targets) and targets[i][0] < day:
            if targets[i][1] is not None:
                held = targets[i][1]
            i += 1
        out.append(held)
    return pd.Series(out, index=dates, name="position")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Progress:
    """Live progress for the dashboard, saved under status/.

    Use it as a context manager so a crash or Ctrl+C is reported too. Writing
    progress is best-effort: a failed write never stops the pipeline.
    """

    def __init__(self, step: str, title: str, total: int | None = None) -> None:
        self.step = step
        self._lock = threading.RLock()
        self.state = {
            "step": step, "title": title, "state": "running", "done": 0, "total": total,
            "current": None, "summary": None, "error": None,
            "started": now_iso(), "updated": now_iso(), "finished": None,
        }
        self._save()
        self.log(f"Started: {title}")

    def update(self, **fields: object) -> None:
        with self._lock:
            self.state.update(fields, updated=now_iso())
            self._save()

    def advance(self, **fields: object) -> None:
        with self._lock:
            self.state["done"] += 1
            self.update(**fields)

    def log(self, message: str, level: str = "info") -> None:
        line = json.dumps({"time": now_iso(), "step": self.step, "level": level, "message": message})
        try:
            STATUS_DIR.mkdir(parents=True, exist_ok=True)
            with self._lock, EVENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def finish(self, summary: str) -> None:
        self.update(state="done", summary=summary, current=None, finished=now_iso())
        self.log(f"Finished: {summary}")

    def fail(self, error: str) -> None:
        self.update(state="failed", error=error, current=None, finished=now_iso())
        self.log(f"Failed: {error}", level="error")

    def __enter__(self) -> Progress:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is KeyboardInterrupt:
            self.fail("stopped (Ctrl+C)")
        elif exc is not None:
            self.fail(str(exc) or exc_type.__name__)
        elif self.state["state"] == "running":
            self.finish("done")
        return False

    def _save(self) -> None:
        path = STATUS_DIR / f"{self.step}.json"
        tmp = path.with_suffix(".tmp")
        try:
            STATUS_DIR.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self.state), encoding="utf-8")
            for _ in range(10):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:  # the dashboard is reading the file; try again
                    time.sleep(0.05)
        except OSError:
            pass

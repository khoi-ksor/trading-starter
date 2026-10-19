"""Live dashboard: watch the pipeline work, in your browser.

    python dashboard.py          # opens http://127.0.0.1:8765

Leave it running in its own terminal while you run the steps in another. It only
reads the files the steps write (status/, signals/, reports/, data/), so it never
changes anything, and it is reachable from this computer only.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd

import common
import config

PAGE = common.ROOT / "dashboard.html"
STEPS = [
    ("step1", "Get prices", "OpenBB"),
    ("step2", "AI signals", "TradingAgents + Claude"),
    ("step3", "Quick test", "vectorbt"),
    ("step4", "Realistic test", "NautilusTrader"),
    ("step5", "Paper trading", "Alpaca"),
]
SIGNAL_FILES = {"ai": common.AI_SIGNALS, "demo": common.DEMO_SIGNALS}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_events(limit: int = 150) -> list[dict]:
    """The newest events, read from the end of the log so a long log stays fast."""
    try:
        with common.EVENTS_FILE.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except ValueError:  # a line cut in half by the 64 KB window
            continue
    return events[::-1]


def read_csv(path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(pd.read_csv(path).to_json(orient="records"))
    except (OSError, ValueError):
        return []


def source_view(source: str) -> dict | None:
    """Signals, price charts and backtest results for the AI or the demo signals."""
    path = SIGNAL_FILES[source]
    if not path.exists():
        return None
    signals = common.load_signals(path)
    charts = []
    for symbol in signals["symbol"].unique():
        targets = common.signal_targets(signals, symbol)
        try:
            prices = common.load_prices(symbol)
        except FileNotFoundError:
            continue
        prices = prices[prices.index >= targets[0][0] - pd.Timedelta(days=14)]
        held = common.target_positions(targets, prices.index)
        rows = signals[signals["symbol"] == symbol]
        charts.append({
            "symbol": symbol,
            "dates": [d.strftime("%Y-%m-%d") for d in prices.index],
            "close": [round(float(c), 6) for c in prices["close"]],
            "held": [int(h) for h in held],
            "signals": [{"date": r.date.strftime("%Y-%m-%d"), "rating": r.rating} for r in rows.itertuples()],
        })
    return {
        "signal_count": len(signals),
        "charts": charts,
        "quick": read_csv(common.REPORTS_DIR / f"quick_test_{source}.csv"),
        "nautilus": read_csv(common.REPORTS_DIR / f"nautilus_backtest_{source}.csv"),
    }


def state() -> dict:
    return {
        "now": common.now_iso(),
        "steps": [
            {"id": sid, "name": name, "tool": tool, "status": read_json(common.STATUS_DIR / f"{sid}.json")}
            for sid, name, tool in STEPS
        ],
        "events": read_events(),
        "sources": {source: source_view(source) for source in SIGNAL_FILES},
        "position_size": config.POSITION_SIZE_USD,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
        elif self.path == "/api/state":
            try:
                body, code = json.dumps(state()).encode(), 200
            except Exception as exc:  # e.g. a CSV caught mid-write; the page keeps its last view
                body, code = json.dumps({"error": str(exc)}).encode(), 503
            self._send(code, "application/json", body)
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard running at {url}  (press Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")


if __name__ == "__main__":
    main()

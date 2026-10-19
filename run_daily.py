r"""The bot's daily run: fresh prices -> today's AI ratings -> paper trades.

Windows Task Scheduler runs this every day at 5:15 PM (task "Trading starter daily run").
You can also run it by hand:

    .venv\Scripts\python run_daily.py             # the real run (paper trades only)
    .venv\Scripts\python run_daily.py --dry-run   # same steps, but no AI calls and no orders

Weekdays rate every symbol; weekends rate crypto only, since stock markets are closed.
Each run is logged to logs/daily_<date>.log, and its progress shows on the dashboard.
TradingAgents keeps a memory of these daily calls, scores them once the results are in,
and feeds the lessons into later analyses. That is the self-learning part.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import common
import config

LOGS_DIR = common.ROOT / "logs"
# On Windows the scheduler starts pythonw (no window); the steps still need the console python.
_exe = Path(sys.executable)
PYTHON = str(_exe.with_name("python.exe")) if _exe.name.lower() == "pythonw.exe" else sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="no AI calls and no orders")
    args = parser.parse_args()

    today = date.today()
    symbols = config.CRYPTO if today.weekday() >= 5 else common.watchlist()
    steps = [
        ["step1_get_data.py"],
        ["step2_ai_signals.py", "--today", "--symbols", *symbols] + (["--dry-run"] if args.dry_run else []),
        ["step5_paper_trade.py"] + ([] if args.dry_run else ["--submit"]),
    ]

    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"daily_{today.isoformat()}.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n##### Daily run {datetime.now():%Y-%m-%d %H:%M}{' (dry run)' if args.dry_run else ''} #####\n")
        for step in steps:
            log.write(f"\n=== {datetime.now():%H:%M:%S}  {' '.join(step)} ===\n")
            log.flush()
            result = subprocess.run(
                [PYTHON, *step], cwd=common.ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                log.write(f"\nStopped: {step[0]} failed (exit code {result.returncode}).\n")
                return result.returncode
        log.write(f"\nDaily run finished at {datetime.now():%H:%M:%S}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

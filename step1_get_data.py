"""Step 1: download daily prices for the watchlist with OpenBB (free Yahoo Finance data).

    python step1_get_data.py
"""

from __future__ import annotations

import common
import config


def main() -> None:
    symbols = common.watchlist()
    with common.Progress("step1", "Download prices", total=len(symbols)) as progress:
        print("Loading OpenBB (the first run takes a minute while it sets itself up)...")
        progress.update(current="loading OpenBB")
        from openbb import obb

        common.PRICES_DIR.mkdir(parents=True, exist_ok=True)
        saved = 0
        for symbol in symbols:
            progress.update(current=symbol)
            fetch = obb.crypto.price.historical if common.is_crypto(symbol) else obb.equity.price.historical
            try:
                df = fetch(
                    symbol=symbol,
                    start_date=config.PRICE_START,
                    end_date=config.PRICE_END,
                    provider="yfinance",
                ).to_df()
            except Exception as exc:  # one bad symbol shouldn't stop the rest
                print(f"{symbol}: download failed ({exc})")
                progress.log(f"{symbol}: download failed ({exc})", level="error")
                progress.advance()
                continue
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df.index = df.index.map(lambda d: str(d)[:10])
            df.index.name = "date"
            df.to_csv(common.price_path(symbol))
            saved += 1
            message = f"{symbol}: {len(df)} days, {df.index[0]} to {df.index[-1]}"
            print(message)
            progress.log(message)
            progress.advance()
        progress.finish(f"{saved} of {len(symbols)} symbols downloaded")


if __name__ == "__main__":
    main()

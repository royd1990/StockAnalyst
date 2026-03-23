"""
Value Investing Strategy
========================
Screens stocks based on classic value investing criteria:
  - P/E ratio < 20
  - P/B ratio < 2
  - Promoter / Insider holding > 60%

Uses yfinance `heldPercentInsiders` as the promoter/insider holding proxy.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional
import time as _time

import pandas as pd
import yfinance as yf

from src.yf_auth import (
    warmup, refresh_crumb, on_auth_error, get_generation, is_auth_error,
    rate_limit, rate_release,
)


def _to_float(v) -> Optional[float]:
    """Safely coerce a yfinance value to float, returning None if not numeric."""
    if v is None:
        return None
    try:
        result = float(v)
        # Reject NaN and Infinity — not usable as filter values
        if result != result or abs(result) == float("inf"):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _fetch_value_data(ticker: str) -> Optional[dict]:
    """Fetch data needed for the Value Investing screen for a single ticker.

    Retries up to 2 times on 401/crumb errors, resetting the yfinance
    authentication singleton before each retry.
    """
    for attempt in range(3):
        gen = get_generation()
        rate_limit()
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            price = _to_float(
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("previousClose")
            )
            if not price:
                return None

            pe = _to_float(info.get("trailingPE"))
            pb = _to_float(info.get("priceToBook"))
            insider_pct = _to_float(info.get("heldPercentInsiders"))  # decimal, e.g. 0.65 = 65%

            name = info.get("shortName") or info.get("longName") or ticker
            sector = info.get("sector") or "—"
            industry = info.get("industry") or "—"
            mktcap = _to_float(info.get("marketCap")) or 0
            currency = info.get("currency", "")
            dividend_yield = _to_float(info.get("dividendYield")) or 0
            roe = _to_float(info.get("returnOnEquity")) or 0
            de_raw = _to_float(info.get("debtToEquity"))

            return {
                "Ticker": ticker,
                "Name": name,
                "Sector": sector,
                "Industry": industry,
                "Currency": currency,
                "Price": price,
                "Market Cap": mktcap,
                "PE": pe,
                "PB": pb,
                "Insider %": insider_pct,
                "Dividend Yield": dividend_yield,
                "ROE": roe,
                "DE Raw": de_raw,
            }
        except Exception as e:
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        finally:
            rate_release()
    return None


def run_value_strategy(
    tickers: List[str],
    max_pe: float = 20.0,
    max_pb: float = 2.0,
    min_insider_pct: float = 60.0,
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    Run the Value Investing Strategy on a list of tickers.

    Parameters
    ----------
    tickers          : list of ticker symbols
    max_pe           : maximum P/E ratio (default 20)
    max_pb           : maximum P/B ratio (default 2)
    min_insider_pct  : minimum insider/promoter holding % (default 60)
    max_workers      : parallel fetch threads
    progress_cb      : optional callback(done, total) for progress updates

    Returns a DataFrame of qualifying stocks sorted by P/E ascending.
    """
    warmup()

    results = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 75

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_value_data, t): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

            if row is None:
                continue

            pe = row["PE"]
            pb = row["PB"]
            insider = row["Insider %"]

            # Apply filters — all three must be present and pass
            pe_ok = pe is not None and 0 < pe <= max_pe
            pb_ok = pb is not None and pb <= max_pb
            insider_ok = insider is not None and insider * 100 >= min_insider_pct

            if not (pe_ok and pb_ok and insider_ok):
                continue

            de_display = round(row["DE Raw"] / 100, 2) if row["DE Raw"] is not None else None

            results.append({
                "Ticker": row["Ticker"],
                "Name": row["Name"],
                "Sector": row["Sector"],
                "Industry": row["Industry"],
                "Currency": row["Currency"],
                "Price": round(row["Price"], 2),
                "Market Cap": row["Market Cap"],
                "P/E": round(pe, 1),
                "P/B": round(pb, 2),
                "Insider/Promoter %": round(insider * 100, 1),
                "Dividend Yield %": round(row["Dividend Yield"] * 100, 2),
                "ROE %": round(row["ROE"] * 100, 1),
                "D/E": de_display,
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("P/E", ascending=True)
    return df.reset_index(drop=True)

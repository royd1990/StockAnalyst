"""
Swedish Growth Strategy
========================
Screens Swedish / Nordic North stocks for high-growth small-mid caps.

9 quantitative filters:
  1. Market Cap: 500M – 15B SEK
  2. Revenue Growth >= 20% YoY
  3. Gross Margin >= 40%
  4. Revenue >= 200M SEK
  5. Operating Margin improving (current > previous year)
  6. Price >= 85% of 52-week high
  7. 12-month return > OMX Stockholm index return
  8. Debt/Equity < 1
  9. Daily liquidity >= 5M SEK

Signals:
  STRONG BUY — 9/9 checks pass
  BUY        — 7-8/9 checks pass
  WATCH      — 5-6/9 checks pass
  FAIL       — <5 checks pass
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
        if result != result or abs(result) == float("inf"):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _fetch_benchmark_return(ticker: str = "^OMX") -> Optional[float]:
    """Fetch 12-month return for the benchmark index. Called once before parallel loop."""
    for attempt in range(3):
        gen = get_generation()
        rate_limit()
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            if hist is None or hist.empty or "Close" not in hist.columns or len(hist) < 20:
                return None
            closes = hist["Close"].dropna()
            if len(closes) < 2:
                return None
            return (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0])
        except Exception as e:
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        finally:
            rate_release()
    return None


def _fetch_swedish_data(ticker: str, benchmark_return: Optional[float]) -> Optional[dict]:
    """Fetch data and apply all 9 filters for a single Swedish/Nordic ticker.

    Releases the semaphore between API calls so other tickers can proceed.
    """
    for attempt in range(3):
        gen = get_generation()

        # ── Call 1: .info ────────────────────────────────────────────────
        rate_limit()
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        price = _to_float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if not price:
            return None

        name = info.get("shortName") or info.get("longName") or ticker
        sector = info.get("sector") or "—"
        industry = info.get("industry") or "—"
        currency = info.get("currency", "")

        mktcap = _to_float(info.get("marketCap")) or 0
        rev_growth = _to_float(info.get("revenueGrowth"))
        gross_margin = _to_float(info.get("grossMargins"))
        total_revenue = _to_float(info.get("totalRevenue")) or 0
        op_margin = _to_float(info.get("operatingMargins"))
        w52_high = _to_float(info.get("fiftyTwoWeekHigh"))
        de_raw = _to_float(info.get("debtToEquity"))
        avg_volume = _to_float(info.get("averageVolume")) or 0

        # ── Call 2: .history(1y) for 12-month return ─────────────────────
        rate_limit()
        try:
            hist = stock.history(period="1y")
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        stock_return_12m = None
        if hist is not None and not hist.empty and "Close" in hist.columns:
            closes = hist["Close"].dropna()
            if len(closes) >= 20:
                stock_return_12m = (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0])

        # ── Call 3: .income_stmt for operating margin improvement ────────
        op_margin_prev = None
        rate_limit()
        try:
            income = stock.income_stmt
            if income is not None and not income.empty and income.shape[1] >= 2:
                if "Operating Income" in income.index and "Total Revenue" in income.index:
                    rev_curr = _to_float(income.loc["Total Revenue"].iloc[0])
                    rev_prev = _to_float(income.loc["Total Revenue"].iloc[1])
                    oi_curr = _to_float(income.loc["Operating Income"].iloc[0])
                    oi_prev = _to_float(income.loc["Operating Income"].iloc[1])
                    if rev_prev and rev_prev > 0 and oi_prev is not None:
                        op_margin_prev = oi_prev / rev_prev
                    if rev_curr and rev_curr > 0 and oi_curr is not None and op_margin is None:
                        op_margin = oi_curr / rev_curr
        except Exception:
            pass
        finally:
            rate_release()

        # ── Apply 9 checks ───────────────────────────────────────────────
        daily_liquidity = avg_volume * price

        checks = {}

        # 1. Market Cap: 500M – 15B SEK
        checks["Mkt Cap 500M–15B"] = bool(500_000_000 <= mktcap <= 15_000_000_000)

        # 2. Revenue Growth >= 20%
        checks["Rev Growth ≥20%"] = bool(rev_growth is not None and rev_growth >= 0.20)

        # 3. Gross Margin >= 40%
        checks["Gross Margin ≥40%"] = bool(gross_margin is not None and gross_margin >= 0.40)

        # 4. Revenue >= 200M SEK
        checks["Revenue ≥200M"] = bool(total_revenue >= 200_000_000)

        # 5. Operating Margin improving
        if op_margin is not None and op_margin_prev is not None:
            checks["Op Margin Improving"] = bool(op_margin > op_margin_prev)
        else:
            checks["Op Margin Improving"] = None  # N/A

        # 6. Price >= 85% of 52W High
        if w52_high and w52_high > 0:
            price_pct_of_52w = price / w52_high
            checks["Price ≥85% of 52W"] = bool(price_pct_of_52w >= 0.85)
        else:
            checks["Price ≥85% of 52W"] = None

        # 7. 12-month return > OMX
        if stock_return_12m is not None and benchmark_return is not None:
            checks["12M > OMX"] = bool(stock_return_12m > benchmark_return)
        else:
            checks["12M > OMX"] = None

        # 8. Debt/Equity < 1 (yfinance reports D/E as percentage, e.g. 50 = 0.5x)
        if de_raw is not None:
            checks["D/E < 1"] = bool(de_raw < 100)
        else:
            # No debt info — assume passes (many growth companies have no debt)
            checks["D/E < 1"] = True

        # 9. Daily liquidity >= 5M SEK
        checks["Liquidity ≥5M SEK"] = bool(daily_liquidity >= 5_000_000)

        # ── Score & Signal ───────────────────────────────────────────────
        passed = sum(1 for v in checks.values() if v is True)
        total_applicable = sum(1 for v in checks.values() if v is not None)

        if total_applicable >= 7 and passed == total_applicable:
            signal = "STRONG BUY"
        elif passed >= 7:
            signal = "BUY"
        elif passed >= 5:
            signal = "WATCH"
        else:
            signal = "FAIL"

        de_display = round(de_raw / 100, 2) if de_raw is not None else None

        return {
            "Signal": signal,
            "Ticker": ticker,
            "Name": name,
            "Sector": sector,
            "Industry": industry,
            "Currency": currency,
            "Price": round(price, 2),
            "Market Cap (M)": round(mktcap / 1e6, 0) if mktcap else None,
            "Revenue (M)": round(total_revenue / 1e6, 0) if total_revenue else None,
            "Rev Growth %": round(rev_growth * 100, 1) if rev_growth is not None else None,
            "Gross Margin %": round(gross_margin * 100, 1) if gross_margin is not None else None,
            "Op Margin %": round(op_margin * 100, 1) if op_margin is not None else None,
            "Op Margin Prev %": round(op_margin_prev * 100, 1) if op_margin_prev is not None else None,
            "Price/52W %": round(price / w52_high * 100, 1) if w52_high and w52_high > 0 else None,
            "12M Return %": round(stock_return_12m * 100, 1) if stock_return_12m is not None else None,
            "OMX Return %": round(benchmark_return * 100, 1) if benchmark_return is not None else None,
            "D/E": de_display,
            "Liquidity (M)": round(daily_liquidity / 1e6, 1) if daily_liquidity else None,
            "Checks Passed": f"{passed}/{total_applicable}",
            "Checks Detail": checks,
            "Market Cap": mktcap,
            "_passed": passed,
            "_total": total_applicable,
        }
    return None


def run_swedish_strategy(
    tickers: List[str],
    benchmark_ticker: str = "^OMX",
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Run the Swedish Growth Strategy on a list of tickers.

    Parameters
    ----------
    tickers          : list of ticker symbols (typically Nordic North universe)
    benchmark_ticker : OMX Stockholm index ticker for relative return comparison
    max_workers      : parallel fetch threads
    progress_cb      : optional callback(done, total) for progress updates

    Returns a DataFrame sorted by signal priority then Revenue Growth descending.
    """
    warmup()

    # Fetch benchmark 12-month return once
    benchmark_return = _fetch_benchmark_return(benchmark_ticker)

    rows: list = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 75

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(_fetch_swedish_data, t, benchmark_return): t
            for t in tickers
        }
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                rows.append(result)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    _order = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2, "FAIL": 3}
    df["_sig_order"] = df["Signal"].map(_order)
    df = df.sort_values(
        ["_sig_order", "Rev Growth %"],
        ascending=[True, False],
    )
    df = df.drop(columns=["_sig_order", "Checks Detail", "_passed", "_total"], errors="ignore")

    return df.reset_index(drop=True)

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

import pandas as pd
import yfinance as yf


def _fetch_stock_data(ticker: str) -> Optional[dict]:
    """Fetch data needed for the 52W High Strategy for a single ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if not price:
            return None

        w52_high = info.get("fiftyTwoWeekHigh")
        if not w52_high:
            return None

        # All-time high from full price history
        try:
            hist = stock.history(period="max")
            if hist.empty or "High" not in hist.columns:
                return None
            all_time_high = float(hist["High"].max())
        except Exception:
            return None

        if all_time_high <= 0:
            return None

        # ATH gap: how close is the 52W high to the all-time high?
        # Negative = 52W high is below ATH; positive = 52W high exceeds previous ATH
        ath_gap_pct = (w52_high - all_time_high) / all_time_high * 100

        # Breakout: how is the current price relative to the 52W high?
        breakout_pct = (price - w52_high) / w52_high * 100

        # Fundamentals scoring (5 criteria)
        roe = info.get("returnOnEquity") or 0
        pe = info.get("trailingPE")
        rev_growth = info.get("revenueGrowth") or 0
        profit_margin = info.get("profitMargins") or 0
        de_raw = info.get("debtToEquity")  # yfinance: 150 => 1.5x ratio

        fund_score = 0
        fund_checks = []
        if roe > 0.15:
            fund_score += 1
            fund_checks.append("ROE>15%")
        if pe and 0 < pe < 40:
            fund_score += 1
            fund_checks.append("P/E<40")
        if rev_growth > 0.05:
            fund_score += 1
            fund_checks.append("RevGrowth>5%")
        if profit_margin > 0.08:
            fund_score += 1
            fund_checks.append("Margin>8%")
        if de_raw is None or de_raw < 100:
            fund_score += 1
            fund_checks.append("D/E<1x")

        return {
            "Ticker": ticker,
            "Name": info.get("shortName") or info.get("longName") or ticker,
            "Sector": info.get("sector") or "—",
            "Currency": info.get("currency", ""),
            "Price": round(price, 2),
            "52W High": round(w52_high, 2),
            "All-Time High": round(all_time_high, 2),
            "ATH Gap %": round(ath_gap_pct, 1),
            "Breakout %": round(breakout_pct, 1),
            "Fund Score": fund_score,
            "Fund Checks": ", ".join(fund_checks) if fund_checks else "—",
            "ROE %": round(roe * 100, 1) if roe else None,
            "P/E": round(pe, 1) if pe else None,
            "Rev Growth %": round(rev_growth * 100, 1) if rev_growth else None,
            "Net Margin %": round(profit_margin * 100, 1) if profit_margin else None,
            "D/E": round(de_raw / 100, 2) if de_raw is not None else None,
            "_mktcap": info.get("marketCap") or 0,
        }
    except Exception:
        return None


def run_52w_high_strategy(
    tickers: List[str],
    ath_gap_threshold: float = 8.0,
    breakout_threshold: float = 3.0,
    min_fund_score: int = 3,
    max_workers: int = 20,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    Run the 52W High Strategy on a list of tickers.

    Screening logic:
      1. 52W high is within ath_gap_threshold% below (or at/above) the all-time high.
      2. Signal assignment:
         - BUY   : price broke above 52W high AND fundamentals are strong
         - WATCH : price within breakout_threshold% of 52W high AND strong fundamentals
         - NEAR  : price within breakout_threshold% of 52W high, fundamentals weak
         - PASS  : does not meet proximity criteria

    Returns a DataFrame sorted by signal priority then market cap desc.
    """
    rows: list = []
    total = len(tickers)
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_stock_data, t): t for t in tickers}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                rows.append(result)
            done += 1
            if progress_cb:
                progress_cb(done, total)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Keep only stocks where 52W high is within threshold of ATH
    df = df[df["ATH Gap %"] >= -ath_gap_threshold]

    if df.empty:
        return df

    def _assign_signal(row: pd.Series) -> str:
        near_52w = row["Breakout %"] >= -breakout_threshold
        strong_fund = row["Fund Score"] >= min_fund_score
        broken_out = row["Breakout %"] >= 0
        if broken_out and strong_fund:
            return "BUY"
        if near_52w and strong_fund:
            return "WATCH"
        if near_52w:
            return "NEAR HIGH"
        return "PASS"

    df["Signal"] = df.apply(_assign_signal, axis=1)

    _order = {"BUY": 0, "WATCH": 1, "NEAR HIGH": 2, "PASS": 3}
    df["_sig_order"] = df["Signal"].map(_order)
    df = df.sort_values(["_sig_order", "_mktcap"], ascending=[True, False])
    df = df.drop(columns=["_sig_order", "_mktcap"], errors="ignore")

    return df.reset_index(drop=True)

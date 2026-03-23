"""
Breakout Analyzer Strategy
===========================
Merges the 52W High Strategy and Double Engine Multibagger into a single
two-phase approach:

  Phase 1 — Fetch all data per ticker (price, 52W high, ATH, fundamentals,
            growth metrics, technical indicators).
  Phase 2 — Apply configurable filters + composite scoring + signal assignment.

Stocks are ranked by signal priority (BUY > WATCH > NEAR HIGH > PASS),
then by Composite Score descending.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional
import time as _time

import numpy as np
import pandas as pd
import yfinance as yf

from src.yf_auth import (
    warmup, refresh_crumb, on_auth_error, get_generation, is_auth_error,
    rate_limit, rate_release,
)

# ── Sector average PE lookup ─────────────────────────────────────────────────
SECTOR_PE: dict = {
    "Technology": 35,
    "Healthcare": 28,
    "Consumer Cyclical": 22,
    "Consumer Defensive": 20,
    "Financial Services": 14,
    "Industrials": 20,
    "Energy": 14,
    "Utilities": 17,
    "Real Estate": 24,
    "Basic Materials": 14,
    "Communication Services": 20,
}
DEFAULT_SECTOR_PE = 20

# ── Tailwind sectors / industries (partial keyword match) ─────────────────────
TAILWIND_KEYWORDS = {
    "artificial intelligence", "semiconductor", "electric vehicle",
    "cybersecurity", "cloud", "defense", "automation", "energy transition",
    "renewable", "software", "information technology", "technology hardware",
    "data center", "machine learning", "robotics",
}



def _to_float(v):
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


def _norm(value: float, lo: float, hi: float) -> float:
    """Linearly normalize value to [0, 100] clamped between lo and hi."""
    if hi <= lo:
        return 0.0
    return float(np.clip((value - lo) / (hi - lo) * 100, 0, 100))


def _industry_is_tailwind(sector: str, industry: str) -> bool:
    text = f"{sector} {industry}".lower()
    return any(kw in text for kw in TAILWIND_KEYWORDS)


def _fetch_breakout_data(ticker: str) -> Optional[dict]:
    """Fetch all data needed for the Breakout Analyzer for a single ticker.

    Fetches .info and .history (2y) while releasing the rate-limit semaphore
    between calls so other tickers can proceed concurrently.
    Retries up to 2 times on 401/crumb errors.
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

        w52_high = _to_float(info.get("fiftyTwoWeekHigh"))
        if not w52_high:
            return None

        # ── Call 2: .history (2y for ATH + volume trend) ─────────────────
        rate_limit()
        try:
            hist = stock.history(period="2y")
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        if hist.empty or "High" not in hist.columns:
            return None

        all_time_high = float(hist["High"].max())
        volume_trend = None
        if "Volume" in hist.columns and len(hist) >= 60:
            vols = hist["Volume"]
            recent = float(vols.tail(30).mean())
            prior = float(vols.iloc[-60:-30].mean())
            if prior > 0:
                volume_trend = recent / prior

        if not all_time_high or all_time_high <= 0:
            return None

        # ATH gap & breakout
        ath_gap_pct = (w52_high - all_time_high) / all_time_high * 100
        breakout_pct = (price - w52_high) / w52_high * 100

        # Fundamentals (all from .info — no income_stmt fetch needed)
        roe = _to_float(info.get("returnOnEquity")) or 0
        pe = _to_float(info.get("trailingPE"))
        rev_growth = _to_float(info.get("revenueGrowth")) or 0
        profit_margin = _to_float(info.get("profitMargins")) or 0
        de_raw = _to_float(info.get("debtToEquity"))
        mktcap = _to_float(info.get("marketCap")) or 0
        fcf = _to_float(info.get("freeCashflow"))
        eps_growth = _to_float(info.get("earningsGrowth")) or 0

        # Use .info growth as CAGR proxy (skipping income_stmt for speed)
        rev_cagr = rev_growth
        eps_cagr = eps_growth

        # Valuation
        fwd_pe = _to_float(info.get("forwardPE"))
        peg = _to_float(info.get("pegRatio"))
        sector = info.get("sector") or "—"
        industry = info.get("industry") or "—"
        industry_pe = SECTOR_PE.get(sector, DEFAULT_SECTOR_PE)

        # Technical
        ma50 = _to_float(info.get("fiftyDayAverage"))
        ma200 = _to_float(info.get("twoHundredDayAverage"))

        return {
            "Ticker": ticker,
            "Name": info.get("shortName") or info.get("longName") or ticker,
            "Sector": sector,
            "Industry": industry,
            "Currency": info.get("currency", ""),
            "Price": round(price, 2),
            "52W High": round(w52_high, 2),
            "All-Time High": round(all_time_high, 2),
            "ATH Gap %": round(ath_gap_pct, 1),
            "Breakout %": round(breakout_pct, 1),
            "ROE": roe,
            "P/E": pe,
            "Rev Growth": rev_growth,
            "Profit Margin": profit_margin,
            "DE Raw": de_raw,
            "Market Cap": mktcap,
            "FCF": fcf,
            "Rev CAGR": rev_cagr,
            "EPS CAGR": eps_cagr,
            "Fwd PE": fwd_pe,
            "PEG": peg,
            "Industry PE": industry_pe,
            "MA50": ma50,
            "MA200": ma200,
            "Volume Trend": volume_trend,
        }
    return None


def _score_and_signal(
    row: dict,
    ath_gap_threshold: float,
    breakout_threshold: float,
    min_composite_score: float,
) -> Optional[dict]:
    """Apply filters, compute scores, and assign signal.

    Returns None if the stock fails the ATH gap technical filter.
    """
    # ── Technical filter: ATH gap ────────────────────────────────────────────
    if row["ATH Gap %"] < -ath_gap_threshold:
        return None

    price = row["Price"]
    roe = row["ROE"]
    pe = row["P/E"]
    rev_growth = row["Rev Growth"]
    profit_margin = row["Profit Margin"]
    de_raw = row["DE Raw"]
    rev_cagr = row["Rev CAGR"]
    eps_cagr = row["EPS CAGR"]
    peg = row["PEG"]
    industry_pe = row["Industry PE"]
    mktcap = row["Market Cap"]
    fcf = row["FCF"]
    ma50 = row["MA50"]
    ma200 = row["MA200"]
    volume_trend = row["Volume Trend"]
    sector = row["Sector"]
    industry = row["Industry"]
    w52_high = row["52W High"]

    # ── Simple Fund Score (0-5) from 52W strategy ────────────────────────────
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

    # ── E1 Checks (informational) ───────────────────────────────────────────
    e1_checks = {
        "Rev CAGR > 15%": rev_cagr > 0.15,
        "EPS > 15%": eps_cagr > 0.15,
        "MktCap > $100M": mktcap >= 100_000_000,
        "ROE > 15%": roe > 0.15,
        "FCF > 0": fcf is not None and fcf > 0,
        "D/E < 1x": de_raw is None or de_raw < 100,
    }
    e1_pass = sum(e1_checks.values())

    # ── Composite Score (0-100) ──────────────────────────────────────────────
    # EPS growth score: 0% = 0pts, 60% = 100pts
    eps_score = _norm(eps_cagr * 100, 0, 60) if eps_cagr else 45.0

    # Revenue growth score: 0% = 0pts, 40% = 100pts
    rev_score = _norm(rev_cagr * 100, 0, 40) if rev_cagr else 40.0

    # Momentum score: breakout strength + golden cross + volume
    golden_cross = bool(ma50 and ma200 and ma50 > ma200)
    m_breakout = _norm(price / w52_high * 100 if w52_high else 0, 98, 110)
    m_gc = 100.0 if golden_cross else 0.0
    m_vol = _norm(volume_trend * 100 if volume_trend else 100, 90, 150)
    momentum_score = 0.50 * m_breakout + 0.30 * m_gc + 0.20 * m_vol

    # Valuation discount score
    if peg is not None and peg > 0:
        val_score = _norm(2.0 - peg, 0.0, 2.0)
    elif pe is not None and industry_pe and pe > 0:
        discount = (industry_pe - pe) / industry_pe * 100
        val_score = _norm(discount, -20, 50)
    else:
        val_score = 40.0  # neutral default

    # Industry tailwind score
    tailwind = _industry_is_tailwind(sector, industry)
    industry_score = 100.0 if tailwind else 30.0

    composite_score = (
        0.40 * eps_score
        + 0.30 * rev_score
        + 0.15 * momentum_score
        + 0.10 * val_score
        + 0.05 * industry_score
    )

    # ── Signal assignment ────────────────────────────────────────────────────
    breakout_pct = row["Breakout %"]
    near_52w = breakout_pct >= -breakout_threshold
    strong = composite_score >= min_composite_score
    broken_out = breakout_pct >= 0

    if broken_out and strong:
        signal = "BUY"
    elif near_52w and strong:
        signal = "WATCH"
    elif near_52w:
        signal = "NEAR HIGH"
    else:
        signal = "PASS"

    de_display = round(de_raw / 100, 2) if de_raw is not None else None

    return {
        "Signal": signal,
        "Ticker": row["Ticker"],
        "Name": row["Name"],
        "Sector": sector,
        "Industry": industry,
        "Currency": row["Currency"],
        "Price": row["Price"],
        "52W High": row["52W High"],
        "All-Time High": row["All-Time High"],
        "ATH Gap %": row["ATH Gap %"],
        "Breakout %": row["Breakout %"],
        "Composite Score": round(composite_score, 1),
        "Fund Score": fund_score,
        "Fund Checks": ", ".join(fund_checks) if fund_checks else "—",
        "Rev CAGR %": round(rev_cagr * 100, 1),
        "EPS Growth %": round(eps_cagr * 100, 1),
        "ROE %": round(roe * 100, 1) if roe else None,
        "Net Margin %": round(profit_margin * 100, 1) if profit_margin else None,
        "D/E": de_display,
        "P/E": round(pe, 1) if pe else None,
        "Industry P/E": industry_pe,
        "PEG": round(peg, 2) if peg else None,
        "Golden Cross": "Yes" if golden_cross else "No",
        "Vol Trend": round(volume_trend, 2) if volume_trend else None,
        "Tailwind Sector": "Yes" if tailwind else "No",
        "E1 Checks": f"{e1_pass}/6",
        "EPS Score": round(eps_score, 1),
        "Rev Score": round(rev_score, 1),
        "Momentum Score": round(momentum_score, 1),
        "Val Score": round(val_score, 1),
        "Market Cap": row["Market Cap"],
    }


def run_breakout_strategy(
    tickers: List[str],
    ath_gap_threshold: float = 8.0,
    breakout_threshold: float = 3.0,
    min_composite_score: float = 40.0,
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Run the Breakout Analyzer on a list of tickers.

    Two-phase approach:
      Phase 1 — Parallel data fetch for all tickers.
      Phase 2 — Filter, score, and assign signals.

    Returns a DataFrame sorted by signal priority (BUY > WATCH > NEAR HIGH > PASS),
    then by Composite Score descending.
    """
    warmup()

    rows: list = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 75

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_breakout_data, t): t for t in tickers}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                scored = _score_and_signal(
                    result, ath_gap_threshold, breakout_threshold, min_composite_score
                )
                if scored is not None:
                    rows.append(scored)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    _order = {"BUY": 0, "WATCH": 1, "NEAR HIGH": 2, "PASS": 3}
    df["_sig_order"] = df["Signal"].map(_order)
    df = df.sort_values(["_sig_order", "Composite Score"], ascending=[True, False])
    df = df.drop(columns=["_sig_order"], errors="ignore")

    return df.reset_index(drop=True)

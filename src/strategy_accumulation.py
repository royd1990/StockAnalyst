"""
Accumulation Detection Strategy
================================
Detects stocks that are likely being accumulated before a breakout.

Uses a 13-rule scoring system across 5 rule groups:
  A — Trend Stabilization (3 rules)
  B — Base Formation / Compression (3 rules)
  C — Volume Accumulation (3 rules)
  D — Relative Strength (2 rules)
  E — Pre-Breakout Condition (2 rules)

Score = sum of boolean rules (0-13).  A stock qualifies when:
  Score >= 10  AND  C1 == True  AND  C2 == True  AND  D1 == True

Signals:
  ACCUMULATION + BREAKOUT — score >= 10, mandatory pass, entry trigger fires
  ACCUMULATION            — score >= 10, mandatory pass
  BUILDING                — score >= 7,  mandatory pass
  NEUTRAL                 — everything else
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional
import time as _time

import numpy as np
import pandas as pd
import yfinance as yf

from src.yf_auth import (
    warmup, refresh_crumb, on_auth_error, get_generation, is_auth_error,
    rate_limit, rate_release,
)

# ── Default benchmark index per market ───────────────────────────────────────
BENCHMARK_MAP: Dict[str, str] = {
    "US": "^GSPC",
    "IN_NSE": "^NSEI",
    "IN_BSE": "^BSESN",
    "GB": "^FTSE",
    "DE": "^GDAXI",
    "FR": "^FCHI",
    "JP": "^N225",
    "HK": "^HSI",
    "AU": "^AXJO",
    "CA": "^GSPTSE",
    "BR": "^BVSP",
    "SG": "^STI",
    "CH": "^SSMI",
    "KR": "^KS11",
    "NL": "^AEX",
    "ES": "^IBEX",
    "SE": "^OMX",
    "ZA": "^J203.JO",
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


def _fetch_benchmark(ticker: str, period: str = "6mo") -> Optional[pd.Series]:
    """Fetch benchmark close prices.  Called once before the parallel loop."""
    for attempt in range(3):
        gen = get_generation()
        rate_limit()
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist is None or hist.empty or "Close" not in hist.columns:
                return None
            return hist["Close"]
        except Exception as e:
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        finally:
            rate_release()
    return None


def _compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> Optional[float]:
    """Compute ATR(period) from numpy arrays.  Returns the last ATR value."""
    if len(close) < period + 1:
        return None
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    atr_series = pd.Series(tr).rolling(period).mean()
    val = atr_series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _fetch_accumulation_data(
    ticker: str,
    benchmark_close: Optional[pd.Series],
) -> Optional[dict]:
    """Fetch 6-month OHLCV + info for a single ticker, evaluate 13 rules."""
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

            hist = stock.history(period="6mo")
            if hist is None or hist.empty or len(hist) < 60:
                return None

            close = hist["Close"].values.astype(float)
            high = hist["High"].values.astype(float)
            low = hist["Low"].values.astype(float)
            open_ = hist["Open"].values.astype(float)
            volume = hist["Volume"].values.astype(float)

            # ── Rule Group A — Trend Stabilization ─────────────────────────
            sma50_series = pd.Series(close).rolling(50).mean()
            sma50_today = sma50_series.iloc[-1]
            sma50_10ago = sma50_series.iloc[-11] if len(sma50_series) >= 11 else None

            A1 = bool(
                sma50_today is not None
                and not pd.isna(sma50_today)
                and sma50_10ago is not None
                and not pd.isna(sma50_10ago)
                and sma50_today >= sma50_10ago
            )

            A2 = bool(
                sma50_today is not None
                and not pd.isna(sma50_today)
                and close[-1] >= sma50_today * 0.97
            )

            lowest_60 = float(np.min(low[-60:]))
            A3 = bool(close[-1] > lowest_60 * 1.10)

            # ── Rule Group B — Base Formation / Compression ────────────────
            hh20 = float(np.max(high[-20:]))
            ll20 = float(np.min(low[-20:]))
            B1 = bool(ll20 > 0 and (hh20 - ll20) / ll20 <= 0.15)

            atr14 = _compute_atr(high, low, close)
            B2 = bool(atr14 is not None and close[-1] > 0 and atr14 / close[-1] < 0.035)

            # B3: sideways — 15+ of last 25 closes in [LL25*1.03, HH25*0.97]
            hh25 = float(np.max(high[-25:]))
            ll25 = float(np.min(low[-25:]))
            band_lo = ll25 * 1.03
            band_hi = hh25 * 0.97
            if band_hi < band_lo:
                # Band inverted → extremely compressed, treat as True
                B3 = True
            else:
                last25_close = close[-25:]
                sideways_count = int(np.sum((last25_close >= band_lo) & (last25_close <= band_hi)))
                B3 = bool(sideways_count >= 15)

            # ── Rule Group C — Volume Accumulation ─────────────────────────
            last20_close = close[-20:]
            last20_open = open_[-20:]
            last20_vol = volume[-20:]

            up_mask = last20_close > last20_open
            down_mask = last20_close <= last20_open

            up_vols = last20_vol[up_mask]
            down_vols = last20_vol[down_mask]

            avg_up_vol = float(np.mean(up_vols)) if len(up_vols) > 0 else 0.0
            avg_down_vol = float(np.mean(down_vols)) if len(down_vols) > 0 else 0.0

            C1 = bool(avg_up_vol > 0 and avg_down_vol <= avg_up_vol * 0.85)

            sma_vol_20 = float(np.mean(volume[-20:])) if len(volume) >= 20 else 0.0

            # C2: 2+ bullish high-volume candles in last 10 bars
            last10_close = close[-10:]
            last10_open = open_[-10:]
            last10_vol = volume[-10:]
            bullish_hv = (last10_close > last10_open) & (last10_vol > sma_vol_20 * 1.4)
            bullish_hv_count = int(np.sum(bullish_hv))
            C2 = bool(bullish_hv_count >= 2)

            # C3: <=1 bearish high-volume candle in last 10 bars
            bearish_hv = (last10_close < last10_open) & (last10_vol > sma_vol_20 * 1.5)
            dist_count = int(np.sum(bearish_hv))
            C3 = bool(dist_count <= 1)

            # ── Rule Group D — Relative Strength ───────────────────────────
            D1 = False
            rs_current = None
            if benchmark_close is not None:
                try:
                    # Align dates via inner join
                    stock_close_s = hist["Close"]
                    aligned = pd.DataFrame({
                        "stock": stock_close_s,
                        "bench": benchmark_close,
                    }).dropna()
                    if len(aligned) >= 20:
                        rs = aligned["stock"] / aligned["bench"]
                        rs_sma20 = rs.rolling(20).mean()
                        rs_now = rs.iloc[-1]
                        rs_sma_now = rs_sma20.iloc[-1]
                        if not pd.isna(rs_now) and not pd.isna(rs_sma_now):
                            rs_current = float(rs_now)
                            D1 = bool(rs_now > rs_sma_now)
                except Exception:
                    pass

            # D2: 6+ of last 10 bars close above midpoint
            last10_high = high[-10:]
            last10_low = low[-10:]
            midpoints = (last10_high + last10_low) / 2
            above_mid_count = int(np.sum(last10_close > midpoints))
            D2 = bool(above_mid_count >= 6)

            # ── Rule Group E — Pre-Breakout ────────────────────────────────
            E1 = bool(close[-1] >= hh20 * 0.97)
            E2 = bool(close[-1] <= hh20 * 1.03)

            # ── Scoring & Signal ───────────────────────────────────────────
            rules = [A1, A2, A3, B1, B2, B3, C1, C2, C3, D1, D2, E1, E2]
            score = sum(rules)

            mandatory_pass = C1 and C2 and D1
            entry_trigger = bool(
                close[-1] > hh20
                and sma_vol_20 > 0
                and volume[-1] > sma_vol_20 * 1.5
            )

            if score >= 10 and mandatory_pass and entry_trigger:
                signal = "ACCUMULATION + BREAKOUT"
            elif score >= 10 and mandatory_pass:
                signal = "ACCUMULATION"
            elif score >= 7 and mandatory_pass:
                signal = "BUILDING"
            else:
                signal = "NEUTRAL"

            # ── Risk management values ─────────────────────────────────────
            stop_loss = float(np.min(low[-10:]))
            atr_stop = close[-1] - 2 * atr14 if atr14 else None
            entry_price = close[-1]
            risk = entry_price - stop_loss if stop_loss and stop_loss < entry_price else None
            target = entry_price + 3 * risk if risk and risk > 0 else None

            up_down_ratio = round(avg_up_vol / avg_down_vol, 2) if avg_down_vol > 0 else None
            sma50_display = round(float(sma50_today), 2) if sma50_today and not pd.isna(sma50_today) else None
            atr_price_pct = round(atr14 / close[-1] * 100, 2) if atr14 and close[-1] > 0 else None
            range_compression = round((hh20 - ll20) / ll20 * 100, 1) if ll20 > 0 else None

            return {
                "Signal": signal,
                "Ticker": ticker,
                "Name": info.get("shortName") or info.get("longName") or ticker,
                "Sector": info.get("sector") or "—",
                "Industry": info.get("industry") or "—",
                "Currency": info.get("currency", ""),
                "Price": round(close[-1], 2),
                "50-SMA": sma50_display,
                "ATR/Price %": atr_price_pct,
                "Range Compression %": range_compression,
                "Accum Score": score,
                "Up/Down Vol Ratio": up_down_ratio,
                "Rel Strength": round(rs_current, 4) if rs_current else None,
                "Bullish Vol Bars": bullish_hv_count,
                "Dist Bars": dist_count,
                "Trend Checks": f"{int(A1)+int(A2)+int(A3)}/3",
                "Base Checks": f"{int(B1)+int(B2)+int(B3)}/3",
                "Volume Checks": f"{int(C1)+int(C2)+int(C3)}/3",
                "RS Checks": f"{int(D1)+int(D2)}/2",
                "Breakout Checks": f"{int(E1)+int(E2)}/2",
                "Stop Loss": round(stop_loss, 2) if stop_loss else None,
                "ATR Stop": round(atr_stop, 2) if atr_stop else None,
                "Target": round(target, 2) if target else None,
                "Market Cap": _to_float(info.get("marketCap")) or 0,
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


def run_accumulation_strategy(
    tickers: List[str],
    benchmark_ticker: str = "^GSPC",
    min_score: int = 7,
    max_workers: int = 10,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Run the Accumulation Detection strategy on a list of tickers.

    Parameters
    ----------
    tickers          : list of ticker symbols
    benchmark_ticker : index ticker for relative strength calculation
    min_score        : minimum accumulation score (0-13) to include
    max_workers      : parallel fetch threads
    progress_cb      : optional callback(done, total) for progress updates

    Returns a DataFrame sorted by signal priority, then by Accum Score descending.
    """
    warmup()

    # Fetch benchmark once — read-only in worker threads
    benchmark_close = _fetch_benchmark(benchmark_ticker)

    rows: list = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 75

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(_fetch_accumulation_data, t, benchmark_close): t
            for t in tickers
        }
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None and result["Accum Score"] >= min_score:
                rows.append(result)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    _order = {
        "ACCUMULATION + BREAKOUT": 0,
        "ACCUMULATION": 1,
        "BUILDING": 2,
        "NEUTRAL": 3,
    }
    df["_sig_order"] = df["Signal"].map(_order)
    df = df.sort_values(["_sig_order", "Accum Score"], ascending=[True, False])
    df = df.drop(columns=["_sig_order"], errors="ignore")

    return df.reset_index(drop=True)

# Accumulation Detection Strategy — Implementation Plan

## Context

Add a third tab **"🔍 Accumulation Detection"** under Investment Strategies. This strategy detects stocks being quietly accumulated by institutional investors before a breakout, using a 13-rule scoring system across 5 rule groups.

---

## Files to Create/Modify

| File | Action | ~Lines |
|------|--------|--------|
| `src/strategy_accumulation.py` | **CREATE** | ~300 |
| `app.py` | **MODIFY** (import + 3rd tab) | ~150 added |

---

## File 1: `src/strategy_accumulation.py` (NEW)

### Structure (mirrors `strategy_breakout.py` exactly)

```
Imports (yfinance, numpy, pandas, ThreadPoolExecutor, yf_auth)
BENCHMARK_MAP dict (market code → index ticker)
_to_float(v) — safe float coercion
_fetch_benchmark(ticker, period="6mo") → Optional[pd.Series]
_fetch_accumulation_data(ticker, benchmark_close) → Optional[dict]
run_accumulation_strategy(tickers, benchmark_ticker, min_score, max_workers, progress_cb) → pd.DataFrame
```

### BENCHMARK_MAP

```python
{
    "US": "^GSPC", "IN_NSE": "^NSEI", "IN_BSE": "^BSESN", "GB": "^FTSE",
    "DE": "^GDAXI", "FR": "^FCHI", "JP": "^N225", "HK": "^HSI",
    "AU": "^AXJO", "CA": "^GSPTSE", "BR": "^BVSP", "SG": "^STI",
    "CH": "^SSMI", "KR": "^KS11", "NL": "^AEX", "ES": "^IBEX",
    "SE": "^OMX", "ZA": "^J203.JO",
}
```

### `_fetch_benchmark(ticker, period="6mo") → Optional[pd.Series]`

- Fetches index OHLCV, returns Close series indexed by date
- Called ONCE before parallel loop (read-only in worker threads)
- Uses rate_limit/rate_release + 3-attempt retry

### `_fetch_accumulation_data(ticker, benchmark_close) → Optional[dict]`

Per-ticker fetch function. Follows the exact retry/auth pattern from `_fetch_breakout_data`.

1. Fetch `yf.Ticker(ticker).info` + `.history(period="6mo")`
2. Require `len(hist) >= 60` bars, else return None
3. Extract numpy arrays: close, high, low, open_, volume
4. Compute all 13 rules:

**Rule Group A — Trend Stabilization:**
- A1: `SMA50_today >= SMA50_10_bars_ago` (50-SMA flat/rising)
- A2: `Close >= SMA50 * 0.97` (price near/above 50-SMA)
- A3: `Close > LowestLow(60) * 1.10` (10%+ above 60-day low)

**Rule Group B — Base Formation / Compression:**
- B1: `(HH20 - LL20) / LL20 <= 0.15` (range compression)
- B2: `ATR(14) / Close < 0.035` (volatility compression)
- B3: `15+ of 25 closes in [LL25*1.03, HH25*0.97]` (sideways behavior)
  - Edge case: if band inverts (HH25*0.97 < LL25*1.03), treat as True (extreme compression)

**Rule Group C — Volume Accumulation:**
- C1: `AvgDownVol(20) <= AvgUpVol(20) * 0.85` (up-volume dominance) **[MANDATORY]**
- C2: `2+ bullish high-vol candles in last 10 bars` (Close>Open, Vol>SMA_vol*1.4) **[MANDATORY]**
- C3: `<=1 bearish high-vol candle in last 10 bars` (no distribution cluster)
  - Guard: handle zero volume days

**Rule Group D — Relative Strength:**
- D1: `RS > SMA(RS, 20)` where RS = Close/BenchmarkClose **[MANDATORY]**
  - If benchmark unavailable → D1 = False (max score becomes 12)
  - Align stock/benchmark dates via inner join on index
- D2: `6+ of last 10 closes > (High+Low)/2` (strong closing)

**Rule Group E — Pre-Breakout:**
- E1: `Close >= HH20 * 0.97` (near 20-day high)
- E2: `Close <= HH20 * 1.03` (not overextended)

**Scoring & Signals:**
```
score = sum([A1..A3, B1..B3, C1..C3, D1, D2, E1, E2])  # 0-13
mandatory = C1 and C2 and D1
entry_trigger = Close > HH20 and Volume > SMA_vol_20 * 1.5

Signal:
  ACCUMULATION + BREAKOUT  →  score >= 10 AND mandatory AND entry_trigger
  ACCUMULATION             →  score >= 10 AND mandatory
  BUILDING                 →  score >= 7  AND mandatory
  NEUTRAL                  →  else
```

**ATR(14) computation:**
```python
tr = max(H-L, abs(H-prevC), abs(L-prevC))  # True Range
ATR = rolling_mean(tr, 14)
```

**Return dict columns:**
Signal, Ticker, Name, Sector, Industry, Currency, Price, 50-SMA, ATR/Price %, Range Compression %, Accum Score, Up/Down Vol Ratio, Rel Strength, Bullish Vol Bars, Dist Bars, Trend Checks (x/3), Base Checks (x/3), Volume Checks (x/3), RS Checks (x/2), Breakout Checks (x/2), Market Cap

### `run_accumulation_strategy(tickers, benchmark_ticker="^GSPC", min_score=7, max_workers=10, progress_cb=None) → pd.DataFrame`

1. `warmup()`
2. `benchmark_close = _fetch_benchmark(benchmark_ticker)` — single call
3. Parallel loop: `ThreadPoolExecutor` + `as_completed`, submit `_fetch_accumulation_data(t, benchmark_close)` per ticker
4. Collect non-None results, `refresh_crumb()` every 75 tickers
5. Build DataFrame, filter `score >= min_score`
6. Sort: signal priority (ACCUM+BREAKOUT > ACCUMULATION > BUILDING > NEUTRAL), then score desc
7. Return `df.reset_index(drop=True)`

---

## File 2: `app.py` (MODIFY)

### Change 1: Add import (line 13)
```python
from src.strategy_accumulation import run_accumulation_strategy, BENCHMARK_MAP
```

### Change 2: Expand tabs (line 807)
```python
tab_breakout, tab_value, tab_accum = st.tabs([
    "📈 Breakout Analyzer", "💰 Value Investing", "🔍 Accumulation Detection"
])
```

### Change 3: Add `with tab_accum:` block (after the `with tab_value:` block ends)

**Layout** (same 2-column pattern as breakout tab):

**Left config column:**
- Market multi-select (multiselect, same pattern)
- Benchmark text input (auto-populated from BENCHMARK_MAP based on first market)
- Min Accumulation Score slider (5–13, default 7)
- Market Cap filter selectbox
- Top N selectbox (20/50/100)
- Universe size caption
- Run Scan button

**Right results column:**
- Info banner explaining the 5 rule groups
- Before scan: signal table legend
- After scan (cached in `st.session_state["acc_cached_results"]`):
  - 4 metric cards: Candidates, Breakouts (🟢), Accumulating (🟡), Top Score
  - Signal emoji mapping: `ACCUMULATION + BREAKOUT` → 🟢, `ACCUMULATION` → 🟡, `BUILDING` → 🔵, `NEUTRAL` → ⬜
  - Main dataframe with column_config (ProgressColumn for score, NumberColumn for ratios)
  - Expander: "Rule Group Breakdown" showing per-group check counts
  - Caption explaining scoring system

---

## Data Flow

```
User clicks Run Scan
  → run_accumulation_strategy(universe, benchmark, min_score)
    → warmup()
    → _fetch_benchmark(benchmark) → pd.Series (once)
    → ThreadPool: _fetch_accumulation_data(ticker, benchmark_close) × N
      → yf.Ticker.info + .history(6mo)
      → compute 13 rules → score + signal
      → return dict or None
    → collect → DataFrame → filter → sort → return
  → cache in session_state
  → apply market cap filter → render
```

---

## Edge Cases & Guards

1. **Insufficient history** (<60 bars): return None, silently skip
2. **Benchmark unavailable**: D1 defaults to False, max score = 12
3. **B3 band inversion** (HH25*0.97 < LL25*1.03): treat as True (extreme compression)
4. **Zero volume days**: guard division by zero in avg_down_vol and sma_vol_20
5. **Multi-market benchmark**: use first market's default benchmark; user can override

---

## Verification

1. Run `python3 -m streamlit run app.py`
2. Select "Investment Strategies" from sidebar
3. Click "🔍 Accumulation Detection" tab
4. Select US market, run with defaults → should show results for US universe
5. Verify signal assignment logic: stocks with score >= 10 + mandatory checks → ACCUMULATION
6. Change benchmark to `^NSEI`, select India NSE → verify relative strength uses correct index
7. Adjust min score slider → results should filter accordingly
8. Verify market cap filter works

# Swedish Stock Investment Strategy — Implementation Plan

## Context

Add a fourth tab **"🇸🇪 Swedish Growth"** under Investment Strategies. This strategy screens Swedish/Nordic stocks for high-growth small-mid caps using 9 quantitative filters focused on the Nasdaq Stockholm market.

---

## Strategy Criteria

| # | Filter | Threshold |
|---|--------|-----------|
| 1 | Market Cap | 500M – 15B SEK |
| 2 | Revenue Growth | >= 20% YoY |
| 3 | Gross Margin | >= 40% |
| 4 | Revenue | >= 200M SEK |
| 5 | Operating Margin | Improving (current > previous year) |
| 6 | Price vs 52W High | >= 85% of 52-week high |
| 7 | 12-month Return vs OMX | Stock return > OMX Stockholm index return |
| 8 | Debt/Equity | < 1 (i.e., yfinance debtToEquity < 100) |
| 9 | Daily Liquidity | >= 5M SEK (avgVolume × price) |

**Benchmark:** `^OMX` (OMX Stockholm 30)

**Scoring:** Pass/fail on all 9 filters. Display which checks passed/failed plus fundamentals.

**Sorting:** By Revenue Growth descending (fastest growers first).

---

## Ticker Universe: Nordic North

Add a new `NORDIC_NORTH` universe in `src/screener.py` combining:
- Existing `UNIVERSES["SE"]` (147 Swedish tickers)
- Additional Nordic-listed growth/tech/healthcare companies on Nasdaq Stockholm

Also add a dedicated market entry or alias so the strategy can reference `"NORDIC_NORTH"` tickers.

---

## Files to Create/Modify

| File | Action | ~Lines |
|------|--------|--------|
| `src/strategy_swedish.py` | **CREATE** | ~250 |
| `src/screener.py` | **MODIFY** — add `NORDIC_NORTH` ticker list | ~20 added |
| `app.py` | **MODIFY** — import + 4th tab | ~120 added |

---

## File 1: `src/strategy_swedish.py` (NEW)

### Structure (mirrors `strategy_value.py`)

```
Imports (yfinance, numpy, pandas, ThreadPoolExecutor, yf_auth)
_to_float(v) — safe float coercion
_fetch_benchmark_return(ticker, period="1y") → Optional[float]  # 12-month return
_fetch_swedish_data(ticker, benchmark_return) → Optional[dict]
run_swedish_strategy(tickers, benchmark_ticker, max_workers, progress_cb) → pd.DataFrame
```

### `_fetch_benchmark_return(ticker="^OMX", period="1y") → Optional[float]`

- Fetch 1y history for OMX index
- Compute 12-month return: `(close[-1] - close[0]) / close[0]`
- Called ONCE before parallel loop
- Uses rate_limit/rate_release + 3-attempt retry

### `_fetch_swedish_data(ticker, benchmark_return) → Optional[dict]`

Per-ticker fetch function. Two API calls with semaphore release between them:

**Call 1: `.info`** — extract:
- Price, name, sector, industry, currency
- Market cap (yfinance reports in USD/local — convert check)
- Revenue growth (`revenueGrowth`)
- Gross margins (`grossMargins`)
- Total revenue (`totalRevenue`)
- Operating margins (`operatingMargins`)
- Previous year operating margins — approximated from `operatingMargins` and `earningsGrowth` trend, or treated as pass if not available from `.info` alone
- 52-week high (`fiftyTwoWeekHigh`)
- Debt/Equity (`debtToEquity`)
- Average volume (`averageVolume`) × price → daily liquidity

**Call 2: `.history(period="1y")`** — compute:
- 12-month stock return: `(close[-1] - close[0]) / close[0]`
- Compare vs benchmark_return
- Also extract operating margin trend from `.income_stmt` if available (release semaphore between calls)

**Call 3 (optional): `.income_stmt`** — for operating margin improvement:
- Compare latest year operating income margin vs prior year
- If unavailable, skip this check (mark as "N/A")

**Apply all 9 filters. Return dict with:**
- Ticker, Name, Sector, Industry, Currency, Price
- Market Cap (SEK), Revenue (SEK)
- Rev Growth %, Gross Margin %, Op Margin %, Op Margin Prev %
- Price/52W %, 12M Return %, OMX Return %
- D/E ratio, Daily Liquidity (M SEK)
- Checks Passed (x/9), individual check results
- Signal: STRONG BUY (9/9), BUY (7-8/9), WATCH (5-6/9), FAIL (<5)

### `run_swedish_strategy(tickers, benchmark_ticker="^OMX", max_workers=8, progress_cb=None) → pd.DataFrame`

1. `warmup()`
2. `benchmark_return = _fetch_benchmark_return(benchmark_ticker)` — single call
3. Parallel loop: submit `_fetch_swedish_data(t, benchmark_return)` per ticker
4. Collect results, `refresh_crumb()` every 75 tickers
5. Build DataFrame, sort by signal priority then Revenue Growth desc
6. Return `df.reset_index(drop=True)`

---

## File 2: `src/screener.py` (MODIFY)

### Add Nordic North universe after existing `UNIVERSES` dict:

```python
NORDIC_NORTH: List[str] = list(dict.fromkeys(
    UNIVERSES.get("SE", []) + [
        # Additional Nordic-listed growth companies on Nasdaq Stockholm
        ...extra tickers...
    ]
))
```

---

## File 3: `app.py` (MODIFY)

### Change 1: Add import
```python
from src.strategy_swedish import run_swedish_strategy
from src.screener import NORDIC_NORTH
```

### Change 2: Expand tabs
```python
tab_breakout, tab_value, tab_accum, tab_swedish = st.tabs([
    "📈 Breakout Analyzer", "💰 Value Investing",
    "🔍 Accumulation Detection", "🇸🇪 Swedish Growth"
])
```

### Change 3: Add `with tab_swedish:` block

**Layout** (same 2-column pattern):

**Left config column:**
- Universe info (Nordic North ticker count)
- Benchmark text input (default `^OMX`)
- Run Scan button

**Right results column:**
- Info banner explaining the 9 criteria
- Before scan: criteria table
- After scan:
  - 4 metric cards: Candidates, Strong Buy, Buy, Watch
  - Signal emoji mapping
  - Main dataframe with all metrics
  - Caption

---

## Data Flow

```
User clicks Run Scan
  → run_swedish_strategy(nordic_north_tickers, benchmark="^OMX")
    → warmup()
    → _fetch_benchmark_return("^OMX") → float (once)
    → ThreadPool: _fetch_swedish_data(ticker, benchmark_return) × N
      → yf.Ticker.info + .history(1y) + .income_stmt
      → apply 9 filters → score + signal
      → return dict or None
    → collect → DataFrame → sort → return
  → cache in session_state
  → render
```

---

## Edge Cases & Guards

1. **Currency conversion**: yfinance reports market cap and revenue in the stock's currency. Swedish stocks on .ST are in SEK — no conversion needed. Verify `info["currency"] == "SEK"`.
2. **Operating margin improvement**: requires income_stmt with 2+ years. If unavailable, mark check as N/A (don't penalize).
3. **Benchmark unavailable**: if ^OMX fetch fails, skip the relative return check.
4. **Low-liquidity stocks**: avgVolume may be 0 for very small caps — guard division.
5. **SEK thresholds**: Market cap 500M-15B SEK and Revenue >= 200M SEK are in SEK. Since .ST stocks report in SEK natively, no conversion needed.

---

## Verification

1. Run `python3 -m streamlit run app.py`
2. Select "Investment Strategies" from sidebar
3. Click "🇸🇪 Swedish Growth" tab
4. Click Run Scan → should process Nordic North universe
5. Verify filter thresholds match the 9 criteria
6. Check that OMX benchmark comparison works
7. Verify operating margin improvement uses income statement data

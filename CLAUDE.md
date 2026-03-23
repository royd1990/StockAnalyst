# CLAUDE.md — StockAnalyst AI

## Commands

```bash
# Install
pip3 install -r requirements.txt

# Run
python3 -m streamlit run app.py
```

Requires `OPENAI_API_KEY` in environment (or `.env` file via python-dotenv).

## Architecture

### Entry point
`app.py` — single Streamlit app with four sidebar page modes:
- **Stock Analysis** — single-ticker deep-dive (price chart, metrics, AI analysis, research)
- **Stock Screener** — multi-market fundamental screener with parallel fetching
- **Portfolio Analysis** — multi-stock portfolio review with AI commentary
- **Technical Strategy** — strategy scans (Breakout Analyzer, Value Investing)

### Modules (`src/`)
| File | Responsibility |
|---|---|
| `markets.py` | `MARKETS` dict — 17 world markets with yfinance suffixes, currency symbols, examples; `DEFAULT_MARKETS` list |
| `stock_data.py` | yfinance wrapper: `get_stock_data()`, `get_key_metrics()`, metric formatting, dividend yield fix |
| `analyst.py` | OpenAI GPT-4o streaming: `analyze_stock()`, `research_stock()`, `analyze_portfolio()` |
| `screener.py` | `UNIVERSES` dict (ticker lists per market), `screen_stocks()` parallel fetcher |
| `yf_auth.py` | Centralized yfinance crumb/cookie manager: `warmup()`, `refresh_crumb()`, `on_auth_error()` with generation-based coordinated refresh |
| `strategy_breakout.py` | `run_breakout_strategy()` — merged breakout analyzer (52W high + multibagger scoring) |
| `strategy_value.py` | `run_value_strategy()` — value investing strategy |
| `strategy_swedish.py` | `run_swedish_strategy()` — Swedish Growth strategy (9-filter Nordic small-mid cap screen) |
| `advanced_analyst.py` | `compute_advanced_metrics()`, `fetch_ownership_data()`, `traffic_light()` |

### Shared patterns
- **Parallel fetching**: `ThreadPoolExecutor` + `as_completed` for bulk yfinance calls (screener, strategies)
- **Streaming AI**: `client.responses.create(stream=True)` → generator yields `event.delta` chunks → `st.write_stream()` in app.py
- **Crumb management**: `src/yf_auth.py` provides centralized, generation-based coordinated crumb refresh — avoids thundering-herd on 401 errors
- **Safe float coercion**: `_to_float()` / `_safe_float()` guards against NaN/Inf from yfinance — used across screener, strategies, advanced_analyst

## Key conventions

- **AI model**: hardcoded `model="gpt-4o"` in `src/analyst.py` (three functions). Uses `web_search_preview` tool for real-time data.
- **Market suffixes**: yfinance tickers need exchange suffixes (e.g., `.NS` for India NSE, `.L` for London). Defined in `MARKETS` dict in `markets.py`.
- **Dividend yield**: yfinance `dividendYield` is unreliable — computed from `dividendRate / currentPrice` when available (see `stock_data.py`).
- **Charts**: Plotly with `plotly_dark` template, primary accent `#00D4AA`.
- **No tests or linting** configured.

## Deploy (Streamlit Cloud)

1. Push repo to GitHub
2. share.streamlit.io → New app → select repo → `app.py`
3. Settings → Secrets → `OPENAI_API_KEY = "sk-..."`

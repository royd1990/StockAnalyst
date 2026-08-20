# 📈 StockAnalyst AI

A Streamlit app for fundamental stock analysis, screening, and valuation across 17 world markets — combining live [yfinance](https://github.com/ranaroussi/yfinance) data with GPT-4o's real-time web search for AI-generated commentary.

## Features

- **Stock Analysis** — single-ticker deep-dive: price chart, key metrics, AI analysis, AI research, advanced fundamentals (ownership, quality signals)
- **Stock Screener** — parallel fundamental screener across multiple markets/universes
- **Portfolio Analysis** — multi-stock portfolio review with AI commentary
- **Investment Strategies**:
  - 📈 Breakout Analyzer — 52-week high + multibagger scoring
  - 💰 Value Investing — classic value screen
  - 🔍 Accumulation Detection — 13-rule pre-breakout scoring
  - 🇸🇪 Swedish Growth — 9-filter Nordic small/mid-cap screen
  - 📊 Fundamental & Valuation — quality/growth screen, DCF, relative valuation (EV/EBITDA, P/E, EV/Sales), and peer comparison

## Tech Stack

- **UI**: [Streamlit](https://streamlit.io/)
- **AI**: OpenAI GPT-4o (`client.responses.create`, streamed) with the `web_search_preview` tool
- **Market data**: `yfinance`, with a centralized crumb/cookie auth manager for reliability
- **Charts**: Plotly (dark theme)

## Setup

```bash
pip3 install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY
python3 -m streamlit run app.py
```

Requires an `OPENAI_API_KEY` (env var or `.env` file).

## Project Structure

```
app.py                        # Streamlit entry point (all page modes)
src/
  markets.py                  # World markets + yfinance ticker suffixes
  stock_data.py                # yfinance wrapper, key metrics
  analyst.py                  # GPT-4o streaming: analysis, research, portfolio commentary
  screener.py                  # Ticker universes + parallel screener
  advanced_analyst.py          # Advanced metrics, ownership data
  peer_analysis.py             # Peer discovery + comparison tables
  valuation_engine.py          # DCF and relative valuation models (pure computation)
  strategy_breakout.py         # Breakout Analyzer strategy
  strategy_value.py            # Value Investing strategy
  strategy_accumulation.py     # Accumulation Detection strategy
  strategy_swedish.py          # Swedish Growth strategy
  strategy_fundamental.py      # Fundamental & Valuation quality/growth screen
  yf_auth.py                   # Centralized yfinance crumb/cookie manager
```

## Deploy (Streamlit Cloud)

1. Push this repo to GitHub
2. [share.streamlit.io](https://share.streamlit.io) → New app → select repo → `app.py`
3. Settings → Secrets → add `OPENAI_API_KEY = "sk-..."`

## Disclaimer

Data is sourced from Yahoo Finance and AI-generated commentary uses web search. For informational purposes only — not financial advice.

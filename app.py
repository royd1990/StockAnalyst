import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from src.analyst import analyze_stock
from src.markets import DEFAULT_MARKETS, MARKETS
from src.stock_data import (
    get_key_metrics,
    get_stock_data,
)

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StockAnalyst AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* Hide default Streamlit footer */
#MainMenu, footer { visibility: hidden; }

/* ── Stock header card ── */
.stock-header {
    background: linear-gradient(135deg, rgba(0,212,170,0.12) 0%, rgba(15,20,35,0.9) 100%);
    border: 1px solid rgba(0,212,170,0.35);
    border-radius: 14px;
    padding: 24px 32px;
    margin-bottom: 28px;
}
.stock-name   { font-size: 1.9rem; font-weight: 750; color: #fff; }
.stock-ticker { font-size: 1rem; color: rgba(255,255,255,0.45); margin-left: 10px; }
.stock-meta   { color: rgba(255,255,255,0.5); font-size: 0.85rem; margin-top: 4px; }
.stock-price  { font-size: 2.6rem; font-weight: 700; color: #fff; }
.price-up     { color: #00D4AA; font-size: 1.1rem; font-weight: 600; }
.price-down   { color: #FF6B6B; font-size: 1.1rem; font-weight: 600; }

/* ── Metric card ── */
.metric-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    padding: 13px 16px;
    margin-bottom: 10px;
    transition: border-color 0.2s;
}
.metric-card:hover { border-color: rgba(0,212,170,0.4); }
.metric-label {
    font-size: 0.70rem;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.metric-value {
    font-size: 1.05rem;
    font-weight: 650;
    color: #e8eaf6;
    margin-top: 3px;
}

/* ── Section label ── */
.section-label {
    font-size: 0.78rem;
    font-weight: 700;
    color: #00D4AA;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding-bottom: 8px;
    margin-top: 8px;
    border-bottom: 1px solid rgba(0,212,170,0.25);
    margin-bottom: 10px;
}

/* ── Info banner ── */
.info-banner {
    background: rgba(0,153,255,0.1);
    border: 1px solid rgba(0,153,255,0.3);
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 0.88rem;
    color: rgba(255,255,255,0.85);
    margin-bottom: 18px;
    line-height: 1.5;
}

/* ── Sidebar styling ── */
[data-testid="stSidebar"] { background: rgba(10,14,23,0.95); }
</style>
""",
    unsafe_allow_html=True,
)


# ── Helper renderers ──────────────────────────────────────────────────────────
def metric_card(label: str, value: str) -> None:
    st.markdown(
        f"""<div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_metrics_grid(metrics: dict) -> None:
    for category, items in metrics.items():
        st.markdown(f'<div class="section-label">{category}</div>', unsafe_allow_html=True)
        pairs = [(k, v) for k, v in items.items()]
        cols_per_row = 4
        for i in range(0, len(pairs), cols_per_row):
            row = pairs[i : i + cols_per_row]
            cols = st.columns(len(row))
            for col, (label, value) in zip(cols, row):
                with col:
                    metric_card(label, value)
        st.write("")


def create_price_chart(history: pd.DataFrame, ticker: str, symbol: str) -> go.Figure:
    fig = go.Figure()

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=history.index,
            open=history["Open"],
            high=history["High"],
            low=history["Low"],
            close=history["Close"],
            name="Price",
            increasing_line_color="#00D4AA",
            decreasing_line_color="#FF6B6B",
            increasing_fillcolor="rgba(0,212,170,0.25)",
            decreasing_fillcolor="rgba(255,107,107,0.25)",
        )
    )

    # Volume bars (secondary y-axis)
    bar_colors = [
        "#00D4AA" if c >= o else "#FF6B6B"
        for c, o in zip(history["Close"], history["Open"])
    ]
    fig.add_trace(
        go.Bar(
            x=history.index,
            y=history["Volume"],
            name="Volume",
            marker_color=bar_colors,
            opacity=0.40,
            yaxis="y2",
        )
    )

    fig.update_layout(
        title=f"{ticker} — 1-Year Price History",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=460,
        showlegend=False,
        xaxis=dict(rangeslider=dict(visible=False), gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(
            title=f"Price ({symbol})",
            gridcolor="rgba(255,255,255,0.05)",
            side="right",
        ),
        yaxis2=dict(
            overlaying="y",
            side="left",
            showgrid=False,
            range=[0, history["Volume"].max() * 6],
            title="Volume",
        ),
        margin=dict(l=0, r=0, t=45, b=0),
    )
    return fig


def create_financials_chart(income_stmt: pd.DataFrame, symbol: str) -> "go.Figure | None":
    if income_stmt is None or income_stmt.empty:
        return None

    revenue_row = net_income_row = None
    for idx in income_stmt.index:
        idx_lower = str(idx).lower()
        if "total revenue" in idx_lower or idx_lower == "revenue":
            revenue_row = income_stmt.loc[idx]
        elif "net income" in idx_lower and "minority" not in idx_lower and net_income_row is None:
            net_income_row = income_stmt.loc[idx]

    if revenue_row is None and net_income_row is None:
        return None

    fig = go.Figure()

    def add_bar(row, name, color, opacity=0.85):
        dates = [str(d)[:4] for d in row.index]
        vals = [v / 1e9 if v == v else 0 for v in row.values]  # NaN guard
        colors = [color if v >= 0 else "#FF6B6B" for v in vals]
        fig.add_trace(
            go.Bar(x=dates, y=vals, name=name, marker_color=colors, opacity=opacity)
        )

    if revenue_row is not None:
        add_bar(revenue_row, "Revenue", "rgba(0,212,170,0.85)")
    if net_income_row is not None:
        add_bar(net_income_row, "Net Income", "rgba(0,153,255,0.75)", opacity=0.75)

    fig.update_layout(
        title=f"Annual Revenue & Net Income ({symbol}B)",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=360,
        barmode="group",
        yaxis=dict(title=f"{symbol}B", gridcolor="rgba(255,255,255,0.05)"),
        legend=dict(orientation="h", y=1.12),
        margin=dict(l=0, r=0, t=50, b=0),
    )
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<h2 style='margin-bottom:4px;'>⚙️ Configuration</h2>",
        unsafe_allow_html=True,
    )

    api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-...",
        value=os.getenv("OPENAI_API_KEY", ""),
        help="Get yours at platform.openai.com",
    )
    if api_key:
        st.success("✅ API key configured", icon="🔑")
    else:
        st.warning("Enter API key to enable AI analysis")

    st.divider()

    st.markdown("<h3 style='margin-bottom:6px;'>🌍 World Markets</h3>", unsafe_allow_html=True)
    st.caption("Select the markets you want to analyse stocks from.")

    selected_markets = st.multiselect(
        "Active markets",
        options=list(MARKETS.keys()),
        default=DEFAULT_MARKETS,
        label_visibility="collapsed",
    )
    if not selected_markets:
        selected_markets = list(MARKETS.keys())

    st.divider()

    st.markdown(
        """<div style='font-size:0.78rem; color:rgba(255,255,255,0.45); line-height:1.6'>
        <b>StockAnalyst AI</b><br>
        Powered by <b>GPT-4o</b> with real-time web search.<br><br>
        Data sourced from Yahoo Finance. For informational purposes only — not financial advice.
        </div>""",
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown(
        """<div style='font-size:0.75rem; color:rgba(255,255,255,0.35)'>
        🚀 Deploy free on <b>Streamlit Cloud</b><br>
        Set <code>OPENAI_API_KEY</code> in Secrets.
        </div>""",
        unsafe_allow_html=True,
    )


# ── Page header ───────────────────────────────────────────────────────────────
st.markdown(
    """<div style='text-align:center; padding:18px 0 6px;'>
    <h1 style='font-size:2.6rem; font-weight:800;
        background:linear-gradient(135deg,#00D4AA,#0099FF);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        margin-bottom:6px;'>
        📈 StockAnalyst AI
    </h1>
    <p style='color:rgba(255,255,255,0.55); font-size:1.05rem; margin:0;'>
        Comprehensive fundamental analysis powered by GPT-4o with real-time web search
    </p>
</div>""",
    unsafe_allow_html=True,
)

st.write("")

# ── Search bar ────────────────────────────────────────────────────────────────
col_ticker, col_market, col_btn = st.columns([3, 3, 1])

with col_ticker:
    ticker_input = st.text_input(
        "Stock ticker",
        placeholder="e.g. AAPL, RELIANCE, ASML …",
        label_visibility="collapsed",
    )

with col_market:
    market_choice = st.selectbox(
        "Market",
        options=selected_markets,
        label_visibility="collapsed",
    )

with col_btn:
    analyze_btn = st.button("Analyze →", type="primary", use_container_width=True)

# Ticker format hint
if market_choice:
    minfo = MARKETS[market_choice]
    suffix = minfo["suffix"]
    examples = minfo["examples"]
    suffix_display = f"`{suffix}`" if suffix else "*(no suffix)*"
    st.caption(
        f"**{minfo['description']}** — Suffix {suffix_display} is added automatically.  "
        f"Examples: `{'`, `'.join(examples[:4])}`"
    )

st.divider()

# ── Main analysis flow ────────────────────────────────────────────────────────
if analyze_btn:
    if not ticker_input.strip():
        st.warning("⚠️ Please enter a stock ticker symbol.")
        st.stop()

    minfo = MARKETS[market_choice]
    full_ticker = ticker_input.strip().upper() + minfo["suffix"]
    symbol = minfo["symbol"]

    # 1. Fetch stock data
    with st.spinner(f"Fetching market data for **{full_ticker}** …"):
        stock_data = get_stock_data(full_ticker)

    if not stock_data:
        st.error(
            f"❌ Could not find data for `{full_ticker}`. "
            "Please verify the ticker symbol and market selection."
        )
        st.info(
            "💡 **Tip:** Make sure the ticker is correct for the chosen exchange. "
            f"For {minfo['description']}, try: `{'`, `'.join(minfo['examples'][:3])}`"
        )
        st.stop()

    info = stock_data["info"]
    company_name = info.get("longName") or info.get("shortName") or full_ticker
    current_price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
        or 0.0
    )
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or current_price
    price_change = current_price - prev_close
    pct_change = (price_change / prev_close * 100) if prev_close else 0.0
    change_class = "price-up" if price_change >= 0 else "price-down"
    change_sign = "+" if price_change >= 0 else ""

    sector = info.get("sector", "")
    industry = info.get("industry", "")
    exchange = info.get("exchange", "")
    country = info.get("country", "")

    meta_parts = [p for p in [sector, industry, exchange, country] if p]
    meta_str = " · ".join(meta_parts)

    # ── Stock header ──────────────────────────────────────────────────────────
    st.markdown(
        f"""<div class="stock-header">
            <div style='display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px;'>
                <div>
                    <span class="stock-name">{company_name}</span>
                    <span class="stock-ticker">{full_ticker}</span>
                    <br>
                    <span class="stock-meta">{meta_str}</span>
                </div>
                <div style='text-align:right;'>
                    <div class="stock-price">{symbol}{current_price:,.2f}</div>
                    <div class="{change_class}">
                        {change_sign}{price_change:.2f} &nbsp;({change_sign}{pct_change:.2f}%)
                    </div>
                    <div style='font-size:0.78rem; color:rgba(255,255,255,0.35); margin-top:4px;'>
                        vs. prev. close
                    </div>
                </div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_fund, tab_ai, tab_charts = st.tabs(
        ["📊  Fundamentals", "🤖  AI Analysis", "📈  Charts"]
    )

    key_metrics = get_key_metrics(info, symbol)

    # ── Tab 1: Fundamentals ───────────────────────────────────────────────────
    with tab_fund:
        render_metrics_grid(key_metrics)

        desc = info.get("longBusinessSummary", "")
        if desc:
            with st.expander("📝 Company Description", expanded=False):
                st.write(desc)

        # Analyst recommendations summary
        rec = info.get("recommendationKey", "")
        target = info.get("targetMeanPrice")
        num_analysts = info.get("numberOfAnalystOpinions")
        if rec or target:
            st.markdown(
                '<div class="section-label">Analyst Consensus</div>',
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                rec_display = rec.upper().replace("_", " ") if rec else "N/A"
                color = {"BUY": "#00D4AA", "STRONG BUY": "#00D4AA", "HOLD": "#FFA500",
                         "UNDERPERFORM": "#FF6B6B", "SELL": "#FF6B6B"}.get(rec_display, "#aaa")
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-label'>Consensus Rating</div>"
                    f"<div class='metric-value' style='color:{color}'>{rec_display}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                metric_card("Mean Target Price", f"{symbol}{target:.2f}" if target else "N/A")
            with c3:
                metric_card("# Analyst Opinions", str(num_analysts) if num_analysts else "N/A")

    # ── Tab 2: AI Analysis ────────────────────────────────────────────────────
    with tab_ai:
        if not api_key:
            st.warning(
                "⚠️ **API key required.** "
                "Enter your OpenAI API key in the sidebar to unlock AI-powered analysis."
            )
        else:
            st.markdown(
                """<div class="info-banner">
                🤖 <b>GPT-4o</b> is searching the web for the latest news, earnings reports,
                analyst opinions, and competitive data. Streaming analysis will appear below as it is generated.
                This typically takes <b>20–45 seconds</b>.
                </div>""",
                unsafe_allow_html=True,
            )

            sector_str = " — ".join(p for p in [sector, industry] if p) or "N/A"
            # Filter out N/A entries for the AI prompt
            clean_metrics = {
                cat: {k: v for k, v in items.items() if v != "N/A"}
                for cat, items in key_metrics.items()
                if any(v != "N/A" for v in items.values())
            }

            st.write_stream(
                analyze_stock(
                    ticker=full_ticker,
                    company_name=company_name,
                    sector=sector_str,
                    market_name=market_choice,
                    metrics=clean_metrics,
                    api_key=api_key,
                )
            )

    # ── Tab 3: Charts ─────────────────────────────────────────────────────────
    with tab_charts:
        history = stock_data.get("history", pd.DataFrame())
        income_stmt = stock_data.get("income_stmt", pd.DataFrame())

        if not history.empty:
            st.plotly_chart(
                create_price_chart(history, full_ticker, symbol),
                use_container_width=True,
            )
        else:
            st.info("📭 Price history not available for this ticker.")

        fin_fig = create_financials_chart(income_stmt, symbol)
        if fin_fig:
            st.plotly_chart(fin_fig, use_container_width=True)
        elif not income_stmt.empty:
            st.info("📭 Could not parse financial statement data for charting.")
        else:
            st.info(
                "📭 Annual financial statements not available. "
                "This is common for non-US listed stocks on Yahoo Finance."
            )

        # 52-week range visualisation
        high_52 = info.get("fiftyTwoWeekHigh")
        low_52 = info.get("fiftyTwoWeekLow")
        if high_52 and low_52 and current_price:
            st.markdown(
                '<div class="section-label" style="margin-top:16px;">52-Week Range</div>',
                unsafe_allow_html=True,
            )
            range_pct = (current_price - low_52) / (high_52 - low_52) * 100 if high_52 != low_52 else 50
            c1, c2, c3 = st.columns([1, 4, 1])
            with c1:
                st.markdown(
                    f"<div style='text-align:right; color:#FF6B6B; font-weight:600; padding-top:8px;'>"
                    f"{symbol}{low_52:,.2f}</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f"""<div style='padding:10px 0;'>
                    <div style='background:rgba(255,255,255,0.1); border-radius:6px; height:10px; position:relative;'>
                        <div style='
                            background:linear-gradient(90deg,#FF6B6B,#FFA500,#00D4AA);
                            width:{range_pct:.1f}%; height:100%; border-radius:6px;'></div>
                        <div style='
                            position:absolute; top:-4px;
                            left:calc({range_pct:.1f}% - 6px);
                            width:12px; height:18px;
                            background:#fff; border-radius:3px;'></div>
                    </div>
                    <div style='text-align:center; margin-top:6px; font-size:0.8rem; color:rgba(255,255,255,0.5);'>
                        Current: {symbol}{current_price:,.2f} — {range_pct:.1f}% of 52W range
                    </div></div>""",
                    unsafe_allow_html=True,
                )
            with c3:
                st.markdown(
                    f"<div style='color:#00D4AA; font-weight:600; padding-top:8px;'>"
                    f"{symbol}{high_52:,.2f}</div>",
                    unsafe_allow_html=True,
                )

elif not analyze_btn:
    # Landing state — show featured markets
    st.markdown(
        "<div style='text-align:center; color:rgba(255,255,255,0.4); margin-top:10px;'>"
        "Enter a stock ticker above and click <b>Analyze →</b> to get started."
        "</div>",
        unsafe_allow_html=True,
    )
    st.write("")

    cols = st.columns(4)
    showcases = [
        ("🇺🇸", "AAPL", "Apple Inc.", "NYSE/NASDAQ"),
        ("🇮🇳", "RELIANCE.NS", "Reliance Industries", "NSE India"),
        ("🇩🇪", "SAP.DE", "SAP SE", "XETRA"),
        ("🇬🇧", "SHEL.L", "Shell plc", "LSE"),
    ]
    for col, (flag, ticker, name, exch) in zip(cols, showcases):
        with col:
            st.markdown(
                f"""<div class='metric-card' style='text-align:center; padding:20px;'>
                    <div style='font-size:2rem;'>{flag}</div>
                    <div style='font-weight:700; margin-top:8px;'>{ticker}</div>
                    <div style='font-size:0.8rem; color:rgba(255,255,255,0.5);'>{name}</div>
                    <div style='font-size:0.72rem; color:#00D4AA; margin-top:4px;'>{exch}</div>
                </div>""",
                unsafe_allow_html=True,
            )

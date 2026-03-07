import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from src.advanced_analyst import compute_advanced_metrics, fetch_ownership_data, traffic_light
from src.analyst import analyze_portfolio, analyze_stock, research_stock
from src.markets import DEFAULT_MARKETS, MARKETS
from src.screener import UNIVERSES, get_universe_for_markets, screen_stocks
from src.strategy_52w import run_52w_high_strategy
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


# ── Portfolio renderer ────────────────────────────────────────────────────────

_CURRENCY_SYMBOLS = {
    "USD": "$", "GBP": "£", "EUR": "€", "INR": "₹", "JPY": "¥",
    "HKD": "HK$", "AUD": "A$", "CAD": "C$", "BRL": "R$",
    "SGD": "S$", "CHF": "CHF ", "KRW": "₩", "ZAR": "R",
}


def _portfolio_checklist(adv: dict) -> tuple:
    """Return (passed, total, checks) using only locally-computable conditions."""
    checks = []

    pe = adv.get("pe")
    checks.append(("P/E < 20", (pe < 20) if pe is not None else None,
                   f"P/E: {pe:.1f}x" if pe is not None else "N/A"))

    pb = adv.get("pb")
    checks.append(("P/B < 3", (pb < 3) if pb is not None else None,
                   f"P/B: {pb:.2f}x" if pb is not None else "N/A"))

    de = adv.get("de_ratio")
    checks.append(("D/E < 1", (de < 1.0) if de is not None else None,
                   f"D/E: {de:.2f}x" if de is not None else "N/A"))

    cr = adv.get("current_ratio")
    checks.append(("Current Ratio > 1", (cr > 1.0) if cr is not None else None,
                   f"CR: {cr:.2f}x" if cr is not None else "N/A"))

    rev_g = adv.get("rev_growth")
    checks.append(("Revenue Growing", (rev_g > 0) if rev_g is not None else None,
                   f"{rev_g * 100:.1f}% YoY" if rev_g is not None else "N/A"))

    roe = adv.get("roe")
    checks.append(("ROE > 15%", (roe > 0.15) if roe is not None else None,
                   f"ROE: {roe * 100:.1f}%" if roe is not None else "N/A"))

    both_growing = (
        adv.get("net_profit_increasing") and adv.get("ebitda_increasing")
        if adv.get("net_profit_increasing") is not None and adv.get("ebitda_increasing") is not None
        else None
    )
    checks.append(("Profit & EBITDA Growing", both_growing,
                   f"NP: {'↑' if adv.get('net_profit_increasing') else '↓' if adv.get('net_profit_increasing') is False else '?'}  "
                   f"EBITDA: {'↑' if adv.get('ebitda_increasing') else '↓' if adv.get('ebitda_increasing') is False else '?'}"))

    checks.append(("Op. Cash Flow Increasing", adv.get("cashflow_increasing"),
                   "Based on last 3 years"))

    passed = sum(1 for _, p, _ in checks if p is True)
    total = sum(1 for _, p, _ in checks if p is not None)
    return passed, total, checks


def _render_portfolio(api_key: str) -> None:
    st.markdown(
        "<div class='section-label' style='font-size:1.3rem;'>📁 Portfolio Analysis</div>",
        unsafe_allow_html=True,
    )

    # ── Stock builder ──────────────────────────────────────────────────────────
    st.markdown("#### Build Your Portfolio")
    st.caption("Add stocks one at a time from any market. Up to 15 stocks.")

    if "ptf_list" not in st.session_state:
        st.session_state["ptf_list"] = []  # list of (full_ticker, market_name, display_name)

    col_t, col_m, col_add = st.columns([2, 2, 1])
    with col_t:
        new_ticker = st.text_input(
            "Ticker", placeholder="e.g. AAPL, RELIANCE, SAP …",
            key="ptf_ticker_input", label_visibility="collapsed",
        )
    with col_m:
        new_market = st.selectbox(
            "Market", options=list(MARKETS.keys()),
            key="ptf_market_input", label_visibility="collapsed",
        )
    with col_add:
        add_btn = st.button("＋ Add Stock", use_container_width=True)

    if new_market:
        minfo = MARKETS[new_market]
        suffix_display = f"`{minfo['suffix']}`" if minfo["suffix"] else "*(no suffix)*"
        st.caption(
            f"**{minfo['description']}** — suffix {suffix_display} added automatically.  "
            f"Examples: `{'`, `'.join(minfo['examples'][:3])}`"
        )

    if add_btn and new_ticker.strip():
        minfo = MARKETS[new_market]
        full_ticker = new_ticker.strip().upper() + minfo["suffix"]
        existing = [ft for ft, _, _ in st.session_state["ptf_list"]]
        if len(existing) >= 15:
            st.warning("Maximum 15 stocks reached.")
        elif full_ticker in existing:
            st.warning(f"{full_ticker} is already in the portfolio.")
        else:
            st.session_state["ptf_list"].append(
                (full_ticker, new_market, new_ticker.strip().upper())
            )
            st.rerun()

    # Current portfolio list
    if st.session_state["ptf_list"]:
        st.markdown("**Current portfolio:**")
        items = st.session_state["ptf_list"]
        cols_per_row = 5
        for row_start in range(0, len(items), cols_per_row):
            row_items = items[row_start: row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for j, (full_t, mkt, _) in enumerate(row_items):
                with cols[j]:
                    st.markdown(
                        f"<div class='metric-card' style='text-align:center; padding:10px;'>"
                        f"<div style='font-weight:700; font-size:0.95rem;'>{full_t}</div>"
                        f"<div style='font-size:0.72rem; color:#00D4AA; margin-top:2px;'>{mkt}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    if st.button("✕ Remove", key=f"rm_{full_t}", use_container_width=True):
                        st.session_state["ptf_list"] = [
                            x for x in st.session_state["ptf_list"] if x[0] != full_t
                        ]
                        st.session_state.pop("portfolio_stocks", None)
                        st.rerun()

        st.write("")
        col_load, col_clear = st.columns([3, 1])
        with col_load:
            load_btn = st.button("▶  Load Portfolio Data", type="primary", use_container_width=True)
        with col_clear:
            if st.button("🗑 Clear All", use_container_width=True):
                st.session_state["ptf_list"] = []
                st.session_state.pop("portfolio_stocks", None)
                st.rerun()
    else:
        st.info("Add at least one stock above to get started.")
        load_btn = False

    # ── Fetch data ─────────────────────────────────────────────────────────────
    if load_btn:
        tickers_to_fetch = [ft for ft, _, _ in st.session_state["ptf_list"]]
        portfolio_stocks = []
        failed = []
        prog = st.progress(0.0)
        prog_txt = st.empty()

        for i, (full_ticker, market_name, _) in enumerate(st.session_state["ptf_list"]):
            prog_txt.caption(f"Fetching {full_ticker} ({i + 1}/{len(tickers_to_fetch)})…")
            data = get_stock_data(full_ticker)
            prog.progress((i + 1) / len(tickers_to_fetch))
            if not data:
                failed.append(full_ticker)
                continue

            info = data["info"]
            adv = compute_advanced_metrics(data)
            sym = _CURRENCY_SYMBOLS.get(info.get("currency", "USD"), "$")

            company_name = info.get("longName") or info.get("shortName") or full_ticker
            sector   = info.get("sector", "")
            industry = info.get("industry", "")
            country  = info.get("country", "")

            current_price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("previousClose")
                or 0.0
            )
            prev_close  = info.get("previousClose") or info.get("regularMarketPreviousClose") or current_price
            price_change = current_price - prev_close
            pct_change   = (price_change / prev_close * 100) if prev_close else 0.0

            rec          = (info.get("recommendationKey") or "").upper().replace("_", " ")
            target_mean  = info.get("targetMeanPrice")
            target_high  = info.get("targetHighPrice")
            target_low   = info.get("targetLowPrice")
            num_analysts = info.get("numberOfAnalystOpinions") or 0
            upside_pct   = ((target_mean - current_price) / current_price * 100) if target_mean and current_price else None

            passed, total, checks = _portfolio_checklist(adv)

            parts = []
            if adv.get("pe"):   parts.append(f"P/E {adv['pe']:.1f}x")
            if adv.get("pb"):   parts.append(f"P/B {adv['pb']:.2f}x")
            if adv.get("roe"):  parts.append(f"ROE {adv['roe']*100:.1f}%")
            if adv.get("de_ratio"): parts.append(f"D/E {adv['de_ratio']:.2f}x")
            if adv.get("rev_growth"): parts.append(f"RevGr {adv['rev_growth']*100:.1f}%")
            metrics_summary = " | ".join(parts)

            portfolio_stocks.append({
                "ticker":        full_ticker,
                "company_name":  company_name,
                "sector":        f"{sector} — {industry}".strip(" —") or "N/A",
                "country":       country or "N/A",
                "market_name":   market_name,
                "sym":           sym,
                "current_price_raw": current_price,
                "current_price": f"{sym}{current_price:,.2f}",
                "price_change":  price_change,
                "pct_change":    pct_change,
                "rec":           rec or "N/A",
                "target_mean":   target_mean,
                "target_price":  f"{sym}{target_mean:.2f}" if target_mean else "N/A",
                "target_high":   f"{sym}{target_high:.2f}" if target_high else "N/A",
                "target_low":    f"{sym}{target_low:.2f}"  if target_low  else "N/A",
                "upside_pct":    upside_pct,
                "num_analysts":  num_analysts,
                "passed":        passed,
                "total":         total,
                "checks":        checks,
                "metrics_summary": metrics_summary,
            })

        prog.empty()
        prog_txt.empty()

        if failed:
            st.warning(f"Could not fetch data for: {', '.join(failed)}")
        if not portfolio_stocks:
            st.error("No valid stock data found. Check the ticker symbols.")
            return

        st.session_state["portfolio_stocks"] = portfolio_stocks

    stocks = st.session_state.get("portfolio_stocks", [])
    if not stocks:
        return

    st.divider()

    # ── Summary Table ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Portfolio Summary</div>', unsafe_allow_html=True)

    summary_rows = []
    for s in stocks:
        upside_str = f"{s['upside_pct']:+.1f}%" if s["upside_pct"] is not None else "N/A"
        score_emoji = "🟢" if s["passed"] >= 6 else "🟡" if s["passed"] >= 4 else "🔴"
        rec_emoji   = {"BUY": "🟢", "STRONG BUY": "🟢", "HOLD": "🟡",
                       "UNDERPERFORM": "🔴", "SELL": "🔴"}.get(s["rec"], "⚪")
        summary_rows.append({
            "Ticker":        s["ticker"],
            "Company":       s["company_name"],
            "Country":       s["country"],
            "Price":         s["current_price"],
            "Day Chg":       f"{'+' if s['price_change'] >= 0 else ''}{s['pct_change']:.2f}%",
            "Analyst":       f"{rec_emoji} {s['rec']}",
            "Target Low":    s["target_low"],
            "Target Mean":   s["target_price"],
            "Target High":   s["target_high"],
            "Upside":        upside_str,
            "# Analysts":    s["num_analysts"] or "N/A",
            "Fund. Score":   f"{score_emoji} {s['passed']}/{s['total']}",
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.write("")

    # ── Per-Stock Detail Cards ─────────────────────────────────────────────────
    st.markdown(
        '<div class="section-label">Analyst Targets & Fundamental Conditions</div>',
        unsafe_allow_html=True,
    )

    for s in stocks:
        rec_color = {"BUY": "#00D4AA", "STRONG BUY": "#00D4AA", "HOLD": "#FFA500",
                     "UNDERPERFORM": "#FF6B6B", "SELL": "#FF6B6B"}.get(s["rec"], "#aaa")
        upside_str   = f"{s['upside_pct']:+.1f}%" if s["upside_pct"] is not None else "N/A"
        upside_color = "#00D4AA" if (s["upside_pct"] or 0) >= 0 else "#FF6B6B"
        score_color  = "#00D4AA" if s["passed"] >= 6 else "#FFA500" if s["passed"] >= 4 else "#FF6B6B"

        with st.expander(
            f"**{s['ticker']}** — {s['company_name']}  ·  {s['current_price']}"
            f"  ·  {s['rec']}  ·  Target {s['target_price']}  ·  Score {s['passed']}/{s['total']}"
        ):
            # ── Analyst targets ────────────────────────────────────────────────
            st.markdown('<div class="section-label">Analyst Price Targets</div>', unsafe_allow_html=True)
            tc1, tc2, tc3, tc4, tc5, tc6 = st.columns(6)
            with tc1:
                st.markdown(
                    f"<div class='metric-card'><div class='metric-label'>Consensus</div>"
                    f"<div class='metric-value' style='color:{rec_color}'>{s['rec']}</div></div>",
                    unsafe_allow_html=True,
                )
            with tc2:
                metric_card("# Analysts", str(s["num_analysts"]) if s["num_analysts"] else "N/A")
            with tc3:
                metric_card("Target Low", s["target_low"])
            with tc4:
                metric_card("Target Mean", s["target_price"])
            with tc5:
                metric_card("Target High", s["target_high"])
            with tc6:
                st.markdown(
                    f"<div class='metric-card'><div class='metric-label'>Upside (Mean)</div>"
                    f"<div class='metric-value' style='color:{upside_color}'>{upside_str}</div></div>",
                    unsafe_allow_html=True,
                )

            # Visual target range bar
            if s["target_low"] != "N/A" and s["target_high"] != "N/A" and s["current_price_raw"]:
                tlo = s.get("target_mean", 0) * 0.85 if not isinstance(s["target_low"], str) else 0
                # Use raw numeric values for the bar
                try:
                    tlo_raw  = float(s["target_low"].replace(s["sym"], "").replace(",", ""))
                    thi_raw  = float(s["target_high"].replace(s["sym"], "").replace(",", ""))
                    tmn_raw  = float(s["target_price"].replace(s["sym"], "").replace(",", ""))
                    cur_raw  = s["current_price_raw"]
                    bar_min  = min(tlo_raw, cur_raw) * 0.97
                    bar_max  = max(thi_raw, cur_raw) * 1.03
                    bar_span = bar_max - bar_min

                    def _bar_pct(v):
                        return max(0, min(100, (v - bar_min) / bar_span * 100))

                    cur_pct = _bar_pct(cur_raw)
                    lo_pct  = _bar_pct(tlo_raw)
                    mn_pct  = _bar_pct(tmn_raw)
                    hi_pct  = _bar_pct(thi_raw)

                    st.markdown(
                        f"""<div style='margin:14px 0 6px; padding:0 8px;'>
                        <div style='position:relative; height:10px; background:rgba(255,255,255,0.08); border-radius:6px;'>
                            <div style='position:absolute; left:{lo_pct:.1f}%; width:{hi_pct-lo_pct:.1f}%;
                                height:100%; background:rgba(0,212,170,0.25); border-radius:6px;'></div>
                            <div title="Mean Target" style='position:absolute; left:{mn_pct:.1f}%;
                                transform:translateX(-50%); width:3px; height:100%; background:#00D4AA;'></div>
                            <div title="Current Price" style='position:absolute; left:{cur_pct:.1f}%;
                                transform:translateX(-50%); width:10px; height:16px; top:-3px;
                                background:#fff; border-radius:3px;'></div>
                        </div>
                        <div style='display:flex; justify-content:space-between;
                            font-size:0.72rem; color:rgba(255,255,255,0.45); margin-top:5px;'>
                            <span>Low {s['target_low']}</span>
                            <span style='color:#aaa;'>● Current {s['current_price']}</span>
                            <span style='color:#00D4AA;'>│ Mean {s['target_price']}</span>
                            <span>High {s['target_high']}</span>
                        </div></div>""",
                        unsafe_allow_html=True,
                    )
                except (ValueError, ZeroDivisionError):
                    pass

            st.write("")

            # ── Fundamental checklist ──────────────────────────────────────────
            st.markdown('<div class="section-label">Fundamental Conditions</div>', unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:1rem; font-weight:700; color:{score_color}; margin-bottom:10px;'>"
                f"Score: {s['passed']}/{s['total']} — "
                f"{'🏆 Strong' if s['passed'] >= 7 else '👍 Good' if s['passed'] >= 5 else '⚠️ Caution' if s['passed'] >= 3 else '🚫 Weak'}"
                f"</div>",
                unsafe_allow_html=True,
            )
            check_cols = st.columns(2)
            for idx, (label, passed, detail) in enumerate(s["checks"]):
                icon   = "✅" if passed is True else "❌" if passed is False else "❓"
                bg     = ("rgba(0,212,170,0.08)" if passed is True
                          else "rgba(255,107,107,0.08)" if passed is False
                          else "rgba(255,255,255,0.03)")
                border = ("#00D4AA" if passed is True
                          else "#FF6B6B" if passed is False
                          else "rgba(255,255,255,0.08)")
                with check_cols[idx % 2]:
                    st.markdown(
                        f"<div style='background:{bg}; border:1px solid {border}; border-radius:8px;"
                        f" padding:8px 14px; margin-bottom:8px;'>"
                        f"<span style='font-size:1rem;'>{icon}</span>"
                        f" <span style='font-weight:600; font-size:0.88rem;'>{label}</span>"
                        f"<div style='font-size:0.75rem; color:rgba(255,255,255,0.5); margin-top:2px;'>{detail}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    st.write("")

    # ── AI Portfolio Analysis ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">🤖 AI Portfolio Analysis</div>', unsafe_allow_html=True)

    if not api_key:
        st.info("Enter your API key in the sidebar to enable AI-powered portfolio analysis.")
        return

    st.markdown(
        """<div class="info-banner">
        🤖 <b>GPT-4o</b> searches the web for the latest news and analyst views on every stock,
        then delivers a full portfolio report — per-stock verdicts with <b>AI price targets</b>,
        diversification review, and prioritised actions.
        Typically takes <b>45–90 seconds</b>.
        </div>""",
        unsafe_allow_html=True,
    )

    if st.button("▶  Run AI Portfolio Analysis", type="primary"):
        ai_payload = [
            {
                "ticker":          s["ticker"],
                "company_name":    s["company_name"],
                "sector":          s["sector"],
                "country":         s["country"],
                "market_name":     s["market_name"],
                "current_price":   s["current_price"],
                "target_low":      s["target_low"],
                "target_price":    s["target_price"],
                "target_high":     s["target_high"],
                "upside_pct":      s["upside_pct"],
                "analyst_rec":     s["rec"],
                "analyst_count":   s["num_analysts"] or "N/A",
                "metrics_summary": s["metrics_summary"],
                "checklist_score": f"{s['passed']}/{s['total']}",
            }
            for s in stocks
        ]
        st.write_stream(analyze_portfolio(ai_payload, api_key))


# ── Screener renderer ─────────────────────────────────────────────────────────

def _render_screener(selected_markets: list, api_key: str) -> None:
    from src.markets import MARKETS as _MARKETS

    st.markdown(
        "<div class='section-label' style='font-size:1.3rem;'>🔎 Stock Screener</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Select markets and adjust the filter sliders below, then click **Run Screener**. "
        "Only stocks that meet ALL active filters are shown."
    )

    # ── Market selector ───────────────────────────────────────────────────────
    market_codes = [_MARKETS[m]["code"] for m in selected_markets if m in _MARKETS]

    # ── Filter sliders ────────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 3])

    with col_left:
        st.markdown("##### Valuation")
        pe_max     = st.slider("P/E (TTM) max",       0.0, 100.0, 40.0, 0.5)
        fpe_max    = st.slider("Forward P/E max",      0.0, 100.0, 35.0, 0.5)
        pb_max     = st.slider("P/B max",              0.0,  20.0,  5.0, 0.1)
        peg_max    = st.slider("PEG max",              0.0,   5.0,  2.0, 0.1)

        st.markdown("##### Profitability")
        roe_min    = st.slider("ROE % min",          -20.0,  60.0,  0.0, 0.5)
        roa_min    = st.slider("ROA % min",          -10.0,  30.0,  0.0, 0.5)
        nm_min     = st.slider("Net Margin % min",   -20.0,  50.0,  0.0, 0.5)
        gm_min     = st.slider("Gross Margin % min",   0.0, 100.0,  0.0, 1.0)

        st.markdown("##### Growth")
        rev_g_min  = st.slider("Rev Growth % min",   -20.0,  80.0,  0.0, 1.0)
        earn_g_min = st.slider("Earn Growth % min",  -50.0, 150.0,  0.0, 1.0)

        st.markdown("##### Financial Health")
        de_max     = st.slider("Debt/Equity max",      0.0,  10.0,  3.0, 0.1)
        cr_min     = st.slider("Current Ratio min",    0.0,   5.0,  0.0, 0.1)

        st.markdown("##### Dividend")
        div_min    = st.slider("Div Yield % min",      0.0,  15.0,  0.0, 0.1)

        run_btn = st.button("▶  Run Screener", type="primary", use_container_width=True)

    with col_right:
        if not run_btn:
            universe = get_universe_for_markets(market_codes)
            st.info(
                f"Universe: **{len(universe)} stocks** across "
                f"**{len(market_codes)} markets**. "
                "Adjust sliders and click **Run Screener** to start."
            )
            return

        universe = get_universe_for_markets(market_codes)
        if not universe:
            st.warning("No stocks found for the selected markets. Select at least one market in the sidebar.")
            return

        total = len(universe)
        st.markdown(f"Screening **{total} stocks** — this may take 1–3 minutes…")
        prog_bar  = st.progress(0.0)
        prog_text = st.empty()

        def _on_progress(done: int, t: int):
            prog_bar.progress(done / t)
            prog_text.caption(f"{done} / {t} tickers fetched…")

        filters = {
            "P/E (TTM)":     (None,    pe_max),
            "Fwd P/E":       (None,    fpe_max),
            "P/B":           (None,    pb_max),
            "PEG":           (None,    peg_max),
            "ROE %":         (roe_min,  None),
            "ROA %":         (roa_min,  None),
            "Net Margin %":  (nm_min,   None),
            "Gross Margin %":(gm_min,   None),
            "Rev Growth %":  (rev_g_min, None),
            "Earn Growth %": (earn_g_min, None),
            "D/E":           (None,    de_max),
            "Current Ratio": (cr_min,   None),
            "Div Yield %":   (div_min,  None),
        }

        with st.spinner(""):
            result_df = screen_stocks(
                universe, filters, max_workers=25, progress_cb=_on_progress
            )

        prog_bar.empty()
        prog_text.empty()

        if result_df.empty:
            st.warning("No stocks matched your filters. Try relaxing some criteria.")
            return

        st.success(f"✅ **{len(result_df)} stocks** matched your filters.")

        # Display columns (drop internal _price)
        display_cols = [
            "Ticker", "Name", "Sector", "Market Cap (B)",
            "P/E (TTM)", "Fwd P/E", "P/B", "PEG",
            "ROE %", "ROA %", "Net Margin %", "Gross Margin %",
            "Rev Growth %", "Earn Growth %",
            "D/E", "Current Ratio", "Div Yield %",
        ]
        display_cols = [c for c in display_cols if c in result_df.columns]
        df_show = result_df[display_cols].copy()

        # Round numeric columns for readability
        for col in df_show.select_dtypes("float").columns:
            df_show[col] = df_show[col].round(2)

        st.dataframe(
            df_show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Market Cap (B)": st.column_config.NumberColumn(format="%.2f B"),
                "P/E (TTM)":      st.column_config.NumberColumn(format="%.1f x"),
                "Fwd P/E":        st.column_config.NumberColumn(format="%.1f x"),
                "P/B":            st.column_config.NumberColumn(format="%.2f x"),
                "PEG":            st.column_config.NumberColumn(format="%.2f"),
                "ROE %":          st.column_config.NumberColumn(format="%.1f %%"),
                "ROA %":          st.column_config.NumberColumn(format="%.1f %%"),
                "Net Margin %":   st.column_config.NumberColumn(format="%.1f %%"),
                "Gross Margin %": st.column_config.NumberColumn(format="%.1f %%"),
                "Rev Growth %":   st.column_config.NumberColumn(format="%.1f %%"),
                "Earn Growth %":  st.column_config.NumberColumn(format="%.1f %%"),
                "D/E":            st.column_config.NumberColumn(format="%.2f"),
                "Current Ratio":  st.column_config.NumberColumn(format="%.2f"),
                "Div Yield %":    st.column_config.NumberColumn(format="%.2f %%"),
            },
        )
        st.caption(
            "Click any column header to sort. "
            "To analyse a stock, copy its ticker and switch to 📊 Stock Analysis mode."
        )


# ── Technical Strategy renderer ───────────────────────────────────────────────

def _render_technical_strategy() -> None:
    from src.markets import MARKETS as _MARKETS

    st.markdown(
        "<div class='section-label' style='font-size:1.3rem;'>📐 Technical Strategy</div>",
        unsafe_allow_html=True,
    )

    tab_52w, = st.tabs(["📈 52W High Strategy"])

    with tab_52w:
        st.markdown(
            """<div class="info-banner">
            <b>52W High Strategy</b> — Identifies stocks whose 52-week high is at or near
            their all-time high, indicating the stock is at peak strength. When a stock with
            <b>strong fundamentals</b> breaks above (or holds near) its 52W high, it signals
            a potential continuation breakout.<br><br>
            <b>Best used when:</b> Overall market sentiment is positive / bull market conditions.
            </div>""",
            unsafe_allow_html=True,
        )

        col_cfg, col_results = st.columns([1, 3])

        with col_cfg:
            st.markdown("##### Market")
            market_name = st.selectbox(
                "Select market",
                options=list(_MARKETS.keys()),
                index=0,
                label_visibility="collapsed",
            )
            market_code = _MARKETS[market_name]["code"]

            st.markdown("##### Strategy Parameters")
            ath_gap = st.slider(
                "Max gap below ATH (%)",
                min_value=1.0, max_value=20.0, value=8.0, step=0.5,
                help="Include stocks whose 52W high is at most this % below their all-time high.",
            )
            breakout_thr = st.slider(
                "Breakout proximity (%)",
                min_value=0.5, max_value=10.0, value=3.0, step=0.5,
                help="Price must be within this % below the 52W high to qualify as 'near breakout'.",
            )
            min_fund = st.slider(
                "Min fundamental score (out of 5)",
                min_value=1, max_value=5, value=3, step=1,
                help="Criteria: ROE>15%, P/E<40, Rev Growth>5%, Net Margin>8%, D/E<1x.",
            )

            universe = UNIVERSES.get(market_code, [])
            st.caption(f"Universe: **{len(universe)} stocks**")

            run_btn = st.button("▶  Run Strategy", type="primary", use_container_width=True)

        with col_results:
            if not run_btn:
                st.info(
                    "Configure the parameters on the left, then click **Run Strategy**.\n\n"
                    "The scan fetches live price & fundamental data for every stock in the "
                    "selected market — this typically takes 1–3 minutes."
                )
                st.markdown(
                    """
**How signals are assigned:**

| Signal | Criteria |
|--------|----------|
| 🟢 BUY | Price ≥ 52W high **and** fundamentals strong |
| 🟡 WATCH | Price within breakout proximity of 52W high **and** fundamentals strong |
| 🔵 NEAR HIGH | Price within breakout proximity of 52W high, fundamentals weak |
| ⬜ PASS | Not near 52W high |

**Fundamental checks** (need ≥ min score): ROE > 15% · P/E 0–40 · Revenue growth > 5% · Net margin > 8% · D/E < 1×
                    """
                )
                return

            if not universe:
                st.warning("No stock universe available for this market.")
                return

            total = len(universe)
            st.markdown(f"Scanning **{total} stocks** in {market_name}…")
            prog_bar = st.progress(0.0)
            prog_text = st.empty()

            def _on_progress(done: int, t: int):
                prog_bar.progress(done / t)
                prog_text.caption(f"{done} / {t} tickers processed…")

            with st.spinner(""):
                result_df = run_52w_high_strategy(
                    universe,
                    ath_gap_threshold=ath_gap,
                    breakout_threshold=breakout_thr,
                    min_fund_score=min_fund,
                    max_workers=25,
                    progress_cb=_on_progress,
                )

            prog_bar.empty()
            prog_text.empty()

            if result_df.empty:
                st.warning(
                    "No stocks matched the strategy criteria. "
                    "Try increasing the ATH gap threshold or loosening other parameters."
                )
                return

            n_buy   = (result_df["Signal"] == "BUY").sum()
            n_watch = (result_df["Signal"] == "WATCH").sum()
            n_near  = (result_df["Signal"] == "NEAR HIGH").sum()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Candidates found", len(result_df))
            c2.metric("BUY signals", int(n_buy))
            c3.metric("WATCH signals", int(n_watch))
            c4.metric("Near High", int(n_near))

            # Emoji labels for display
            signal_emoji = {
                "BUY": "🟢 BUY",
                "WATCH": "🟡 WATCH",
                "NEAR HIGH": "🔵 NEAR HIGH",
                "PASS": "⬜ PASS",
            }
            result_df["Signal"] = result_df["Signal"].map(signal_emoji).fillna(result_df["Signal"])

            display_cols = [
                "Signal", "Ticker", "Name", "Sector",
                "Price", "52W High", "All-Time High",
                "ATH Gap %", "Breakout %",
                "Fund Score", "Fund Checks",
                "ROE %", "P/E", "Rev Growth %", "Net Margin %", "D/E",
            ]
            currency = _MARKETS[market_name]["symbol"]
            display_cols = [c for c in display_cols if c in result_df.columns]
            df_show = result_df[display_cols].copy()

            st.dataframe(
                df_show,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Signal":        st.column_config.TextColumn("Signal", width="medium"),
                    "Price":         st.column_config.NumberColumn(f"Price ({currency})", format="%.2f"),
                    "52W High":      st.column_config.NumberColumn(f"52W High ({currency})", format="%.2f"),
                    "All-Time High": st.column_config.NumberColumn(f"ATH ({currency})", format="%.2f"),
                    "ATH Gap %":     st.column_config.NumberColumn("ATH Gap %", format="%.1f %%"),
                    "Breakout %":    st.column_config.NumberColumn("Breakout %", format="%.1f %%"),
                    "Fund Score":    st.column_config.NumberColumn("Score /5", format="%d"),
                    "ROE %":         st.column_config.NumberColumn("ROE %", format="%.1f %%"),
                    "P/E":           st.column_config.NumberColumn("P/E", format="%.1f x"),
                    "Rev Growth %":  st.column_config.NumberColumn("Rev Growth %", format="%.1f %%"),
                    "Net Margin %":  st.column_config.NumberColumn("Net Margin %", format="%.1f %%"),
                    "D/E":           st.column_config.NumberColumn("D/E", format="%.2f x"),
                },
            )
            st.caption(
                "ATH Gap % = how far 52W high is from the all-time high (0% = at ATH, -5% = 5% below). "
                "Breakout % = how current price relates to 52W high (positive = broken out). "
                "To analyse a stock in depth, copy its ticker and switch to 📊 Stock Analysis."
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<h2 style='margin-bottom:4px;'>⚙️ Configuration</h2>",
        unsafe_allow_html=True,
    )

    page_mode = st.radio(
        "Mode",
        ["📊 Stock Analysis", "🔎 Stock Screener", "📁 Portfolio Analysis", "📐 Technical Strategy"],
        label_visibility="collapsed",
        horizontal=False,
    )

    st.divider()

    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        st.success("✅ AI analysis ready", icon="🔑")
    else:
        st.error("OPENAI_API_KEY not set in environment")

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

# ── Screener / Portfolio pages (short-circuit when active) ────────────────────
if page_mode == "🔎 Stock Screener":
    _render_screener(selected_markets, api_key)
    st.stop()

if page_mode == "📁 Portfolio Analysis":
    _render_portfolio(api_key)
    st.stop()

if page_mode == "📐 Technical Strategy":
    _render_technical_strategy()
    st.stop()

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
    tab_fund, tab_ai, tab_adv, tab_research, tab_charts = st.tabs(
        ["📊  Fundamentals", "🤖  AI Analysis", "🔬  Advanced Fundamental Analysis", "🔍  Research", "📈  Charts"]
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
            yahoo_ticker = full_ticker.replace(".L", ".L").strip()
            analyst_url = f"https://finance.yahoo.com/quote/{yahoo_ticker}/analysis/"
            st.markdown(
                f'<div class="section-label">Analyst Consensus &nbsp;'
                f'<a href="{analyst_url}" target="_blank" '
                f'style="font-size:0.75rem; color:#00D4AA; text-decoration:none; '
                f'font-weight:400; letter-spacing:normal; text-transform:none;">'
                f'↗ View full analyst breakdown</a></div>',
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
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-label'># Analyst Opinions</div>"
                    f"<div class='metric-value'>"
                    f"{num_analysts if num_analysts else 'N/A'} &nbsp;"
                    f"<a href='{analyst_url}' target='_blank' "
                    f"style='font-size:0.78rem; color:#00D4AA; text-decoration:none;'>↗</a>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

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

    # ── Tab 3: Advanced Analysis ───────────────────────────────────────────────
    with tab_adv:
        adv = compute_advanced_metrics(stock_data)
        sym = symbol  # currency symbol shorthand

        def _fmt(val, as_pct=False, as_currency=False, decimals=2):
            if val is None:
                return "—"
            if as_pct:
                return f"{val * 100:.{decimals}f}%"
            if as_currency:
                from src.stock_data import format_currency
                return format_currency(val, sym)
            return f"{val:.{decimals}f}"

        def adv_card(label, value, light=""):
            st.markdown(
                f"<div class='metric-card'>"
                f"<div class='metric-label'>{label}</div>"
                f"<div class='metric-value'>{light} {value}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        def trend_bar(trend_data, title, color="#00D4AA", value_sym=""):
            if not trend_data:
                return None
            years  = [y for y, _ in trend_data]
            values = [v / 1e9 for _, v in trend_data]
            bar_colors = [
                color if v >= 0 else "#FF6B6B" for v in values
            ]
            fig = go.Figure(go.Bar(
                x=years, y=values,
                marker_color=bar_colors,
                text=[f"{v:.2f}B" for v in values],
                textposition="outside",
            ))
            fig.update_layout(
                title=title,
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=260,
                showlegend=False,
                yaxis=dict(title=f"{value_sym}B", gridcolor="rgba(255,255,255,0.05)"),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            return fig

        # ── Section A: Valuation Scorecard ────────────────────────────────────
        st.markdown('<div class="section-label">📊 Valuation Scorecard</div>', unsafe_allow_html=True)
        pe_tl  = traffic_light(adv["pe"],  True,  15, 25)
        pb_tl  = traffic_light(adv["pb"],  True,  1,  3)
        peg_tl = traffic_light(adv["peg"], True,  1,  2)

        c1, c2, c3, c4 = st.columns(4)
        with c1: adv_card("P/E Ratio (TTM)", _fmt(adv["pe"]) + "x", pe_tl)
        with c2: adv_card("P/B Ratio",       _fmt(adv["pb"]) + "x", pb_tl)
        with c3: adv_card("PEG Ratio",       _fmt(adv["peg"]) + "x" if adv["peg"] else "—", peg_tl)
        with c4: adv_card("Forward P/E",     _fmt(adv["forward_pe"]) + "x" if adv["forward_pe"] else "—")

        # Overvalued / undervalued note (will be updated after web search)
        valuation_placeholder = st.empty()

        st.write("")

        # ── Section B: Balance Sheet Panel ────────────────────────────────────
        st.markdown('<div class="section-label">📋 Balance Sheet & Income</div>', unsafe_allow_html=True)

        b1, b2, b3, b4 = st.columns(4)
        with b1:
            adv_card("Total Revenue",    _fmt(adv["revenue"],    as_currency=True))
            adv_card("Gross Profit",     _fmt(adv["gross_profit"], as_currency=True))
        with b2:
            adv_card("EBIT",             _fmt(adv["ebit"],       as_currency=True))
            adv_card("EBITDA",           _fmt(adv["ebitda"],     as_currency=True))
        with b3:
            adv_card("Net Income",       _fmt(adv["net_income"], as_currency=True))
            adv_card("Free Cash Flow",   _fmt(adv["fcf"],        as_currency=True))
        with b4:
            adv_card("Total Assets",     _fmt(adv["total_assets"],      as_currency=True))
            adv_card("Total Liabilities",_fmt(adv["total_liabilities"], as_currency=True))

        st.write("")
        m1, m2, m3, m4 = st.columns(4)
        with m1: adv_card("Gross Margin",   _fmt(adv["gross_margin"], as_pct=True),
                           traffic_light(adv["gross_margin"], False, 0.40, 0.20))
        with m2: adv_card("EBIT Margin",    _fmt(adv["ebit_margin"],  as_pct=True),
                           traffic_light(adv["ebit_margin"],  False, 0.15, 0.05))
        with m3: adv_card("Net Margin",     _fmt(adv["net_margin"],   as_pct=True),
                           traffic_light(adv["net_margin"],   False, 0.10, 0.03))
        with m4: adv_card("Operating CF",   _fmt(adv["op_cashflow"],  as_currency=True))

        st.write("")

        # ── Section C: Capital, Leverage & Returns ────────────────────────────
        st.markdown('<div class="section-label">⚖️ Capital, Leverage & Returns</div>', unsafe_allow_html=True)

        cr_tl   = traffic_light(adv["current_ratio"], False, 2.0,  1.0)   # >2 🟢, >1 🟡, <1 🔴
        de_tl   = traffic_light(adv["de_ratio"],      True,  0.5,  1.5)   # <0.5 🟢, <1.5 🟡, else 🔴
        ic_tl   = traffic_light(adv["interest_cov"],  False, 5.0,  2.0)   # >5 🟢, >2 🟡, <2 🔴
        roe_tl  = traffic_light(adv["roe"],           False, 0.15, 0.10)
        roic_tl = traffic_light(adv["roic"],          False, 0.15, 0.08)

        r1, r2, r3, r4, r5 = st.columns(5)
        with r1: adv_card("Debt / Equity",      _fmt(adv["de_ratio"])   + "x" if adv["de_ratio"] else "—", de_tl)
        with r2: adv_card("Current Ratio",      _fmt(adv["current_ratio"]) + "x" if adv["current_ratio"] else "—", cr_tl)
        with r3: adv_card("Interest Coverage",  _fmt(adv["interest_cov"])  + "x" if adv["interest_cov"]  else "—", ic_tl)
        with r4: adv_card("ROE",                _fmt(adv["roe"],  as_pct=True), roe_tl)
        with r5: adv_card("ROIC",               _fmt(adv["roic"], as_pct=True), roic_tl)

        r6, r7, r8, r9, r10 = st.columns(5)
        with r6: adv_card("ROA",                _fmt(adv["roa"],         as_pct=True))
        with r7: adv_card("Revenue Growth YoY", _fmt(adv["rev_growth"],  as_pct=True),
                           traffic_light(adv["rev_growth"], False, 0.15, 0.05))
        with r8: adv_card("Earnings Growth YoY",_fmt(adv["earn_growth"], as_pct=True),
                           traffic_light(adv["earn_growth"], False, 0.15, 0.05))
        with r9: adv_card("EPS (TTM)",          _fmt(adv["eps_ttm"],     as_currency=True))
        with r10: adv_card("Forward EPS",       _fmt(adv["eps_forward"], as_currency=True),
                           "🟢" if (adv["eps_forward"] and adv["eps_ttm"]
                                    and adv["eps_forward"] > adv["eps_ttm"]) else "🔴"
                           if (adv["eps_forward"] and adv["eps_ttm"]) else "⚪")

        op_lev_val = ("🟢 Yes — earnings growing faster than revenue"
                      if adv["op_leverage"] is True else
                      "🔴 No — earnings lagging revenue growth"
                      if adv["op_leverage"] is False else "⚪ Insufficient data")
        st.markdown(
            f"<div class='metric-card'><div class='metric-label'>Operating Leverage</div>"
            f"<div class='metric-value'>{op_lev_val}</div></div>",
            unsafe_allow_html=True,
        )
        st.write("")

        # ── Section D: Ownership & Institutional (web search) ─────────────────
        st.markdown('<div class="section-label">🏦 Ownership & Institutional Activity</div>',
                    unsafe_allow_html=True)

        ownership = {}
        if api_key:
            with st.spinner("Searching the web for ownership and institutional data …"):
                is_indian = any(x in market_choice.lower() for x in ["india", "nse", "bse"])
                ownership = fetch_ownership_data(
                    ticker=full_ticker,
                    company_name=company_name,
                    market_name=market_choice,
                    sector=f"{sector} {industry}".strip(),
                    api_key=api_key,
                )

            o1, o2, o3, o4 = st.columns(4)
            beat_raise = ownership.get("recent_beat_and_raise")
            beat_tl = "🟢" if beat_raise is True else ("🔴" if beat_raise is False else "⚪")

            inst_trend = ownership.get("institutional_trend", "")
            inst_tl = {"increasing": "🟢", "decreasing": "🔴", "stable": "🟡"}.get(
                inst_trend or "", "⚪")

            mf_entering = ownership.get("mf_or_foreign_investment_entering")
            mf_tl = "🟢" if mf_entering is True else ("🔴" if mf_entering is False else "⚪")

            with o1:
                if is_indian:
                    adv_card("Promoter Holdings",
                             f"{ownership.get('promoter_holdings_pct', '—')}%"
                             if ownership.get("promoter_holdings_pct") else "—",
                             traffic_light(ownership.get("promoter_holdings_pct"), False, 50, 30))
                else:
                    adv_card("Insider Ownership",
                             f"{ownership.get('insider_ownership_pct', '—')}%"
                             if ownership.get("insider_ownership_pct") else "—",
                             traffic_light(ownership.get("insider_ownership_pct"), False, 10, 5))
            with o2:
                if is_indian:
                    adv_card("Promoter Pledgings",
                             f"{ownership.get('promoter_pledgings_pct', '—')}%"
                             if ownership.get("promoter_pledgings_pct") else "—",
                             traffic_light(ownership.get("promoter_pledgings_pct"), True, 5, 20))
                else:
                    adv_card("Industry Avg P/E",
                             f"{ownership.get('industry_avg_pe', '—')}x"
                             if ownership.get("industry_avg_pe") else "—")
            with o3:
                adv_card("Institutional Trend",
                         (inst_trend or "Unknown").capitalize(), inst_tl)
            with o4:
                adv_card("MF / Foreign Entering",
                         "Yes" if mf_entering is True else
                         "No" if mf_entering is False else "Unknown", mf_tl)

            if ownership.get("beat_raise_details"):
                st.markdown(
                    f"<div class='metric-card'>"
                    f"<div class='metric-label'>Most Recent Earnings {beat_tl}</div>"
                    f"<div class='metric-value' style='font-size:0.95rem;'>"
                    f"{ownership['beat_raise_details']}</div></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Enter API key in the sidebar to load ownership and institutional data.")

        st.write("")

        # ── Now update valuation placeholder with intrinsic value ─────────────
        industry_pe   = ownership.get("industry_avg_pe")
        intrinsic_val = None
        if adv["eps_forward"] and industry_pe:
            intrinsic_val = adv["eps_forward"] * float(industry_pe)

        current_p = adv["current_price"]
        if intrinsic_val and current_p:
            diff_pct   = (intrinsic_val - current_p) / current_p * 100
            verdict    = "🟢 UNDERVALUED" if intrinsic_val > current_p else "🔴 OVERVALUED"
            valuation_placeholder.markdown(
                f"<div class='metric-card' style='border-color:rgba(0,212,170,0.4);'>"
                f"<div class='metric-label'>Intrinsic Value Estimate "
                f"(Forward EPS × Industry P/E {industry_pe}x)</div>"
                f"<div class='metric-value'>{sym}{intrinsic_val:.2f} &nbsp; "
                f"<span style='font-size:0.9rem; color:{'#00D4AA' if diff_pct>0 else '#FF6B6B'}'>"
                f"{'+' if diff_pct > 0 else ''}{diff_pct:.1f}% vs current {sym}{current_p:.2f}"
                f"</span> &nbsp; {verdict}</div></div>",
                unsafe_allow_html=True,
            )

        # ── Section E: Investment Checklist ───────────────────────────────────
        st.markdown('<div class="section-label">✅ Investment Checklist</div>', unsafe_allow_html=True)
        st.caption("Based on the Henry Chien fundamental analysis framework")

        def checklist_item(num, label, passed, detail=""):
            icon   = "✅" if passed is True else ("❌" if passed is False else "❓")
            bg     = ("rgba(0,212,170,0.08)" if passed is True
                      else "rgba(255,107,107,0.08)" if passed is False
                      else "rgba(255,255,255,0.03)")
            border = ("#00D4AA" if passed is True
                      else "#FF6B6B" if passed is False
                      else "rgba(255,255,255,0.08)")
            st.markdown(
                f"<div style='background:{bg}; border:1px solid {border}; border-radius:8px;"
                f" padding:10px 16px; margin-bottom:8px; display:flex; align-items:center; gap:12px;'>"
                f"<span style='font-size:1.2rem;'>{icon}</span>"
                f"<div><div style='font-weight:600; font-size:0.9rem;'>{num}. {label}</div>"
                f"<div style='font-size:0.78rem; color:rgba(255,255,255,0.5); margin-top:2px;'>{detail}</div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        checks = []

        # 1. Intrinsic Value > Current Price
        if intrinsic_val and current_p:
            checks.append((
                "Intrinsic Value > Current Price",
                intrinsic_val > current_p,
                f"Intrinsic: {sym}{intrinsic_val:.2f}  |  Current: {sym}{current_p:.2f}"
                f"  (Industry P/E: {industry_pe}x)"
            ))
        else:
            checks.append(("Intrinsic Value > Current Price", None,
                           "Needs industry P/E from web search — run with API key"))

        # 2. P/E Low (vs industry)
        pe_val = adv["pe"]
        if pe_val and industry_pe:
            checks.append(("P/E Ratio is Low", pe_val < float(industry_pe),
                           f"Stock P/E: {pe_val:.1f}x  |  Industry avg: {industry_pe}x"))
        elif pe_val:
            checks.append(("P/E Ratio is Low", pe_val < 20,
                           f"P/E: {pe_val:.1f}x (threshold: <20)"))
        else:
            checks.append(("P/E Ratio is Low", None, "P/E data unavailable"))

        # 3. P/B Low
        pb_val = adv["pb"]
        checks.append(("P/B Ratio is Low",
                        (pb_val < 3) if pb_val is not None else None,
                        f"P/B: {pb_val:.2f}x (threshold: <3)" if pb_val else "P/B data unavailable"))

        # 4. D/E Low (industry dependent)
        de_val = adv["de_ratio"]
        checks.append(("Debt / Equity is Low",
                        (de_val < 1.0) if de_val is not None else None,
                        f"D/E: {de_val:.2f}x (threshold: <1.0)" if de_val else "D/E data unavailable"))

        # 5. Current Ratio > 1 (standard finance)
        cr_val = adv["current_ratio"]
        checks.append(("Current Ratio > 1.0",
                        (cr_val > 1.0) if cr_val is not None else None,
                        f"Current Ratio: {cr_val:.2f}x" if cr_val else "Data unavailable"))

        # 6. Promoter Pledgings Low  /  Insider Ownership High
        if is_indian:
            pledg = ownership.get("promoter_pledgings_pct")
            checks.append(("Promoter Pledgings Low",
                           (pledg < 10) if pledg is not None else None,
                           f"Pledgings: {pledg}%" if pledg is not None else "Data not found via web search"))
        else:
            insider = ownership.get("insider_ownership_pct")
            checks.append(("Insider Ownership > 10%",
                           (insider > 10) if insider is not None else None,
                           f"Insider ownership: {insider}%" if insider is not None else "Data not found via web search"))

        # 7. Promoter / Institutional trend increasing
        if is_indian:
            ph = ownership.get("promoter_holdings_pct")
            checks.append(("Promoter Holding Trend Increasing",
                           None if not ownership else ownership.get("institutional_trend") == "increasing",
                           f"Holdings: {ph}%" if ph else "See institutional trend field"))
        else:
            inst = ownership.get("institutional_trend")
            checks.append(("Institutional Holding Trend Increasing",
                           (inst == "increasing") if inst else None,
                           f"Trend: {inst or 'Unknown'}"))

        # 8. MF / Foreign investment entering
        mf = ownership.get("mf_or_foreign_investment_entering")
        checks.append(("MF / Foreign Investors Entering",
                       mf,
                       "Based on recent 13F filings and fund flow data" if mf is not None else "Data not found"))

        # 9. Cash flow increasing
        checks.append(("Operating Cash Flow Increasing",
                       adv["cashflow_increasing"],
                       f"Trend: {' → '.join(f'{sym}{v/1e9:.1f}B' for _, v in adv['cashflow_trend'][-3:])}"
                       if adv["cashflow_trend"] else "Insufficient historical data"))

        # 10. Net Profit & EBITDA growing
        both_growing = (adv["net_profit_increasing"] and adv["ebitda_increasing"]
                        if adv["net_profit_increasing"] is not None
                        and adv["ebitda_increasing"] is not None else None)
        np_dir  = "↑" if adv["net_profit_increasing"] else ("↓" if adv["net_profit_increasing"] is False else "?")
        ebd_dir = "↑" if adv["ebitda_increasing"]     else ("↓" if adv["ebitda_increasing"]     is False else "?")
        checks.append(("Net Profit & EBITDA Growing",
                       both_growing,
                       f"Net Profit: {np_dir}  |  EBITDA: {ebd_dir}"))

        passed_count = sum(1 for _, p, _ in checks if p is True)
        total_scored = sum(1 for _, p, _ in checks if p is not None)
        score_color  = "#00D4AA" if passed_count >= 7 else ("#FFA500" if passed_count >= 5 else "#FF6B6B")
        st.markdown(
            f"<div style='font-size:1.1rem; font-weight:700; margin-bottom:14px; color:{score_color};'>"
            f"Score: {passed_count} / {total_scored} checks passed"
            f"{'  🏆 Strong' if passed_count >= 8 else '  👍 Good' if passed_count >= 6 else '  ⚠️ Caution' if passed_count >= 4 else '  🚫 Weak'}"
            f"</div>",
            unsafe_allow_html=True,
        )
        for i, (label, passed, detail) in enumerate(checks, 1):
            checklist_item(i, label, passed, detail)

        st.write("")

        # ── Section F: Trend Charts ────────────────────────────────────────────
        st.markdown('<div class="section-label">📈 Trend Charts</div>', unsafe_allow_html=True)

        chart_pairs = [
            (adv["revenue_trend"],    "Revenue",          "#00D4AA"),
            (adv["net_income_trend"], "Net Income",       "#0099FF"),
            (adv["ebitda_trend"],     "EBITDA",           "#AA66FF"),
            (adv["cashflow_trend"],   "Operating Cash Flow", "#FFB300"),
            (adv["fcf_trend"],        "Free Cash Flow",   "#00D4AA"),
            (adv["eps_trend"],        "EPS",              "#0099FF"),
        ]
        # Only render charts that have data; group in rows of 2
        available = [(t, title, color) for t, title, color in chart_pairs if t]
        for i in range(0, len(available), 2):
            pair = available[i: i + 2]
            cols = st.columns(len(pair))
            for col, (trend_data, title, color) in zip(cols, pair):
                with col:
                    # EPS uses raw values (not billions)
                    if "EPS" in title:
                        years  = [y for y, _ in trend_data]
                        values = [v for _, v in trend_data]
                        fig = go.Figure(go.Bar(
                            x=years, y=values,
                            marker_color=[color if v >= 0 else "#FF6B6B" for v in values],
                            text=[f"{sym}{v:.2f}" for v in values],
                            textposition="outside",
                        ))
                        fig.update_layout(
                            title=title, template="plotly_dark",
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            height=260, showlegend=False,
                            yaxis=dict(title=sym, gridcolor="rgba(255,255,255,0.05)"),
                            margin=dict(l=0, r=0, t=40, b=0),
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        fig = trend_bar(trend_data, title, color, sym)
                        if fig:
                            st.plotly_chart(fig, use_container_width=True)

    # ── Tab 4: Research ────────────────────────────────────────────────────────
    with tab_research:
        if not api_key:
            st.warning(
                "⚠️ **API key required.** "
                "Set your OpenAI API key in the environment to unlock Research."
            )
        else:
            st.markdown(
                """<div class="info-banner">
                🔍 <b>GPT-4o</b> is searching the web for the latest news, earnings calls,
                analyst opinions, SWOT factors, and macro context. This is a comprehensive
                research report and typically takes <b>45–90 seconds</b>.
                </div>""",
                unsafe_allow_html=True,
            )
            sector_str = " — ".join(p for p in [sector, industry] if p) or "N/A"
            price_str = (
                f"{symbol}{current_price:,.2f}"
                if current_price
                else "N/A"
            )
            st.write_stream(
                research_stock(
                    ticker=full_ticker,
                    company_name=company_name,
                    sector=sector_str,
                    market_name=market_choice,
                    current_price=price_str,
                    api_key=api_key,
                )
            )

    # ── Tab 5: Charts ─────────────────────────────────────────────────────────
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

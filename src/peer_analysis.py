"""
Peer Comparison Module
======================
Identifies peer companies for a given stock and builds comparison tables
with valuation multiples, operating metrics, and plain-language insights.

Usage:
    peers = find_peers(ticker, sector, industry, screening_df=screening_df)
    peer_df = fetch_peer_data(peers)
    comparison = build_comparison_table(target_data, peer_df)
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


# ---------------------------------------------------------------------------
# Peer discovery
# ---------------------------------------------------------------------------

def find_peers(
    ticker: str,
    sector: str,
    industry: str,
    screening_df: Optional[pd.DataFrame] = None,
    max_peers: int = 10,
) -> List[str]:
    """Find peer tickers from the same industry/sector.

    Parameters
    ----------
    ticker       : the target ticker to find peers for (excluded from results)
    sector       : sector string for the target stock
    industry     : industry string for the target stock
    screening_df : optional DataFrame from a fundamental screen; must contain
                   at least 'Ticker' and ideally 'Industry' / 'Sector' columns
    max_peers    : maximum number of peer tickers to return

    Returns
    -------
    List of peer ticker strings (may be empty).
    """
    if screening_df is None or screening_df.empty:
        return []

    df = screening_df.copy()

    # Normalise the ticker column name
    ticker_col = None
    for col in ("Ticker", "ticker", "Symbol", "symbol"):
        if col in df.columns:
            ticker_col = col
            break
    if ticker_col is None:
        return []

    # Exclude the target ticker itself
    df = df[df[ticker_col].str.upper() != ticker.upper()]

    # Try industry match first
    if industry and "Industry" in df.columns:
        industry_matches = df[df["Industry"].str.lower() == industry.lower()]
        if len(industry_matches) > 0:
            return industry_matches[ticker_col].head(max_peers).tolist()

    # Fallback to sector match
    if sector and "Sector" in df.columns:
        sector_matches = df[df["Sector"].str.lower() == sector.lower()]
        if len(sector_matches) > 0:
            return sector_matches[ticker_col].head(max_peers).tolist()

    return []


# ---------------------------------------------------------------------------
# Single-ticker data fetch
# ---------------------------------------------------------------------------

def _fetch_peer_data(ticker: str) -> Optional[dict]:
    """Fetch valuation and operating metrics for a single peer ticker.

    Retries up to 2 times on 401/crumb errors, resetting yfinance auth
    before each retry.
    """
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

            name = info.get("shortName") or info.get("longName") or ticker
            sector = info.get("sector") or "—"
            industry = info.get("industry") or "—"
            mktcap = _to_float(info.get("marketCap"))
            currency = info.get("currency", "")

            revenue = _to_float(info.get("totalRevenue"))
            ebitda = _to_float(info.get("ebitda"))
            net_income = _to_float(info.get("netIncomeToCommon"))
            operating_margins = _to_float(info.get("operatingMargins"))
            profit_margins = _to_float(info.get("profitMargins"))
            roe = _to_float(info.get("returnOnEquity"))
            revenue_growth = _to_float(info.get("revenueGrowth"))

            ev_ebitda = _to_float(info.get("enterpriseToEbitda"))
            trailing_pe = _to_float(info.get("trailingPE"))
            forward_pe = _to_float(info.get("forwardPE"))
            price_to_book = _to_float(info.get("priceToBook"))
            shares_out = _to_float(info.get("sharesOutstanding"))

            # Derived metrics
            ebitda_margin = None
            if ebitda is not None and revenue is not None and revenue != 0:
                ebitda_margin = ebitda / revenue

            ev = _to_float(info.get("enterpriseValue"))
            ev_sales = None
            if ev is not None and revenue is not None and revenue != 0:
                ev_sales = ev / revenue

            total_debt = _to_float(info.get("totalDebt"))
            total_cash = _to_float(info.get("totalCash"))
            net_debt = None
            if total_debt is not None and total_cash is not None:
                net_debt = total_debt - total_cash

            net_debt_ebitda = None
            if net_debt is not None and ebitda is not None and ebitda != 0:
                net_debt_ebitda = net_debt / ebitda

            # ROIC approximation — use ROE as proxy when detailed data unavailable
            roic = roe

            return {
                "Ticker": ticker,
                "Name": name,
                "Sector": sector,
                "Industry": industry,
                "Market Cap": mktcap,
                "Currency": currency,
                "Price": price,
                "Revenue": revenue,
                "EBITDA": ebitda,
                "EBITDA Margin": ebitda_margin,
                "Net Income": net_income,
                "Operating Margin": operating_margins,
                "Net Margin": profit_margins,
                "ROE": roe,
                "ROIC": roic,
                "Revenue Growth": revenue_growth,
                "EV/EBITDA": ev_ebitda,
                "P/E": trailing_pe,
                "Forward P/E": forward_pe,
                "EV/Sales": ev_sales,
                "P/B": price_to_book,
                "Net Debt": net_debt,
                "Net Debt/EBITDA": net_debt_ebitda,
                "Shares Outstanding": shares_out,
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


# ---------------------------------------------------------------------------
# Bulk fetch
# ---------------------------------------------------------------------------

def fetch_peer_data(
    tickers: List[str],
    max_workers: int = 6,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Fetch peer metrics for a list of tickers in parallel.

    Parameters
    ----------
    tickers     : list of ticker symbols
    max_workers : parallel fetch threads (default 6)
    progress_cb : optional callback(done, total) for progress updates

    Returns
    -------
    DataFrame with all peer metrics, sorted by Market Cap descending.
    """
    warmup()

    results = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 75

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_peer_data, t): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

            if row is not None:
                results.append(row)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("Market Cap", ascending=False, na_position="last")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Comparison table & analytics
# ---------------------------------------------------------------------------

def _extract_target_metrics(target_data: dict) -> dict:
    """Extract standardised metrics from a target data dict.

    The target_data may come from a screening DataFrame row (dict) and may use
    slightly different key names.  This normalises to the same schema as
    _fetch_peer_data output.
    """
    def _get(keys):
        """Return the first available value from a list of candidate keys."""
        for k in keys:
            v = target_data.get(k)
            if v is not None:
                return _to_float(v)
        return None

    revenue = _get(["Revenue", "totalRevenue"])
    ebitda = _get(["EBITDA", "ebitda"])
    ebitda_margin = _get(["EBITDA Margin", "ebitdaMargin"])
    if ebitda_margin is None and ebitda is not None and revenue is not None and revenue != 0:
        ebitda_margin = ebitda / revenue

    ev = _get(["Enterprise Value", "enterpriseValue"])
    ev_sales = _get(["EV/Sales", "evSales"])
    if ev_sales is None and ev is not None and revenue is not None and revenue != 0:
        ev_sales = ev / revenue

    total_debt = _get(["Total Debt", "totalDebt"])
    total_cash = _get(["Total Cash", "totalCash"])
    net_debt = _get(["Net Debt", "netDebt"])
    if net_debt is None and total_debt is not None and total_cash is not None:
        net_debt = total_debt - total_cash

    net_debt_ebitda = _get(["Net Debt/EBITDA", "netDebtEbitda"])
    if net_debt_ebitda is None and net_debt is not None and ebitda is not None and ebitda != 0:
        net_debt_ebitda = net_debt / ebitda

    roe = _get(["ROE", "returnOnEquity"])
    roic = _get(["ROIC", "returnOnCapital"])
    if roic is None:
        roic = roe

    return {
        "Ticker": target_data.get("Ticker", "TARGET"),
        "Name": target_data.get("Name", target_data.get("shortName", "—")),
        "Market Cap": _get(["Market Cap", "marketCap"]),
        "Revenue": revenue,
        "EBITDA": ebitda,
        "EBITDA Margin": ebitda_margin,
        "Operating Margin": _get(["Operating Margin", "Op Margin", "operatingMargins"]),
        "Net Margin": _get(["Net Margin", "profitMargins"]),
        "ROE": roe,
        "ROIC": roic,
        "Revenue Growth": _get(["Revenue Growth", "revenueGrowth"]),
        "EV/EBITDA": _get(["EV/EBITDA", "enterpriseToEbitda"]),
        "P/E": _get(["P/E", "PE", "trailingPE"]),
        "Forward P/E": _get(["Forward P/E", "forwardPE"]),
        "EV/Sales": ev_sales,
        "P/B": _get(["P/B", "PB", "priceToBook"]),
        "Net Debt": net_debt,
        "Net Debt/EBITDA": net_debt_ebitda,
    }


def _safe_median(series: pd.Series) -> Optional[float]:
    """Return median of a series, ignoring NaN. Returns None if all NaN."""
    vals = series.dropna()
    if vals.empty:
        return None
    return float(vals.median())


def _safe_mean(series: pd.Series) -> Optional[float]:
    """Return mean of a series, ignoring NaN. Returns None if all NaN."""
    vals = series.dropna()
    if vals.empty:
        return None
    return float(vals.mean())


def _pct_fmt(v) -> str:
    """Format a decimal ratio as a percentage string, e.g. 0.15 -> '15.0%'."""
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def _num_fmt(v, decimals=1) -> str:
    """Format a number to given decimal places, or '—' if None."""
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def build_comparison_table(
    target_data: dict,
    peer_df: pd.DataFrame,
) -> dict:
    """Build comparison analytics between a target stock and its peers.

    Parameters
    ----------
    target_data : raw data dict for the selected stock (from screen or fetch)
    peer_df     : DataFrame returned by fetch_peer_data()

    Returns
    -------
    dict with keys: 'table', 'peer_median', 'peer_avg', 'premium_discount',
                    'insights'
    """
    target = _extract_target_metrics(target_data)

    # Build display table rows
    display_cols = [
        "Ticker", "Name", "Market Cap", "Revenue",
        "EBITDA Margin %", "Op Margin %", "ROE %", "Rev Growth %",
        "EV/EBITDA", "P/E", "EV/Sales", "Net Debt/EBITDA",
    ]

    def _make_display_row(d: dict, label_prefix: str = "") -> dict:
        ticker_label = f"{label_prefix}{d.get('Ticker', '—')}"
        return {
            "Ticker": ticker_label,
            "Name": d.get("Name", "—"),
            "Market Cap": d.get("Market Cap"),
            "Revenue": d.get("Revenue"),
            "EBITDA Margin %": _pct_fmt(d.get("EBITDA Margin")),
            "Op Margin %": _pct_fmt(d.get("Operating Margin")),
            "ROE %": _pct_fmt(d.get("ROE")),
            "Rev Growth %": _pct_fmt(d.get("Revenue Growth")),
            "EV/EBITDA": _num_fmt(d.get("EV/EBITDA")),
            "P/E": _num_fmt(d.get("P/E")),
            "EV/Sales": _num_fmt(d.get("EV/Sales")),
            "Net Debt/EBITDA": _num_fmt(d.get("Net Debt/EBITDA")),
        }

    rows = [_make_display_row(target, ">>> TARGET  ")]
    for _, peer_row in peer_df.iterrows():
        rows.append(_make_display_row(peer_row.to_dict()))

    table = pd.DataFrame(rows, columns=display_cols)

    # Compute peer medians and averages for key multiples
    multiple_keys = {
        "ev_ebitda": "EV/EBITDA",
        "pe": "P/E",
        "ev_sales": "EV/Sales",
    }

    peer_median: Dict[str, Optional[float]] = {}
    peer_avg: Dict[str, Optional[float]] = {}
    for short_key, col in multiple_keys.items():
        if col in peer_df.columns:
            peer_median[short_key] = _safe_median(peer_df[col])
            peer_avg[short_key] = _safe_mean(peer_df[col])
        else:
            peer_median[short_key] = None
            peer_avg[short_key] = None

    # Premium / discount vs peer median
    premium_discount: Dict[str, Optional[float]] = {}
    target_multiples = {
        "ev_ebitda": _to_float(target.get("EV/EBITDA")),
        "pe": _to_float(target.get("P/E")),
        "ev_sales": _to_float(target.get("EV/Sales")),
    }
    for key in multiple_keys:
        t_val = target_multiples.get(key)
        m_val = peer_median.get(key)
        if t_val is not None and m_val is not None and m_val != 0:
            premium_discount[key] = (t_val - m_val) / m_val * 100
        else:
            premium_discount[key] = None

    # Generate insights
    insights = generate_insights(target, peer_median, premium_discount)

    return {
        "table": table,
        "peer_median": peer_median,
        "peer_avg": peer_avg,
        "premium_discount": premium_discount,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------

def generate_insights(
    target_data: dict,
    peer_median: dict,
    premium_discount: dict,
) -> List[str]:
    """Generate 3-5 template-based plain-language insights.

    Uses conditional logic to produce relevant, data-driven observations.
    Only includes insights where sufficient data is available.

    Parameters
    ----------
    target_data      : normalised target metrics dict
    peer_median      : dict with median multiples (ev_ebitda, pe, ev_sales)
    premium_discount : dict with % premium/discount for each multiple

    Returns
    -------
    List of insight strings.
    """
    insights: List[str] = []

    # --- EV/EBITDA insight ---
    ev_ebitda_pd = premium_discount.get("ev_ebitda")
    target_ev_ebitda = _to_float(target_data.get("EV/EBITDA"))
    median_ev_ebitda = peer_median.get("ev_ebitda")
    roic = _to_float(target_data.get("ROIC"))

    if ev_ebitda_pd is not None and target_ev_ebitda is not None and median_ev_ebitda is not None:
        direction = "discount" if ev_ebitda_pd < 0 else "premium"
        abs_pd = abs(ev_ebitda_pd)
        msg = (
            f"Trades at {abs_pd:.0f}% {direction} to peer median EV/EBITDA "
            f"({target_ev_ebitda:.1f}x vs {median_ev_ebitda:.1f}x)"
        )
        if roic is not None:
            roic_pct = roic * 100
            qualifier = "higher" if roic_pct > 12 else "lower"
            msg += f" despite {qualifier} ROIC ({roic_pct:.1f}%)."
        else:
            msg += "."
        insights.append(msg)

    # --- P/E insight ---
    pe_pd = premium_discount.get("pe")
    target_pe = _to_float(target_data.get("P/E"))
    median_pe = peer_median.get("pe")
    rev_growth = _to_float(target_data.get("Revenue Growth"))

    if pe_pd is not None and target_pe is not None and median_pe is not None:
        direction = "premium" if pe_pd > 0 else "discount"
        abs_pd = abs(pe_pd)
        msg = f"P/E {direction} of {abs_pd:.0f}% ({target_pe:.1f}x vs peer median {median_pe:.1f}x)"
        if rev_growth is not None:
            growth_pct = rev_growth * 100
            speed = "faster" if growth_pct > 10 else "slower"
            justification = "justified" if (pe_pd > 0 and speed == "faster") or (pe_pd < 0 and speed == "slower") else "elevated"
            if pe_pd < 0:
                justification = "potentially undervalued" if speed == "faster" else "reflecting slower growth"
            msg += f" appears {justification} given {speed} revenue growth ({growth_pct:.1f}%)."
        else:
            msg += "."
        insights.append(msg)

    # --- EV/Sales insight ---
    ev_sales_pd = premium_discount.get("ev_sales")
    target_ev_sales = _to_float(target_data.get("EV/Sales"))
    median_ev_sales = peer_median.get("ev_sales")

    if target_ev_sales is not None and median_ev_sales is not None:
        position = "above" if target_ev_sales > median_ev_sales else "below"
        insights.append(
            f"EV/Sales of {target_ev_sales:.1f}x is {position} peer median of "
            f"{median_ev_sales:.1f}x."
        )

    # --- Net Debt/EBITDA insight ---
    target_nd_ebitda = _to_float(target_data.get("Net Debt/EBITDA"))
    # Compute peer median for Net Debt/EBITDA if not already in peer_median
    if target_nd_ebitda is not None:
        balance = "stronger" if target_nd_ebitda < 2.0 else "weaker"
        msg = (
            f"Net Debt/EBITDA of {target_nd_ebitda:.1f}x indicates "
            f"a {balance} balance sheet"
        )
        if target_nd_ebitda < 0:
            msg = (
                f"Net Debt/EBITDA of {target_nd_ebitda:.1f}x (net cash position) "
                f"indicates a strong balance sheet."
            )
        else:
            msg += "."
        insights.append(msg)

    # --- EBITDA margin insight ---
    target_ebitda_margin = _to_float(target_data.get("EBITDA Margin"))
    if target_ebitda_margin is not None:
        margin_pct = target_ebitda_margin * 100
        quality = "exceeds" if margin_pct > 20 else "trails"
        insights.append(
            f"EBITDA margin of {margin_pct:.1f}% {quality} typical benchmarks, "
            f"signalling {'strong' if margin_pct > 20 else 'room for improvement in'} "
            f"operational efficiency."
        )

    return insights

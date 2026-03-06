import json
from typing import Dict, List, Optional, Tuple

import pandas as pd
from openai import OpenAI


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _get_row(df: pd.DataFrame, *names: str) -> Optional[pd.Series]:
    """Find first matching row in a DataFrame — exact match first, then partial."""
    if df is None or df.empty:
        return None
    # Normalised exact match
    for name in names:
        norm = name.lower().replace(" ", "").replace("_", "")
        for idx in df.index:
            if str(idx).lower().replace(" ", "").replace("_", "") == norm:
                return df.loc[idx]
    # Partial match
    for name in names:
        for idx in df.index:
            if name.lower() in str(idx).lower():
                return df.loc[idx]
    return None


def _latest(row) -> Optional[float]:
    """Return the most-recent non-NaN value in a financial row."""
    if row is None:
        return None
    for v in row.values:
        f = _safe_float(v)
        if f is not None:
            return f
    return None


def _trend(row, n: int = 4) -> List[Tuple[str, float]]:
    """Return up to n annual values as [(year, value)] sorted oldest → newest."""
    if row is None:
        return []
    pairs = [(str(k)[:4], _safe_float(v)) for k, v in zip(row.index, row.values)]
    pairs = [(y, v) for y, v in pairs if v is not None]
    return list(reversed(pairs[-n:]))


def _is_increasing(trend: List[Tuple[str, float]]) -> Optional[bool]:
    vals = [v for _, v in trend]
    if len(vals) < 2:
        return None
    return vals[-1] > vals[0]


def traffic_light(value: Optional[float], low_good: bool,
                  green_thresh: float, yellow_thresh: float) -> str:
    """
    🟢 / 🟡 / 🔴 / ⚪
    low_good=True  → smaller is better (P/E, D/E, pledgings …)
    low_good=False → larger is better (ROE, current ratio …)
    """
    if value is None:
        return "⚪"
    if low_good:
        return "🟢" if value <= green_thresh else ("🟡" if value <= yellow_thresh else "🔴")
    else:
        return "🟢" if value >= green_thresh else ("🟡" if value >= yellow_thresh else "🔴")


# ── Main computation ──────────────────────────────────────────────────────────

def compute_advanced_metrics(stock_data: dict) -> dict:
    info         = stock_data.get("info", {})
    income_stmt  = stock_data.get("income_stmt",  pd.DataFrame())
    balance_sheet= stock_data.get("balance_sheet", pd.DataFrame())
    cashflow     = stock_data.get("cashflow",      pd.DataFrame())

    # ── Income statement ─────────────────────────────────────────────────────
    revenue       = (_latest(_get_row(income_stmt, "Total Revenue", "Revenue"))
                     or _safe_float(info.get("totalRevenue")))
    gross_profit  = (_latest(_get_row(income_stmt, "Gross Profit"))
                     or _safe_float(info.get("grossProfits")))
    ebit          = _latest(_get_row(income_stmt, "EBIT", "Operating Income",
                                     "Earnings Before Interest And Taxes"))
    ebitda_val    = (_latest(_get_row(income_stmt, "EBITDA", "Normalized EBITDA"))
                     or _safe_float(info.get("ebitda")))
    net_income    = (_latest(_get_row(income_stmt, "Net Income",
                                      "Net Income Common Stockholders"))
                     or _safe_float(info.get("netIncomeToCommon")))

    int_row       = _get_row(income_stmt, "Interest Expense",
                             "Interest Expense Non Operating", "Net Interest Income")
    interest_exp  = abs(_latest(int_row)) if _latest(int_row) is not None else None

    # Fall back EBIT from operating margin × revenue
    if ebit is None:
        om = _safe_float(info.get("operatingMargins"))
        if om and revenue:
            ebit = om * revenue

    # ── Balance sheet ────────────────────────────────────────────────────────
    total_assets  = (_latest(_get_row(balance_sheet, "Total Assets"))
                     or _safe_float(info.get("totalAssets")))
    total_equity  = (_latest(_get_row(balance_sheet, "Stockholders Equity",
                                      "Total Equity Gross Minority Interest",
                                      "Common Stock Equity"))
                     or _safe_float(info.get("totalStockholderEquity")))
    total_debt    = (_latest(_get_row(balance_sheet, "Total Debt", "Long Term Debt",
                                      "Long Term Debt And Capital Lease Obligation"))
                     or _safe_float(info.get("totalDebt")))
    total_liab    = (_latest(_get_row(balance_sheet, "Total Liabilities Net Minority Interest",
                                      "Total Liabilities"))
                     or ((total_assets - total_equity)
                         if total_assets and total_equity else None))

    # ── Cash flow ────────────────────────────────────────────────────────────
    fcf_val       = _safe_float(info.get("freeCashflow"))
    op_cf_val     = _safe_float(info.get("operatingCashflow"))

    # ── Margins ──────────────────────────────────────────────────────────────
    gross_margin  = ((gross_profit / revenue) if gross_profit and revenue
                     else _safe_float(info.get("grossMargins")))
    ebit_margin   = ((ebit / revenue) if ebit and revenue
                     else _safe_float(info.get("operatingMargins")))
    net_margin    = ((net_income / revenue) if net_income and revenue
                     else _safe_float(info.get("profitMargins")))

    # ── Key ratios ───────────────────────────────────────────────────────────
    pe            = _safe_float(info.get("trailingPE"))
    forward_pe    = _safe_float(info.get("forwardPE"))
    pb            = _safe_float(info.get("priceToBook"))
    peg           = _safe_float(info.get("pegRatio"))
    # Compute PEG as fallback: P/E ÷ earnings growth (expressed as %)
    if peg is None and pe is not None:
        eg = _safe_float(info.get("earningsGrowth"))
        if eg and eg > 0:
            peg = pe / (eg * 100)
    # yfinance debtToEquity is stored as %, e.g. 102.63 means D/E = 1.0263
    de_raw        = _safe_float(info.get("debtToEquity"))
    de_ratio      = (de_raw / 100) if de_raw is not None else None   # actual ratio
    current_ratio = _safe_float(info.get("currentRatio"))
    roe           = _safe_float(info.get("returnOnEquity"))
    roa           = _safe_float(info.get("returnOnAssets"))

    # Interest Coverage = EBIT / Interest Expense
    interest_cov  = (ebit / interest_exp
                     if ebit and interest_exp and interest_exp > 0 else None)

    # ROIC = NOPAT / Invested Capital   (NOPAT = EBIT × (1 − tax))
    roic = None
    if ebit and total_equity is not None and total_debt is not None:
        nopat        = ebit * (1 - 0.21)
        invested_cap = total_equity + total_debt
        if invested_cap > 0:
            roic = nopat / invested_cap

    # Operating leverage: earnings growing faster than revenue
    rev_growth   = _safe_float(info.get("revenueGrowth"))
    earn_growth  = _safe_float(info.get("earningsGrowth"))
    op_leverage  = (earn_growth > rev_growth
                    if rev_growth is not None and earn_growth is not None else None)

    # EPS
    eps_ttm      = _safe_float(info.get("trailingEps"))
    eps_forward  = _safe_float(info.get("forwardEps"))
    current_price= _safe_float(info.get("currentPrice")
                               or info.get("regularMarketPrice")
                               or info.get("previousClose"))

    # ── Trend series ─────────────────────────────────────────────────────────
    revenue_trend     = _trend(_get_row(income_stmt, "Total Revenue", "Revenue"))
    net_income_trend  = _trend(_get_row(income_stmt, "Net Income",
                                        "Net Income Common Stockholders"))
    ebitda_trend      = _trend(_get_row(income_stmt, "EBITDA", "Normalized EBITDA"))
    eps_trend         = _trend(_get_row(income_stmt, "Basic EPS", "Diluted EPS", "EPS"))

    cashflow_trend    = _trend(_get_row(cashflow,
                                        "Operating Cash Flow",
                                        "Cash Flow From Continuing Operating Activities"))
    fcf_trend         = _trend(_get_row(cashflow, "Free Cash Flow"))

    # Compute FCF from OCF − Capex if not directly available
    if not fcf_trend:
        ocf_r   = _get_row(cashflow, "Operating Cash Flow",
                           "Cash Flow From Continuing Operating Activities")
        capex_r = _get_row(cashflow, "Capital Expenditure",
                           "Purchase Of PPE", "Capital Expenditures")
        if ocf_r is not None and capex_r is not None:
            ocf_d   = dict(zip(ocf_r.index, ocf_r.values))
            capex_d = dict(zip(capex_r.index, capex_r.values))
            combined = []
            for k in list(ocf_d.keys()):
                o = _safe_float(ocf_d.get(k))
                c = _safe_float(capex_d.get(k))
                if o is not None and c is not None:
                    combined.append((str(k)[:4], o + c))   # capex is negative
            fcf_trend = list(reversed(combined[-4:]))

    return {
        # Income
        "revenue": revenue, "gross_profit": gross_profit,
        "ebit": ebit, "ebitda": ebitda_val, "net_income": net_income,
        # Balance
        "total_assets": total_assets, "total_liabilities": total_liab,
        "total_equity": total_equity, "total_debt": total_debt,
        # Cash flow
        "fcf": fcf_val, "op_cashflow": op_cf_val,
        # Margins
        "gross_margin": gross_margin, "ebit_margin": ebit_margin, "net_margin": net_margin,
        # Valuation ratios
        "pe": pe, "forward_pe": forward_pe, "pb": pb, "peg": peg,
        # Leverage / liquidity
        "de_ratio": de_ratio, "current_ratio": current_ratio, "interest_cov": interest_cov,
        # Return metrics
        "roe": roe, "roa": roa, "roic": roic,
        # Growth / leverage
        "rev_growth": rev_growth, "earn_growth": earn_growth, "op_leverage": op_leverage,
        # EPS
        "eps_ttm": eps_ttm, "eps_forward": eps_forward, "current_price": current_price,
        # Trend series
        "revenue_trend": revenue_trend, "net_income_trend": net_income_trend,
        "ebitda_trend": ebitda_trend, "cashflow_trend": cashflow_trend,
        "fcf_trend": fcf_trend, "eps_trend": eps_trend,
        # Trend directions
        "cashflow_increasing":   _is_increasing(cashflow_trend),
        "net_profit_increasing": _is_increasing(net_income_trend),
        "ebitda_increasing":     _is_increasing(ebitda_trend),
        "revenue_increasing":    _is_increasing(revenue_trend),
    }


# ── Web-searched ownership / institutional data ───────────────────────────────

def fetch_ownership_data(
    ticker: str,
    company_name: str,
    market_name: str,
    sector: str,
    api_key: str,
) -> dict:
    """
    GPT-4o web search → structured JSON with ownership, institutional activity,
    industry P/E for intrinsic value, and beat-and-raise signal.
    """
    client = OpenAI(api_key=api_key)

    is_indian = any(x in market_name.lower() for x in ["india", "nse", "bse"])

    ownership_block = (
        '  "promoter_holdings_pct": <latest promoter/founder holding % as number or null>,\n'
        '  "promoter_pledgings_pct": <latest pledged shares % as number or null>,'
        if is_indian else
        '  "insider_ownership_pct": <management + director ownership % as number or null>,'
    )

    prompt = f"""Search the web for the most current data on {company_name} (ticker: {ticker}, exchange: {market_name}, sector: {sector}).

Return ONLY a valid JSON object — no markdown, no explanation:
{{
  "industry_avg_pe": <current median/average P/E for the {sector} sector as number, or null>,
{ownership_block}
  "institutional_trend": <"increasing", "decreasing", "stable", or null>,
  "mf_or_foreign_investment_entering": <true if mutual funds or foreign institutions are recently increasing position, false if decreasing, null if unknown>,
  "recent_beat_and_raise": <true if company beat earnings estimates AND raised guidance in most recent quarter, false if missed, null if unknown>,
  "beat_raise_details": <one-sentence description of most recent earnings result vs consensus estimate, or null>
}}"""

    try:
        response = client.responses.create(
            model="gpt-4o",
            input=prompt,
            tools=[{"type": "web_search_preview"}],
        )
        raw = response.output_text.strip()
        # Strip markdown fences if present
        if "```" in raw:
            for part in raw.split("```"):
                if "{" in part:
                    raw = part.lstrip("json\n").strip()
                    break
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        return json.loads(raw)
    except Exception:
        return {}

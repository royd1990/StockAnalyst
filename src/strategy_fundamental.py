"""
Fundamental Screening Strategy
===============================
Screens stocks by quality and growth fundamentals:
  - ROIC >= threshold
  - Operating Margin >= threshold
  - Positive FCF for 3 consecutive years
  - Net Debt / EBITDA <= threshold
  - Revenue CAGR (3yr) >= threshold
  - Earnings CAGR (3yr) >= threshold

All stocks are returned (including FAILs) so users can see partial matches.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional
import time as _time

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


def _get_row(df, *names):
    """Try multiple row-name variations on a financial-statement DataFrame.

    Returns the row as a Series, or None if no match is found.
    """
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


def _latest(row):
    """Extract the most recent non-NaN value from a financial-statement row Series."""
    if row is None:
        return None
    for val in row:
        f = _to_float(val)
        if f is not None:
            return f
    return None


def _cagr(start: float, end: float, years: float) -> Optional[float]:
    """Compound annual growth rate: (end/start)^(1/years) - 1.

    Returns None if start <= 0, end <= 0, or years < 1.
    Negative end values (e.g. losses) cannot produce a real CAGR.
    """
    if start is None or end is None:
        return None
    if start <= 0 or end <= 0 or years < 1:
        return None
    try:
        result = (end / start) ** (1.0 / years) - 1.0
        # Guard against complex results (shouldn't happen now, but be safe)
        if isinstance(result, complex):
            return None
        return float(result)
    except (ZeroDivisionError, ValueError, OverflowError, TypeError):
        return None


def _fetch_fundamental_data(ticker: str) -> Optional[dict]:
    """Fetch fundamental data for a single ticker.

    Makes 4 yfinance calls (info, income_stmt, balance_sheet, cashflow),
    each wrapped with rate_limit / rate_release.
    Retries up to 2 times on auth errors.
    """
    for attempt in range(3):
        gen = get_generation()

        # ── Call 1: .info ─────────────────────────────────────────────────
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

        name = info.get("shortName") or info.get("longName") or ticker
        sector = info.get("sector") or "—"
        industry = info.get("industry") or "—"
        currency = info.get("currency", "")
        mktcap = _to_float(info.get("marketCap")) or 0
        shares_outstanding = _to_float(info.get("sharesOutstanding"))

        # Valuation from info
        ev_ebitda = _to_float(info.get("enterpriseToEbitda"))
        trailing_pe = _to_float(info.get("trailingPE"))
        forward_pe = _to_float(info.get("forwardPE"))
        ps_ratio = _to_float(info.get("priceToSalesTrailing12Months"))
        op_margins_info = _to_float(info.get("operatingMargins"))
        ebitda_info = _to_float(info.get("ebitda"))
        total_debt_info = _to_float(info.get("totalDebt"))
        total_cash_info = _to_float(info.get("totalCash"))
        enterprise_value = _to_float(info.get("enterpriseValue"))
        eps = _to_float(info.get("trailingEps"))
        forward_eps = _to_float(info.get("forwardEps"))
        revenue_info = _to_float(info.get("totalRevenue"))

        # ── Call 2: .income_stmt ──────────────────────────────────────────
        rate_limit()
        try:
            income_stmt = stock.income_stmt
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        # ── Call 3: .balance_sheet ────────────────────────────────────────
        rate_limit()
        try:
            balance_sheet = stock.balance_sheet
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        # ── Call 4: .cashflow ─────────────────────────────────────────────
        rate_limit()
        try:
            cashflow = stock.cashflow
        except Exception as e:
            rate_release()
            if attempt < 2 and is_auth_error(e):
                on_auth_error(gen)
                _time.sleep(1 + attempt)
                continue
            return None
        rate_release()

        # ── Compute derived metrics ───────────────────────────────────────

        # EBIT from income statement
        ebit_row = _get_row(income_stmt, "EBIT", "Operating Income")
        ebit = _latest(ebit_row)

        # Revenue from income statement (for margin calc and CAGR)
        rev_row = _get_row(income_stmt, "Total Revenue", "Revenue")
        revenue_latest = _latest(rev_row)

        # Net Income from income statement (for earnings CAGR)
        ni_row = _get_row(income_stmt, "Net Income", "Net Income Common Stockholders")

        # Equity from balance sheet
        equity_row = _get_row(
            balance_sheet,
            "Stockholders Equity",
            "Total Equity Gross Minority Interest",
            "Common Stock Equity",
        )
        equity = _latest(equity_row)

        # Total Debt from balance sheet or info
        debt_row = _get_row(balance_sheet, "Total Debt", "Long Term Debt")
        total_debt = _latest(debt_row) if debt_row is not None else total_debt_info

        # Cash from balance sheet or info
        cash_row = _get_row(
            balance_sheet,
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments",
        )
        total_cash = _latest(cash_row) if cash_row is not None else total_cash_info

        # EBITDA — prefer info, fall back to income stmt
        ebitda_row = _get_row(income_stmt, "EBITDA", "Normalized EBITDA")
        ebitda = ebitda_info or _latest(ebitda_row)

        # ── ROIC ─────────────────────────────────────────────────────────
        roic = None
        if ebit is not None and equity is not None:
            nopat = ebit * (1.0 - 0.21)
            invested_capital = equity + (total_debt or 0)
            if invested_capital > 0:
                roic = nopat / invested_capital

        # ── Operating Margin ──────────────────────────────────────────────
        op_margin = op_margins_info  # already a decimal from info
        if op_margin is None and ebit is not None and revenue_latest and revenue_latest > 0:
            op_margin = ebit / revenue_latest

        # ── FCF history (3 years) ─────────────────────────────────────────
        ocf_row = _get_row(
            cashflow,
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "Cash Flow From Continuing Operating Activities",
        )
        capex_row = _get_row(cashflow, "Capital Expenditure", "Capital Expenditures")

        fcf_history = []
        if ocf_row is not None and capex_row is not None:
            # Columns are dates, most recent first — take up to 3
            for i in range(min(3, len(ocf_row))):
                ocf_val = _to_float(ocf_row.iloc[i])
                capex_val = _to_float(capex_row.iloc[i])
                if ocf_val is not None and capex_val is not None:
                    fcf_history.append(ocf_val - abs(capex_val))
                else:
                    fcf_history.append(None)

        fcf_3yr_positive = (
            len(fcf_history) >= 3
            and all(f is not None and f > 0 for f in fcf_history[:3])
        )
        fcf_display = "Yes" if fcf_3yr_positive else "No"

        # ── Net Debt / EBITDA ─────────────────────────────────────────────
        net_debt_ebitda = None
        net_debt = None
        if total_debt is not None and total_cash is not None:
            net_debt = total_debt - total_cash
        if net_debt is not None and ebitda and ebitda > 0:
            net_debt_ebitda = net_debt / ebitda

        # ── Revenue CAGR (3yr) ────────────────────────────────────────────
        rev_cagr = None
        if rev_row is not None and len(rev_row) >= 4:
            rev_end = _to_float(rev_row.iloc[0])
            rev_start = _to_float(rev_row.iloc[3])
            if rev_end is not None and rev_start is not None:
                rev_cagr = _cagr(rev_start, rev_end, 3)

        # ── Earnings CAGR (3yr) ───────────────────────────────────────────
        earn_cagr = None
        if ni_row is not None and len(ni_row) >= 4:
            ni_end = _to_float(ni_row.iloc[0])
            ni_start = _to_float(ni_row.iloc[3])
            if ni_end is not None and ni_start is not None:
                earn_cagr = _cagr(ni_start, ni_end, 3)

        # ── EV / Sales ────────────────────────────────────────────────────
        ev_sales = ps_ratio  # priceToSalesTrailing12Months is close enough
        if ev_sales is None and enterprise_value and revenue_latest and revenue_latest > 0:
            ev_sales = enterprise_value / revenue_latest

        return {
            "Ticker": ticker,
            "Name": name,
            "Sector": sector,
            "Industry": industry,
            "Currency": currency,
            "Price": round(price, 2),
            "Market Cap": mktcap,
            "Shares Outstanding": shares_outstanding,
            "ROIC": roic,
            "Op Margin": op_margin,
            "FCF 3yr Positive": fcf_3yr_positive,
            "FCF Display": fcf_display,
            "FCF History": fcf_history,
            "Net Debt/EBITDA": net_debt_ebitda,
            "Rev CAGR": rev_cagr,
            "Earn CAGR": earn_cagr,
            # Valuation & raw fields for downstream use
            "EV/EBITDA": ev_ebitda,
            "P/E": trailing_pe,
            "EV/Sales": ev_sales,
            "Forward PE": forward_pe,
            "EPS": eps,
            "Forward EPS": forward_eps,
            "Revenue": revenue_info or revenue_latest,
            "EBITDA": ebitda,
            "Total Debt": total_debt,
            "Total Cash": total_cash,
            "Net Debt": net_debt,
            "Enterprise Value": enterprise_value,
        }

    return None


def _apply_screen(row: dict, thresholds: dict) -> Optional[dict]:
    """Apply 6 fundamental quality rules and assign a signal.

    Returns a dict with all raw data, rule results, and signal.
    All stocks are returned (even FAIL) so the caller can display partial matches.
    """
    roic = row.get("ROIC")
    op_margin = row.get("Op Margin")
    fcf_3yr = row.get("FCF 3yr Positive")
    nd_ebitda = row.get("Net Debt/EBITDA")
    rev_cagr = row.get("Rev CAGR")
    earn_cagr = row.get("Earn CAGR")

    min_roic = thresholds["min_roic"]
    min_op_margin = thresholds["min_op_margin"]
    max_nd_ebitda = thresholds["max_net_debt_ebitda"]
    min_rev_cagr = thresholds["min_rev_cagr"]
    min_earn_cagr = thresholds["min_earn_cagr"]

    # Convert decimals to percentages for comparison — guard against non-real types
    def _safe_pct(val, decimals=1):
        if val is None or isinstance(val, complex):
            return None
        try:
            return round(float(val) * 100, decimals)
        except (TypeError, ValueError, OverflowError):
            return None

    def _safe_round(val, decimals=2):
        if val is None or isinstance(val, complex):
            return None
        try:
            return round(float(val), decimals)
        except (TypeError, ValueError, OverflowError):
            return None

    roic_pct = _safe_pct(roic)
    op_margin_pct = _safe_pct(op_margin)
    rev_cagr_pct = _safe_pct(rev_cagr)
    earn_cagr_pct = _safe_pct(earn_cagr)
    nd_ebitda_display = _safe_round(nd_ebitda)

    rules = []

    # Rule 1: ROIC >= min_roic %
    roic_passed = roic_pct is not None and roic_pct >= min_roic
    rules.append({
        "name": "ROIC",
        "value": roic_pct,
        "threshold": f">= {min_roic}%",
        "passed": roic_passed,
    })

    # Rule 2: Operating Margin >= min_op_margin %
    op_passed = op_margin_pct is not None and op_margin_pct >= min_op_margin
    rules.append({
        "name": "Operating Margin",
        "value": op_margin_pct,
        "threshold": f">= {min_op_margin}%",
        "passed": op_passed,
    })

    # Rule 3: Positive FCF for 3 consecutive years
    fcf_passed = bool(fcf_3yr)
    rules.append({
        "name": "FCF 3yr Positive",
        "value": row.get("FCF Display", "N/A"),
        "threshold": "Yes (3 consecutive years)",
        "passed": fcf_passed,
    })

    # Rule 4: Net Debt/EBITDA <= max
    nd_passed = nd_ebitda is not None and nd_ebitda <= max_nd_ebitda
    rules.append({
        "name": "Net Debt/EBITDA",
        "value": nd_ebitda_display,
        "threshold": f"<= {max_nd_ebitda}",
        "passed": nd_passed,
    })

    # Rule 5: Revenue CAGR >= min %
    rev_passed = rev_cagr_pct is not None and rev_cagr_pct >= min_rev_cagr
    rules.append({
        "name": "Revenue CAGR (3yr)",
        "value": rev_cagr_pct,
        "threshold": f">= {min_rev_cagr}%",
        "passed": rev_passed,
    })

    # Rule 6: Earnings CAGR >= min %
    earn_passed = earn_cagr_pct is not None and earn_cagr_pct >= min_earn_cagr
    rules.append({
        "name": "Earnings CAGR (3yr)",
        "value": earn_cagr_pct,
        "threshold": f">= {min_earn_cagr}%",
        "passed": earn_passed,
    })

    passed_count = sum(1 for r in rules if r["passed"])
    total_rules = 6

    if passed_count == 6:
        signal = "STRONG PASS"
    elif passed_count == 5:
        signal = "PASS"
    elif passed_count >= 3:
        signal = "PARTIAL"
    else:
        signal = "FAIL"

    return {
        "Ticker": row["Ticker"],
        "Name": row["Name"],
        "Sector": row["Sector"],
        "Industry": row["Industry"],
        "Currency": row["Currency"],
        "Price": row["Price"],
        "Market Cap": row["Market Cap"],
        "ROIC %": roic_pct,
        "Op Margin %": op_margin_pct,
        "FCF 3yr": row.get("FCF Display", "N/A"),
        "Net Debt/EBITDA": nd_ebitda_display,
        "Rev CAGR %": rev_cagr_pct,
        "Earn CAGR %": earn_cagr_pct,
        "Passed": f"{passed_count}/{total_rules}",
        "Signal": signal,
        "_rules": rules,
        "_passed_count": passed_count,
        "_raw": row,
    }


def run_fundamental_screen(
    tickers: List[str],
    min_roic: float = 12.0,
    min_op_margin: float = 10.0,
    require_positive_fcf_3yr: bool = True,
    max_net_debt_ebitda: float = 3.0,
    min_rev_cagr: float = 5.0,
    min_earn_cagr: float = 5.0,
    max_workers: int = 6,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Run the Fundamental Quality Screen on a list of tickers.

    Parameters
    ----------
    tickers              : list of ticker symbols
    min_roic             : minimum ROIC % (default 12)
    min_op_margin        : minimum operating margin % (default 10)
    require_positive_fcf_3yr : require 3 consecutive years of positive FCF (default True)
    max_net_debt_ebitda  : maximum Net Debt / EBITDA (default 3.0)
    min_rev_cagr         : minimum revenue CAGR % over 3 years (default 5)
    min_earn_cagr        : minimum earnings CAGR % over 3 years (default 5)
    max_workers          : parallel fetch threads
    progress_cb          : optional callback(done, total) for progress updates

    Returns a DataFrame of all screened stocks sorted by passed_count desc, then ROIC desc.
    Includes ALL stocks (even FAIL) so the user can see partial matches.
    """
    warmup()

    thresholds = {
        "min_roic": min_roic,
        "min_op_margin": min_op_margin,
        "require_positive_fcf_3yr": require_positive_fcf_3yr,
        "max_net_debt_ebitda": max_net_debt_ebitda,
        "min_rev_cagr": min_rev_cagr,
        "min_earn_cagr": min_earn_cagr,
    }

    results = []
    total = len(tickers)
    done = 0
    _CRUMB_REFRESH_EVERY = 50

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_fetch_fundamental_data, t): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            done += 1
            if progress_cb:
                progress_cb(done, total)
            if done % _CRUMB_REFRESH_EVERY == 0:
                refresh_crumb()

            if row is None:
                continue

            screened = _apply_screen(row, thresholds)
            if screened is not None:
                results.append(screened)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # Sort by passed_count descending, then ROIC descending
    df = df.sort_values(
        ["_passed_count", "ROIC %"],
        ascending=[False, False],
        na_position="last",
    )
    df = df.drop(columns=["_passed_count", "_rules"], errors="ignore")

    return df.reset_index(drop=True)

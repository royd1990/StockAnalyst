"""
Pure computation module for stock valuation models.

No yfinance dependency, no I/O. Takes pre-fetched financial data and user
assumptions, returns valuation results as dataclasses.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
import pandas as pd
import math


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DCFInputs:
    fcf_latest: float           # FCF0 (latest free cash flow)
    growth_rate: float          # annual FCF growth as decimal (e.g., 0.10 = 10%)
    discount_rate: float        # WACC as decimal (e.g., 0.10 = 10%)
    terminal_growth: float      # perpetual growth as decimal (e.g., 0.03 = 3%)
    forecast_years: int         # explicit forecast period (e.g., 5)
    net_debt: float             # Total Debt - Cash (can be negative if cash > debt)
    shares_outstanding: float   # diluted shares


@dataclass
class DCFResult:
    forecasted_fcfs: List[Tuple[int, float]]    # [(year, fcf), ...]
    pv_fcfs: List[Tuple[int, float]]            # [(year, pv), ...]
    terminal_value: float                        # undiscounted terminal value
    pv_terminal: float                           # present value of terminal
    enterprise_value: float                      # sum of PV(FCFs) + PV(Terminal)
    equity_value: float                          # EV - net debt
    value_per_share: float                       # equity / shares
    current_price: float                         # for reference
    upside_pct: float                            # (value_per_share / current_price - 1) * 100


@dataclass
class RelativeValResult:
    model_name: str             # "EV/EBITDA", "P/E", "EV/Sales"
    multiple_used: float
    base_metric: float          # the EBITDA, EPS, or Revenue used
    implied_ev: Optional[float]         # for EV-based models
    implied_equity: Optional[float]
    implied_share_price: float
    current_price: float
    upside_pct: float           # (implied / current - 1) * 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0) -> float:
    """Coerce a value to float, guarding against None / NaN / Inf."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def build_dcf_inputs(raw_data: dict) -> DCFInputs:
    """Extract DCF inputs from the raw data dict returned by
    strategy_fundamental._fetch_fundamental_data.

    raw_data contains keys like: 'fcf_latest', 'rev_cagr', 'net_debt',
    'shares_outstanding', 'total_debt', 'total_cash', 'ebitda', 'revenue',
    'net_income', 'price', etc.

    Defaults:
    - fcf_latest: from raw_data['fcf_latest'], fallback to
      operating_cashflow - abs(capex)
    - growth_rate: from raw_data['rev_cagr'] if available, else 0.10
    - discount_rate: 0.10
    - terminal_growth: 0.03
    - forecast_years: 5
    - net_debt: raw_data['net_debt'] or (total_debt - total_cash)
    - shares_outstanding: raw_data['shares_outstanding']
    """
    # FCF
    fcf = _safe_float(raw_data.get("fcf_latest"))
    if fcf == 0.0:
        op_cf = _safe_float(raw_data.get("operating_cashflow", 0))
        capex = abs(_safe_float(raw_data.get("capex", 0)))
        fcf = op_cf - capex

    # Growth rate
    rev_cagr = raw_data.get("rev_cagr")
    if rev_cagr is not None:
        growth_rate = _safe_float(rev_cagr, default=0.10)
    else:
        growth_rate = 0.10

    # Net debt
    net_debt = raw_data.get("net_debt")
    if net_debt is not None:
        net_debt = _safe_float(net_debt)
    else:
        total_debt = _safe_float(raw_data.get("total_debt", 0))
        total_cash = _safe_float(raw_data.get("total_cash", 0))
        net_debt = total_debt - total_cash

    shares = _safe_float(raw_data.get("shares_outstanding", 0))

    return DCFInputs(
        fcf_latest=fcf,
        growth_rate=growth_rate,
        discount_rate=0.10,
        terminal_growth=0.03,
        forecast_years=5,
        net_debt=net_debt,
        shares_outstanding=shares,
    )


def build_relative_inputs(raw_data: dict) -> dict:
    """Extract inputs for relative valuation models from raw screening data.

    Returns dict with:
    - 'ebitda': float or None
    - 'eps': float or None (trailing)
    - 'forward_eps': float or None
    - 'revenue': float or None
    - 'net_debt': float
    - 'shares_outstanding': float
    - 'current_price': float
    - 'current_ev_ebitda': float or None (current company multiple)
    - 'current_pe': float or None
    - 'current_ev_sales': float or None
    """
    def _maybe_float(key):
        v = raw_data.get(key)
        if v is None:
            return None
        f = _safe_float(v, default=None)
        return f

    net_debt_val = raw_data.get("net_debt")
    if net_debt_val is not None:
        net_debt = _safe_float(net_debt_val)
    else:
        total_debt = _safe_float(raw_data.get("total_debt", 0))
        total_cash = _safe_float(raw_data.get("total_cash", 0))
        net_debt = total_debt - total_cash

    return {
        "ebitda": _maybe_float("ebitda"),
        "eps": _maybe_float("eps"),
        "forward_eps": _maybe_float("forward_eps"),
        "revenue": _maybe_float("revenue"),
        "net_debt": net_debt,
        "shares_outstanding": _safe_float(raw_data.get("shares_outstanding", 0)),
        "current_price": _safe_float(raw_data.get("price", 0)),
        "current_ev_ebitda": _maybe_float("ev_ebitda"),
        "current_pe": _maybe_float("pe_ratio"),
        "current_ev_sales": _maybe_float("ev_sales"),
    }


# ---------------------------------------------------------------------------
# Core valuation functions
# ---------------------------------------------------------------------------

def compute_dcf(inputs: DCFInputs, current_price: float) -> DCFResult:
    """Standard DCF valuation.

    For each year t (1 to forecast_years):
        FCF_t = fcf_latest * (1 + growth_rate)^t
        PV_t  = FCF_t / (1 + discount_rate)^t

    Terminal Value = FCF_n * (1 + terminal_growth) / (discount_rate - terminal_growth)
    PV(Terminal)   = Terminal Value / (1 + discount_rate)^n

    Enterprise Value = sum(PV_t) + PV(Terminal)
    Equity Value     = EV - net_debt
    Value Per Share  = Equity Value / shares_outstanding
    """
    if inputs.terminal_growth >= inputs.discount_rate:
        raise ValueError(
            f"terminal_growth ({inputs.terminal_growth}) must be less than "
            f"discount_rate ({inputs.discount_rate})"
        )
    if inputs.shares_outstanding <= 0:
        raise ValueError(
            f"shares_outstanding must be > 0, got {inputs.shares_outstanding}"
        )

    n = inputs.forecast_years
    forecasted_fcfs: List[Tuple[int, float]] = []
    pv_fcfs: List[Tuple[int, float]] = []

    for t in range(1, n + 1):
        fcf_t = inputs.fcf_latest * (1 + inputs.growth_rate) ** t
        pv_t = fcf_t / (1 + inputs.discount_rate) ** t
        forecasted_fcfs.append((t, fcf_t))
        pv_fcfs.append((t, pv_t))

    fcf_n = forecasted_fcfs[-1][1]
    terminal_value = fcf_n * (1 + inputs.terminal_growth) / (
        inputs.discount_rate - inputs.terminal_growth
    )
    pv_terminal = terminal_value / (1 + inputs.discount_rate) ** n

    sum_pv = sum(pv for _, pv in pv_fcfs)
    enterprise_value = sum_pv + pv_terminal
    equity_value = enterprise_value - inputs.net_debt
    value_per_share = equity_value / inputs.shares_outstanding

    upside_pct = (
        (value_per_share / current_price - 1) * 100
        if current_price > 0
        else 0.0
    )

    return DCFResult(
        forecasted_fcfs=forecasted_fcfs,
        pv_fcfs=pv_fcfs,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        current_price=current_price,
        upside_pct=upside_pct,
    )


def dcf_sensitivity(
    inputs: DCFInputs,
    current_price: float,
    discount_rates: Optional[List[float]] = None,
    terminal_growths: Optional[List[float]] = None,
) -> pd.DataFrame:
    """Return DataFrame: index = discount rates (as "8%", "9%", ...),
    columns = terminal growth rates (as "1%", "2%", ...),
    cells = implied value per share (float, rounded to 2 decimals).

    Catches errors (e.g., terminal_growth >= discount_rate) and puts None
    in those cells.
    """
    if discount_rates is None:
        discount_rates = [0.08, 0.09, 0.10, 0.11, 0.12]
    if terminal_growths is None:
        terminal_growths = [0.01, 0.02, 0.03, 0.04, 0.05]

    col_labels = [f"{int(round(tg * 100))}%" for tg in terminal_growths]
    row_labels = [f"{int(round(dr * 100))}%" for dr in discount_rates]

    rows = []
    for dr in discount_rates:
        row = []
        for tg in terminal_growths:
            try:
                modified = DCFInputs(
                    fcf_latest=inputs.fcf_latest,
                    growth_rate=inputs.growth_rate,
                    discount_rate=dr,
                    terminal_growth=tg,
                    forecast_years=inputs.forecast_years,
                    net_debt=inputs.net_debt,
                    shares_outstanding=inputs.shares_outstanding,
                )
                result = compute_dcf(modified, current_price)
                row.append(round(result.value_per_share, 2))
            except (ValueError, ZeroDivisionError):
                row.append(None)
        rows.append(row)

    return pd.DataFrame(rows, index=row_labels, columns=col_labels)


def reverse_dcf(
    fcf_latest: float,
    discount_rate: float,
    terminal_growth: float,
    forecast_years: int,
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
) -> float:
    """Find the implied FCF growth rate that makes DCF value = current market price.

    Uses bisection search between -50% and +100% growth.
    Returns the implied growth rate as a decimal.
    If no solution found in range, return the boundary.
    """
    if shares_outstanding <= 0 or current_price <= 0:
        return 0.0

    target_equity = current_price * shares_outstanding
    target_ev = target_equity + net_debt

    def _ev_for_growth(g: float) -> Optional[float]:
        """Compute enterprise value for a given growth rate."""
        try:
            pv_sum = 0.0
            for t in range(1, forecast_years + 1):
                fcf_t = fcf_latest * (1 + g) ** t
                pv_sum += fcf_t / (1 + discount_rate) ** t

            fcf_n = fcf_latest * (1 + g) ** forecast_years
            if discount_rate <= terminal_growth:
                return None
            tv = fcf_n * (1 + terminal_growth) / (discount_rate - terminal_growth)
            pv_tv = tv / (1 + discount_rate) ** forecast_years
            return pv_sum + pv_tv
        except (OverflowError, ZeroDivisionError):
            return None

    lo, hi = -0.50, 1.00
    # 60 iterations of bisection gives precision ~2^-60
    for _ in range(60):
        mid = (lo + hi) / 2.0
        ev_mid = _ev_for_growth(mid)
        if ev_mid is None:
            hi = mid
            continue
        if ev_mid < target_ev:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2.0


def ev_ebitda_valuation(
    ebitda: float,
    multiple: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
) -> RelativeValResult:
    """EV = EBITDA * multiple. Equity = EV - net_debt. Price = Equity / shares."""
    implied_ev = ebitda * multiple
    implied_equity = implied_ev - net_debt
    implied_price = implied_equity / shares_outstanding if shares_outstanding > 0 else 0.0
    upside = (implied_price / current_price - 1) * 100 if current_price > 0 else 0.0

    return RelativeValResult(
        model_name="EV/EBITDA",
        multiple_used=multiple,
        base_metric=ebitda,
        implied_ev=implied_ev,
        implied_equity=implied_equity,
        implied_share_price=implied_price,
        current_price=current_price,
        upside_pct=upside,
    )


def pe_valuation(
    eps: float,
    multiple: float,
    current_price: float,
) -> RelativeValResult:
    """Implied price = EPS * P/E multiple."""
    implied_price = eps * multiple
    upside = (implied_price / current_price - 1) * 100 if current_price > 0 else 0.0

    return RelativeValResult(
        model_name="P/E",
        multiple_used=multiple,
        base_metric=eps,
        implied_ev=None,
        implied_equity=None,
        implied_share_price=implied_price,
        current_price=current_price,
        upside_pct=upside,
    )


def ev_sales_valuation(
    revenue: float,
    multiple: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
) -> RelativeValResult:
    """EV = Revenue * multiple. Equity = EV - net_debt. Price = Equity / shares."""
    implied_ev = revenue * multiple
    implied_equity = implied_ev - net_debt
    implied_price = implied_equity / shares_outstanding if shares_outstanding > 0 else 0.0
    upside = (implied_price / current_price - 1) * 100 if current_price > 0 else 0.0

    return RelativeValResult(
        model_name="EV/Sales",
        multiple_used=multiple,
        base_metric=revenue,
        implied_ev=implied_ev,
        implied_equity=implied_equity,
        implied_share_price=implied_price,
        current_price=current_price,
        upside_pct=upside,
    )


def valuation_summary(
    dcf_result: Optional[DCFResult],
    relative_results: List[RelativeValResult],
    current_price: float,
) -> dict:
    """Combine all models into a summary.

    Returns dict with:
    - 'models': list of {"name": str, "implied_price": float, "upside_pct": float}
    - 'avg_implied_price': float (average of all valid models)
    - 'median_implied_price': float
    - 'min_implied_price': float
    - 'max_implied_price': float
    - 'current_price': float
    - 'avg_upside_pct': float
    """
    models: List[Dict] = []

    if dcf_result is not None:
        models.append({
            "name": "DCF",
            "implied_price": dcf_result.value_per_share,
            "upside_pct": dcf_result.upside_pct,
        })

    for rr in relative_results:
        models.append({
            "name": rr.model_name,
            "implied_price": rr.implied_share_price,
            "upside_pct": rr.upside_pct,
        })

    prices = [m["implied_price"] for m in models]

    if not prices:
        return {
            "models": models,
            "avg_implied_price": 0.0,
            "median_implied_price": 0.0,
            "min_implied_price": 0.0,
            "max_implied_price": 0.0,
            "current_price": current_price,
            "avg_upside_pct": 0.0,
        }

    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    if n % 2 == 1:
        median_price = sorted_prices[n // 2]
    else:
        median_price = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2.0

    avg_price = sum(prices) / n
    avg_upside = (avg_price / current_price - 1) * 100 if current_price > 0 else 0.0

    return {
        "models": models,
        "avg_implied_price": avg_price,
        "median_implied_price": median_price,
        "min_implied_price": min(prices),
        "max_implied_price": max(prices),
        "current_price": current_price,
        "avg_upside_pct": avg_upside,
    }

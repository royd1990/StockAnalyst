import yfinance as yf
import pandas as pd
from typing import Any, Dict, Optional


def get_stock_data(ticker: str) -> Dict[str, Any]:
    """Fetch comprehensive stock data using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Validate we got real data
        if not info:
            return {}
        has_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or info.get("navPrice")
        )
        has_name = info.get("longName") or info.get("shortName") or info.get("symbol")
        if not has_price and not has_name:
            return {}

        history = pd.DataFrame()
        try:
            history = stock.history(period="1y")
        except Exception:
            pass

        income_stmt = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

        try:
            income_stmt = stock.income_stmt
        except Exception:
            pass
        try:
            balance_sheet = stock.balance_sheet
        except Exception:
            pass
        try:
            cashflow = stock.cashflow
        except Exception:
            pass

        return {
            "info": info,
            "history": history,
            "income_stmt": income_stmt,
            "balance_sheet": balance_sheet,
            "cashflow": cashflow,
        }
    except Exception:
        return {}


def _safe_float(val) -> Optional[float]:
    """Safely convert a value to float, returning None for invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


def format_currency(num, symbol: str = "$") -> str:
    """Format a number as currency with K/M/B/T suffixes."""
    val = _safe_float(num)
    if val is None:
        return "N/A"
    sign = "-" if val < 0 else ""
    abs_val = abs(val)
    if abs_val >= 1e12:
        return f"{symbol}{sign}{abs_val / 1e12:.2f}T"
    elif abs_val >= 1e9:
        return f"{symbol}{sign}{abs_val / 1e9:.2f}B"
    elif abs_val >= 1e6:
        return f"{symbol}{sign}{abs_val / 1e6:.2f}M"
    elif abs_val >= 1e3:
        return f"{symbol}{sign}{abs_val / 1e3:.2f}K"
    else:
        return f"{symbol}{sign}{abs_val:.2f}"


def format_percent(num) -> str:
    """Format a decimal as a percentage."""
    val = _safe_float(num)
    if val is None:
        return "N/A"
    return f"{val * 100:.2f}%"


def format_ratio(num, decimals: int = 2) -> str:
    """Format a number as a ratio."""
    val = _safe_float(num)
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}x"


def format_number(num) -> str:
    """Format a plain number with K/M/B/T suffixes (no currency symbol)."""
    val = _safe_float(num)
    if val is None:
        return "N/A"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}{abs_val / 1e12:.2f}T"
    elif abs_val >= 1e9:
        return f"{sign}{abs_val / 1e9:.2f}B"
    elif abs_val >= 1e6:
        return f"{sign}{abs_val / 1e6:.2f}M"
    elif abs_val >= 1e3:
        return f"{sign}{abs_val / 1e3:.2f}K"
    else:
        return f"{sign}{abs_val:.2f}"


def format_price(num, symbol: str = "$") -> str:
    """Format a per-share price."""
    val = _safe_float(num)
    if val is None:
        return "N/A"
    return f"{symbol}{val:.2f}"


def _compute_dividend_yield(info: dict) -> str:
    """
    yfinance is inconsistent: for some tickers `dividendYield` is a decimal ratio
    (0.004 = 0.4%), for others it's already expressed as a percentage value (0.4 = 0.4%).
    Compute from dividendRate / currentPrice when possible, then fall back.
    """
    rate = _safe_float(info.get("dividendRate"))
    price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))
    if rate is not None and price and price > 0:
        return f"{rate / price * 100:.2f}%"
    raw = _safe_float(info.get("dividendYield"))
    if raw is None:
        return "N/A"
    # If raw < 0.5 it is likely already a proper decimal ratio (e.g. 0.004 → 0.4%)
    # If raw >= 0.5 yfinance returned it as a human-readable % (e.g. 0.4 → 0.4%)
    if raw >= 0.5:
        return f"{raw:.2f}%"
    return f"{raw * 100:.2f}%"


def get_key_metrics(info: dict, currency_symbol: str = "$") -> dict:
    """Extract and format key fundamental metrics from yfinance info dict."""
    return {
        "Valuation": {
            "Market Cap": format_currency(info.get("marketCap"), currency_symbol),
            "Enterprise Value": format_currency(info.get("enterpriseValue"), currency_symbol),
            "P/E Ratio (TTM)": format_ratio(info.get("trailingPE")),
            "Forward P/E": format_ratio(info.get("forwardPE")),
            "PEG Ratio": format_ratio(info.get("pegRatio")),
            "P/S Ratio (TTM)": format_ratio(info.get("priceToSalesTrailing12Months")),
            "Price / Book": format_ratio(info.get("priceToBook")),
            "EV / EBITDA": format_ratio(info.get("enterpriseToEbitda")),
        },
        "Profitability": {
            "Revenue (TTM)": format_currency(info.get("totalRevenue"), currency_symbol),
            "Gross Margin": format_percent(info.get("grossMargins")),
            "Operating Margin": format_percent(info.get("operatingMargins")),
            "Net Profit Margin": format_percent(info.get("profitMargins")),
            "ROE": format_percent(info.get("returnOnEquity")),
            "ROA": format_percent(info.get("returnOnAssets")),
            "Free Cash Flow": format_currency(info.get("freeCashflow"), currency_symbol),
            "EBITDA": format_currency(info.get("ebitda"), currency_symbol),
        },
        "Growth": {
            "Revenue Growth (YoY)": format_percent(info.get("revenueGrowth")),
            "Earnings Growth (YoY)": format_percent(info.get("earningsGrowth")),
            "Earnings Quarterly Growth": format_percent(info.get("earningsQuarterlyGrowth")),
            "Revenue Per Share": format_price(info.get("revenuePerShare"), currency_symbol),
        },
        "Per Share": {
            "EPS (TTM)": format_price(info.get("trailingEps"), currency_symbol),
            "Forward EPS": format_price(info.get("forwardEps"), currency_symbol),
            "Book Value / Share": format_price(info.get("bookValue"), currency_symbol),
            "Dividend / Share": format_price(info.get("dividendRate"), currency_symbol),
            "Dividend Yield": _compute_dividend_yield(info),
            "Payout Ratio": format_percent(info.get("payoutRatio")),
        },
        "Financial Health": {
            "Total Cash": format_currency(info.get("totalCash"), currency_symbol),
            "Total Debt": format_currency(info.get("totalDebt"), currency_symbol),
            "Debt / Equity": format_ratio(info.get("debtToEquity")),
            "Current Ratio": format_ratio(info.get("currentRatio")),
            "Quick Ratio": format_ratio(info.get("quickRatio")),
            "Operating Cash Flow": format_currency(info.get("operatingCashflow"), currency_symbol),
        },
        "Market Statistics": {
            "Beta": f"{_safe_float(info.get('beta')):.2f}" if _safe_float(info.get("beta")) is not None else "N/A",
            "52-Week High": format_price(info.get("fiftyTwoWeekHigh"), currency_symbol),
            "52-Week Low": format_price(info.get("fiftyTwoWeekLow"), currency_symbol),
            "Avg Volume (3M)": format_number(info.get("averageVolume")),
            "Shares Outstanding": format_number(info.get("sharesOutstanding")),
            "Short % of Float": format_percent(info.get("shortPercentOfFloat")),
            "Analyst Target Price": format_price(info.get("targetMeanPrice"), currency_symbol),
            "# Analyst Opinions": str(info.get("numberOfAnalystOpinions", "N/A")),
        },
    }


def get_metrics_summary_text(metrics: dict) -> str:
    """Convert metrics dict to a readable text summary for the AI prompt."""
    lines = []
    for category, items in metrics.items():
        lines.append(f"\n{category}:")
        for name, value in items.items():
            if value != "N/A":
                lines.append(f"  • {name}: {value}")
    return "\n".join(lines)

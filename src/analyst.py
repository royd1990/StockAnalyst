import openai
from openai import OpenAI
from typing import Generator

from src.stock_data import get_metrics_summary_text


def analyze_stock(
    ticker: str,
    company_name: str,
    sector: str,
    market_name: str,
    metrics: dict,
    api_key: str,
) -> Generator[str, None, None]:
    """
    Streaming generator that yields analysis text chunks.
    Uses OpenAI GPT-4o with the web_search_preview tool for real-time fundamental analysis.
    """
    client = OpenAI(api_key=api_key)

    metrics_text = get_metrics_summary_text(metrics)

    prompt = f"""You are a senior equity research analyst at a top-tier investment bank. \
Perform a comprehensive fundamental analysis of **{company_name}** (ticker: `{ticker}`), \
listed on {market_name}. Sector/Industry: {sector if sector.strip(" -") else "N/A"}.

**Current Financial Metrics (from live market data):**
{metrics_text}

Please search the web for the latest information about this company — including recent earnings \
reports, news, analyst upgrades/downgrades, management guidance, and any significant events — \
then provide a thorough investment analysis structured as follows:

## 1. Company Snapshot
Concise description of the business model, key products/services, revenue mix, and geographic exposure.

## 2. Recent Performance & News
Latest quarterly earnings results vs. expectations, revenue/EPS trends, management guidance, \
and any major recent developments (M&A, regulatory news, product launches, etc.).

## 3. Growth Catalysts
Specific near-term and long-term drivers of growth. Include addressable market size where relevant.

## 4. Risk Factors
The top 3–5 risks that could impair the investment thesis. Be specific and candid.

## 5. Competitive Landscape
Market position, key competitors, and sustainable competitive advantages (moats) — or lack thereof.

## 6. Financial Health Assessment
Quality of the balance sheet, cash generation capability, debt levels, and capital allocation \
track record (dividends, buybacks, capex).

## 7. Valuation Analysis
Using the provided metrics and comparable companies / sector averages, assess whether the stock \
is **overvalued**, **fairly valued**, or **undervalued**. Justify with specific numbers.

## 8. Investment Recommendation

Provide a clear recommendation in the following format:

| Field | Detail |
|---|---|
| **Recommendation** | BUY / HOLD / SELL |
| **Conviction Level** | High / Medium / Low |
| **Investment Horizon** | Short-term (<1yr) / Medium-term (1–3yr) / Long-term (3yr+) |
| **Estimated Fair Value Range** | {ticker} price range |
| **Key Upside Catalyst** | Single most important catalyst |
| **Key Downside Risk** | Single most important risk |

End with a one-paragraph **Investment Summary** suitable for a client briefing note.

Be data-driven, specific, and actionable. Use numbers wherever possible."""

    try:
        with client.responses.stream(
            model="gpt-4o",
            input=prompt,
            tools=[{"type": "web_search_preview"}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    except openai.AuthenticationError:
        yield "\n\n❌ **Authentication Error**: Invalid API key. Please check your OpenAI API key in the sidebar."
    except openai.RateLimitError:
        yield "\n\n⚠️ **Rate Limit**: API rate limit reached. Please wait a moment and try again."
    except openai.APIStatusError as e:
        yield f"\n\n❌ **API Error ({e.status_code})**: {e.message}"
    except Exception as e:
        yield f"\n\n❌ **Unexpected Error**: {str(e)}"

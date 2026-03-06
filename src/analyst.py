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
        stream = client.responses.create(
            model="gpt-4o",
            input=prompt,
            tools=[{"type": "web_search_preview"}],
            stream=True,
        )
        for event in stream:
            if getattr(event, "type", None) == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta:
                    yield delta

    except openai.AuthenticationError:
        yield "\n\n❌ **Authentication Error**: Invalid API key. Please check your OpenAI API key in the sidebar."
    except openai.RateLimitError:
        yield "\n\n⚠️ **Rate Limit**: API rate limit reached. Please wait a moment and try again."
    except openai.APIStatusError as e:
        yield f"\n\n❌ **API Error ({e.status_code})**: {e.message}"
    except Exception as e:
        yield f"\n\n❌ **Unexpected Error**: {str(e)}"


def research_stock(
    ticker: str,
    company_name: str,
    sector: str,
    market_name: str,
    current_price: str,
    api_key: str,
) -> Generator[str, None, None]:
    """
    Streaming generator for the Research tab.
    Searches the web for news, concalls, SWOT, analyst views, and macro context.
    """
    client = OpenAI(api_key=api_key)

    prompt = f"""You are a senior equity research analyst. Conduct deep-dive research on \
**{company_name}** (ticker: `{ticker}`, exchange: {market_name}, sector: {sector if sector.strip(" -") else "N/A"}, \
current price: {current_price}).

Search the web thoroughly for the most current information — prioritise sources published in the \
last 90 days — and produce the following research report:

## 1. Latest News & Developments
Summarise the 5–8 most significant recent news items (date + source + key takeaway each). \
Cover corporate actions, regulatory events, product launches, partnerships, legal matters, \
and any management changes.

## 2. Earnings Calls & Management Commentary
Summarise the most recent earnings call / investor day / concall:
- Reported revenue and EPS vs analyst consensus
- Management guidance for next quarter and full year
- Key themes and phrases used by management
- Questions raised by analysts and management responses

## 3. SWOT Analysis
Provide a structured SWOT:
- **Strengths** — 3–4 durable competitive advantages
- **Weaknesses** — 3–4 internal vulnerabilities or gaps
- **Opportunities** — 3–4 addressable growth vectors
- **Threats** — 3–4 external risks (competitive, regulatory, macro)

## 4. Analyst Sentiment & Price Targets
- Current consensus rating (Buy / Hold / Sell split)
- Range of analyst price targets (low / median / high)
- Recent rating changes or initiations (last 60 days)
- Key bull and bear arguments from sell-side research

## 5. Macro & Geopolitical Context
How is the current global macro environment — including interest rates, inflation, \
currency trends, trade policy, geopolitical tensions, and sector-specific tailwinds/headwinds — \
affecting this company's near-term and medium-term outlook? Be specific about which macro \
factors are most material to this stock.

---
Be specific, cite figures where available, and flag uncertainty where data is limited. \
Structure each section with clear headers and bullet points."""

    try:
        stream = client.responses.create(
            model="gpt-4o",
            input=prompt,
            tools=[{"type": "web_search_preview"}],
            stream=True,
        )
        for event in stream:
            if getattr(event, "type", None) == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta:
                    yield delta

    except openai.AuthenticationError:
        yield "\n\n❌ **Authentication Error**: Invalid API key."
    except openai.RateLimitError:
        yield "\n\n⚠️ **Rate Limit**: API rate limit reached. Please wait and retry."
    except openai.APIStatusError as e:
        yield f"\n\n❌ **API Error ({e.status_code})**: {e.message}"
    except Exception as e:
        yield f"\n\n❌ **Unexpected Error**: {str(e)}"

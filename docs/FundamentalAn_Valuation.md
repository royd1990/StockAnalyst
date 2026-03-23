# Stock Research Feature: Product and Implementation Strategy

## Goal

Build a **stock research workflow** inside the app with three major stages:

1. **Fundamental screening**
2. **Valuation analysis**
3. **Competition / peer comparison**

The system should help a user:
- filter stocks based on quality and growth,
- estimate intrinsic value using multiple valuation models,
- compare the result with current market pricing,
- analyze competitors and peer valuation multiples.

---

# 1. Fundamental Screening

## Objective

Create a configurable stock screener that filters companies based on business quality, growth, and balance sheet strength.

The screener should support:
- **default thresholds**
- **user-editable thresholds**
- **pass/fail output**
- **explanation of which rule passed or failed**

---

## 1.1 Screening Categories

### A. Quality Filters

Default conditions:

- **ROIC > 12%**
- **Operating margin > 10%**
- **Positive free cash flow in each of the last 3 years**
- **Net Debt / EBITDA < 3**

### B. Growth Filters

Default conditions:

- **Revenue growth > 5% annually**  
  Use a **3–5 year average**
- **Earnings growth > 5% annually**
- **Promoter holding trend is increasing**
- **FIIs or mutual funds are accumulating / investing**

### C. General Design Requirements

- Thresholds should be configurable by the user.
- Defaults should be pre-filled in the UI.
- The screener should show:
  - raw metric values,
  - threshold values,
  - pass/fail status,
  - optional confidence or data availability indicator.

---

## 1.2 Key Metric Definitions

### ROIC
**Return on Invested Capital**

A common formulation is:

\[
ROIC = \frac{NOPAT}{Invested\ Capital}
\]

Where:
- **NOPAT** = EBIT × (1 - tax rate)
- **Invested Capital** = Equity + Debt - Excess Cash  
  (exact definition may vary by implementation)

---

### Operating Margin

\[
Operating\ Margin = \frac{Operating\ Income}{Revenue}
\]

---

### Free Cash Flow (FCF)

Two acceptable forms:

#### Formula 1
\[
FCF = Operating\ Cash\ Flow - Capital\ Expenditure
\]

#### Formula 2
\[
FCF = EBIT(1 - Tax\ Rate) + Depreciation\ \&\ Amortization - Capital\ Expenditure - Change\ in\ Working\ Capital
\]

Interpretation:
- start with operating profit,
- subtract taxes,
- add back non-cash charges,
- subtract reinvestment required to sustain and grow the business.

---

### Net Debt / EBITDA

\[
Net\ Debt / EBITDA = \frac{Total\ Debt - Cash\ \&\ Equivalents}{EBITDA}
\]

---

### Revenue Growth

Use either:
- CAGR over a selected period, or
- average annual growth over 3–5 years.

Recommended:

\[
Revenue\ CAGR = \left(\frac{Revenue_{end}}{Revenue_{start}}\right)^{1/n} - 1
\]

---

### Earnings Growth

Use CAGR for:
- EPS, or
- net income, depending on data quality and consistency.

\[
Earnings\ CAGR = \left(\frac{Earnings_{end}}{Earnings_{start}}\right)^{1/n} - 1
\]

---

### Promoter / FII / MF Trend

These are ownership trend signals.

The system should detect whether:
- promoter holding is increasing,
- FIIs are increasing ownership,
- mutual funds are increasing ownership.

This can be implemented as:
- latest quarter vs previous quarter,
- trailing 4-quarter slope,
- or a simple trend classification:
  - increasing
  - stable
  - decreasing

---

# 2. Valuation Engine

## Objective

For stocks that pass the screener, provide valuation using multiple models:

1. **DCF valuation**
2. **EV / EBITDA valuation**
3. **P/E valuation**
4. **EV / Sales valuation**

The app should allow the user to compare:
- intrinsic value,
- current market price,
- implied upside/downside,
- what assumptions justify the current market price.

---

## 2.1 DCF Valuation

DCF is the primary intrinsic valuation method.

### User Inputs

The DCF engine should accept:

- **FCF0 or latest Free Cash Flow**
- **r** = discount rate
- **n** = explicit forecast period
- **g** = terminal growth rate
- **FCF growth path**

The **FCF growth path** may be:
- constant growth,
- year-by-year custom growth inputs,
- multi-stage growth (e.g. high growth, tapering growth, terminal growth).

---

## 2.2 DCF Steps

### A. Forecast Free Cash Flow

Project future FCF for each year \( t \).

For constant growth:

\[
FCF_t = FCF_0 \times (1 + growth_t)^t
\]

Or for custom yearly growth:
- Year 1 growth = x%
- Year 2 growth = y%
- etc.

---

### B. Discount Forecast Cash Flows

\[
PV(FCF_t) = \frac{FCF_t}{(1+r)^t}
\]

Where:
- \( r \) = discount rate
- \( t \) = year number

---

### C. Calculate Terminal Value

Terminal growth rate represents the perpetual growth rate after the explicit forecast period.

Using Gordon Growth:

\[
Terminal\ Value = \frac{FCF_{n+1}}{r-g}
\]

Where:
- \( FCF_{n+1} = FCF_n \times (1+g) \)

Discount it back to present:

\[
PV(Terminal\ Value) = \frac{Terminal\ Value}{(1+r)^n}
\]

---

### D. Calculate Enterprise Value

\[
Enterprise\ Value = \sum_{t=1}^{n} \frac{FCF_t}{(1+r)^t} + \frac{Terminal\ Value}{(1+r)^n}
\]

---

### E. Calculate Equity Value

\[
Equity\ Value = Enterprise\ Value - Net\ Debt
\]

Alternative form if needed:

\[
Equity\ Value = Enterprise\ Value + Cash - Debt
\]

---

### F. Value Per Share

\[
Value\ Per\ Share = \frac{Equity\ Value}{Diluted\ Shares\ Outstanding}
\]

---

## 2.3 DCF Feature Expectations

The system should support:

- editable assumptions,
- bull / base / bear scenarios,
- sensitivity table for:
  - discount rate,
  - terminal growth rate,
- reverse DCF:
  - solve for growth assumptions implied by the current market price.

This is important because the user wants to understand:
> “What is the market offering now, and what assumptions are embedded in today’s price?”

---

# 3. Relative Valuation Models

## Objective

Estimate value using market-based multiples, especially by comparing with peer companies.

---

## 3.1 EV / EBITDA Valuation

### Concept

Use peer-group EV / EBITDA multiples and apply them to the company’s EBITDA.

### Formula

\[
Enterprise\ Value = EBITDA \times EV/EBITDA\ Multiple
\]

Then convert to equity value:

\[
Equity\ Value = Enterprise\ Value - Net\ Debt
\]

Then per share:

\[
Value\ Per\ Share = \frac{Equity\ Value}{Shares\ Outstanding}
\]

### Requirements

- calculate peer median / average EV/EBITDA,
- allow excluding outliers,
- show current company multiple vs peer multiple,
- optionally use forward EBITDA if available.

---

## 3.2 P/E Valuation

### Concept

Use earnings-based market multiple.

### Formula

\[
Price\ Per\ Share = EPS \times P/E\ Multiple
\]

Or at equity level:

\[
Equity\ Value = Net\ Income \times P/E\ Multiple
\]

### Requirements

- compute current company P/E,
- compare with historical P/E and peer P/E,
- support trailing and forward EPS,
- show implied share price from chosen multiple.

---

## 3.3 EV / Sales Valuation

### Concept

Useful especially for:
- high-growth businesses,
- low-profit or temporarily low-margin companies,
- earlier-stage businesses where EBITDA or earnings are not reliable.

### Formula

\[
Enterprise\ Value = Revenue \times EV/Sales\ Multiple
\]

Then:

\[
Equity\ Value = Enterprise\ Value - Net\ Debt
\]

\[
Value\ Per\ Share = \frac{Equity\ Value}{Shares\ Outstanding}
\]

### Requirements

- use peer median EV/Sales,
- support trailing and forward revenue,
- especially highlight use case for high-growth stocks.

---

# 4. Competition Analysis

## Objective

For a stock under research, identify competitors and compare valuation and operating metrics.

This feature should answer:
- Who are the closest peers?
- What multiples does the market assign to them?
- Is the selected stock cheaper or more expensive than peers?
- Does that premium or discount appear justified?

---

## 4.1 Competitor Analysis Output

For a selected company, provide:

- list of competitors / peers
- sector / industry classification
- market cap
- revenue
- EBITDA margin
- ROIC
- growth rates
- EV / EBITDA
- P/E
- EV / Sales
- debt metrics
- optional summary insights

---

## 4.2 Peer Comparison Logic

The peer engine should:
- identify comparable companies,
- fetch valuation multiples,
- compute:
  - peer average,
  - peer median,
  - percentile ranking of selected stock,
- support filtering peers by:
  - country,
  - industry,
  - size,
  - business model.

---

## 4.3 Suggested Insights

The app should generate plain-language commentary such as:

- “This stock trades below the peer median EV/EBITDA despite better ROIC.”
- “The company has a premium P/E, but revenue growth is also above the peer group.”
- “EV/Sales appears rich relative to peers unless margins improve.”

---

# 5. Research Workflow in the App

## Recommended User Flow

### Step 1: Run Screener
User selects a universe of stocks and filters by quality and growth thresholds.

### Step 2: Review Passed Stocks
Display all companies that satisfy the screener, with reasons and metric summaries.

### Step 3: Open Stock Research View
For a selected stock, show:
- fundamentals,
- historical trends,
- ownership trend,
- balance sheet indicators.

### Step 4: Run Valuation
Allow the user to choose:
- DCF
- EV/EBITDA
- P/E
- EV/Sales

### Step 5: Compare With Market
Show:
- intrinsic value,
- current market price,
- discount / premium,
- implied assumptions.

### Step 6: Run Competition Analysis
Show peers, peer multiples, and relative positioning.

---

# 6. Data Requirements

The implementation will need the following data fields.

## Financial Statement Data
- Revenue
- EBIT / Operating income
- EBITDA
- Net income
- Operating cash flow
- Capex
- Depreciation & amortization
- Working capital change
- Total debt
- Cash and equivalents
- Shares outstanding
- EPS

## Market Data
- Current stock price
- Market cap
- Enterprise value
- Current valuation multiples
- Historical multiples if available

## Ownership Data
- Promoter holding history
- FII holding history
- Mutual fund holding history

## Metadata
- Industry
- Sector
- Country / exchange
- Competitor mapping

---

# 7. Engineering Tasks for a Coding Agent

Below is the recommended breakdown into tasks.

---

## Task 1: Define Research Domain Model

Create the core entities and schemas for:
- Company
- Financial statements
- Market data
- Ownership data
- Screening rules
- Valuation assumptions
- Peer group data
- Valuation results

### Deliverables
- typed models / interfaces
- validation rules
- units and normalization strategy

---

## Task 2: Build Fundamental Metrics Library

Implement reusable functions to calculate:
- ROIC
- operating margin
- FCF
- net debt
- net debt / EBITDA
- revenue CAGR
- earnings CAGR
- ownership trend classification

### Deliverables
- pure calculation functions
- test coverage for each metric
- fallbacks for missing data

---

## Task 3: Build Configurable Screener Engine

Implement a rules engine that:
- accepts a stock universe,
- applies default thresholds,
- supports user-edited thresholds,
- returns pass/fail per rule and overall result.

### Deliverables
- screening engine
- rule configuration format
- response payload with explanations

Example output structure:
- stock
- rule name
- actual value
- threshold
- passed
- notes

---

## Task 4: Build Screener UI

Create UI for:
- default thresholds
- editable filters
- screener results table
- metric explanations
- pass/fail highlighting

### Deliverables
- filter panel
- results grid
- drill-down to stock research page

---

## Task 5: Implement DCF Engine

Build a DCF module that supports:
- base FCF input
- discount rate
- forecast period
- terminal growth
- custom yearly growth path
- enterprise value
- equity value
- value per share

### Deliverables
- DCF calculator
- scenario support
- sensitivity analysis matrix
- reverse DCF support if feasible

---

## Task 6: Build Relative Valuation Engine

Implement:
- EV/EBITDA valuation
- P/E valuation
- EV/Sales valuation

The system should:
- take either peer multiples or manually entered multiples,
- compute enterprise value / equity value / share price,
- compare current company valuation to peers.

### Deliverables
- three valuation modules
- standardized output format
- consistency checks across models

---

## Task 7: Build Peer Selection and Competitor Mapping

Create logic to identify peer companies based on:
- industry
- sector
- company size
- business model
- geography

### Deliverables
- peer selection rules
- manual override support
- competitor list generation

---

## Task 8: Build Competition Analysis View

Display:
- selected stock
- peer table
- peer multiples
- growth and profitability comparison
- premium/discount analysis

### Deliverables
- peer comparison dashboard
- ranking and median statistics
- plain-language insights

---

## Task 9: Build Assumption Management Layer

Allow the user to save and modify assumptions for valuation:
- discount rate
- terminal growth
- growth path
- chosen peer multiple
- bull/base/bear cases

### Deliverables
- assumption forms
- save/load presets
- validation for unrealistic inputs

---

## Task 10: Build Market-Implied Valuation Tools

Implement features that answer:
- what growth is implied by current market price?
- what multiple is the market assigning?
- what discount/premium exists vs intrinsic value?

### Deliverables
- reverse DCF helper
- implied multiple analysis
- price vs value summary widgets

---

## Task 11: Data Quality and Missing Data Handling

Implement logic for:
- missing financial fields,
- stale values,
- inconsistent periods,
- negative EBITDA or earnings,
- fallback model selection.

Example:
- if EBITDA is negative, EV/EBITDA may not be usable,
- if earnings are distorted, P/E may be misleading,
- if profits are weak but revenue is growing, EV/Sales may be more appropriate.

### Deliverables
- validation layer
- model applicability checks
- user warnings

---

## Task 12: Narrative Research Summary Generator

Generate a concise summary for each analyzed stock covering:
- quality
- growth
- balance sheet
- valuation
- peer comparison
- market-implied expectations

### Deliverables
- templated narrative engine
- plain-language explanation blocks
- bullish and risk observations

---
# 9. Output Format Recommendations

For each stock, the app should ideally produce:

## Screener Result
- pass/fail overall
- pass/fail by rule
- raw values

## Valuation Result
- DCF value per share
- EV/EBITDA implied value
- P/E implied value
- EV/Sales implied value
- current price
- upside/downside %

## Peer Result
- competitor list
- peer median multiples
- company premium/discount vs peers

## Summary
- brief qualitative explanation of findings

---

# 10. Important Implementation Notes

- All threshold values must be editable, but defaults should be preloaded.
- DCF must support both simple and advanced users.
- Not every valuation model applies to every company; the UI should explain when a model is not suitable.
- Peer valuation should favor medians over averages when outliers are present.
- Ownership trend signals should be treated as supporting indicators, not sole decision-makers.

---

# 11. Final Build Objective

The finished feature should allow a user to:
1. screen stocks by quality and growth,
2. select a company,
3. value it using multiple models,
4. compare it with peers,
5. understand whether the current market price is attractive under reasonable assumptions.
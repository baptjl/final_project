# 10-K AutoModel

Turn a 10-K HTML filing into a clean Excel model in one click.

This repository contains the code for my CPSC 1710 final project: a web app and pipeline that:

- parses a 10-K HTML filing,
- extracts the consolidated income statement,
- maps raw labels into a standard chart of accounts (COA),
- generates a projection-ready Excel workbook, and
- optionally nudges the revenue growth assumption using AI sentiment from the 10-K text and external news.

- **Live demo (Render):** (https://final-project-xr8o.onrender.com)
- **Course:** CPSC 1710 – Introduction to AI Applications (Yale)
- **Author:** Baptiste Joffe, Evan Gresser

---

## 1. Introduction

Financial modeling usually starts with a 10-K and a lot of manual copy-paste into Excel.  
The goal of this project is to:

1. **Automate extraction** of an income statement from a 10-K HTML filing.
2. **Normalize the data** into a consistent COA so that different companies can be modeled in the same template.
3. **Produce a model-ready Excel workbook**, with actuals, assumptions, and simple projections.
4. **Experiment with AI sentiment**, using management’s language (and optionally recent news) to gently adjust the revenue growth assumption.

When the pipeline is uncertain about the numbers or the sentiment signal, it prefers to be conservative and **apply no adjustment** rather than fabricate a result.

---

## 2. App Overview

The web app has four main views:

- **Home**  
  High-level description of what the tool does and why it exists.

- **App**  
  Main pipeline interface:
  1. **Source:** Paste a 10-K HTML URL or upload a `.html / .htm` file.  
  2. **Company:** Enter the company name (used in the model / news search).  
  3. **Options:** Toggle whether to use external news to enhance the revenue outlook.  
     - OpenAI-based label mapping for the COA is always enabled.  
  4. **Generate:** Runs the pipeline. When it finishes, the browser downloads `Final_<Company>.xlsx`.

- **Dashboard**  
  Shows a run history for the logged-in user:
  - Date/time
  - Company
  - Source (HTML vs SEC+HTML, etc.)
  - Base revenue growth assumption
  - Combined AI sentiment score
  - Bump in growth (if any)
  - Whether external news was used
  - Sentiment label (e.g., neutral / slightly positive)

- **Settings / Auth**  
  Simple email-and-password registration and login. Sign-up creates an account in a local SQLite DB; runs are tied to that user.

There is also a small “Finance fun fact” flip-card on the Home / App page for a bit of fun.

---

## 3. Methods & Pipeline

When you click **Generate**, the server launches a Python pipeline with the following stages:

### 3.1 Ingestion

- If a **URL** is provided: download the HTML.
- If a **file** is uploaded: read the HTML from disk.
- For this submission, SEC XBRL API support is implemented but **disabled by default** for stability.  
  The active path is HTML-based extraction.

### 3.2 Income statement extraction

- Parse the HTML and collect candidate tables.
- Score tables using heuristics:
  - presence of “Revenue”, “Net income”, etc.
  - number of year columns
  - numeric density.
- Select the best candidate as the consolidated income statement.
- Detect column scales (e.g. “in millions”).
- Convert the table into a tidy DataFrame: (raw_label, year, value).

### 3.3 COA label mapping (LLM-assisted)

- Each `raw_label` is mapped into a standard COA using:
  - exact/regex rules for common labels, and
  - an OpenAI LLM for fuzzier labels / edge cases.
- Examples of resulting COA buckets:
  - Revenue
  - Cost of Goods Sold
  - R&D
  - SG&A
  - Operating income
  - Net income
- The mapping is conservative: if the LLM is unclear and rules don’t match, the line can be left unmapped rather than wrongly classified.

### 3.4 Excel model generation

Using the COA-mapped tidy data, the pipeline:

1. Fills a **Mid-Product** structure (pandas / Excel) with historical years.
2. Writes a **Final Excel** file that includes:
   - Historical actuals
   - Assumption cells (revenue growth, margin %s, etc.)
   - Simple projections for the next few years
   - Links from assumptions → projected income statement
3. Adds a dedicated **“AI Revenue Outlook”** sheet summarizing the sentiment overlay (see below).

### 3.5 AI revenue sentiment (optional overlay)

If enabled in the environment:

1. Extracts forward-looking text from the 10-K (e.g., MD&A sections).
2. Optionally fetches recent news snippets about the company using NewsAPI.
3. Sends both to an LLM with a prompt that:
   - asks for a small integer sentiment score from negative to positive,
   - requires explicit revenue / demand / outlook commentary to justify non-zero scores.
4. Converts the combined score into a small bump in the base revenue growth assumption (e.g., ±0.5–1.5 percentage points).
5. Writes into the **AI Revenue Outlook** sheet:
   - Base growth
   - Combined score
   - Applied bump
   - Whether external news was used
   - A short note
   - Separate “10-K Evidence” and “News Evidence” sections

If the model does not find any concrete forward-looking revenue / demand language, it stays neutral and explains that no adjustment was applied.

---

## 4. Results & Example

For demonstration, I tested the pipeline on large-cap companies such as **Microsoft**:

- The HTML extractor finds the income statement and maps it into the COA.
- The generated **Final Excel** has:
  - clean historical income statement lines,
  - linked projections using a base revenue growth assumption,
  - an **AI Revenue Outlook** sheet showing:
    - base growth around the historical CAGR,
    - a combined sentiment score (often neutral or mildly positive),
    - a small or zero bump in growth, with the note explaining why.

The **Dashboard** view then shows a run entry such as:

- Date: `2025-12-09 00:39:35`
- Company: “Microsoft”
- Source: `sec_api+html` or `html`
- Base Growth: ~0.15 (15.3%)
- Combined Score: `0` (neutral)
- Bump: `0.0`
- External: `Yes` or `No`
- Label: `neutral`

This confirms that the full end-to-end flow works:
HTML → extraction → mapping → projections → sentiment → Excel download → run history.

---

## 5. Discussion & Future Work

### Challenges

- **HTML variability:** Different 10-Ks format their tables differently. Some are traditional static HTML; others, like Salesforce, use interactive/iXBRL layouts that are much harder to parse reliably.
- **Resource constraints:** Running the full pipeline (pandas, openpyxl, LLM calls, NewsAPI) on a free Render instance is tight in memory and time. This required careful error handling and conservative use of external calls.
- **Sentiment reliability:** Naïve prompts made the LLM react to generic management boilerplate (“we aim to deliver shareholder value”) with unjustified growth bumps. The prompt had to be tightened so that only explicit forward-looking revenue/demand guidance matters.

### Lessons learned

- Reliability is more important than being fancy. The pipeline is designed to **do nothing** (no bump, neutral note) when evidence is weak.
- Separating concerns (extraction, mapping, projections, sentiment) makes debugging much easier.
- Good logging and clean Excel outputs are crucial to convince yourself the automation is not hallucinating.

### Future directions

- Turn SEC XBRL API support into the **primary** extraction path for US filers, so interactive/iXBRL 10-Ks become easy to support.
- Add an explicit **“Upload PDF (experimental)”** path using OCR/vision and strong consistency checks.
- Extend the model from revenue outlook to margin / capex / FCF outlook.
- Build richer dashboards on top of run history (e.g., compare scenarios across runs or companies).

---

## 6. How to Run the Project

### 6.1 Requirements

- Python **3.10+**
- A terminal (macOS / Linux / WSL / Windows)
- Recommended: virtual environment

### 6.2 Installation

```bash
git clone https://github.com/baptjl/final_project.git
cd final_project

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
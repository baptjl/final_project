# Unified 10-K Financial Analysis Pipeline

## Overview

This is a complete end-to-end pipeline that automates financial analysis from 10-K SEC filings:

```
10-K HTML Filing
        ↓
[STEP 1] AutoModel Extraction (extract financial data from tables)
        ↓
CSV with extracted income statement data
        ↓
[STEP 2] Mid-Product Generation (convert to finmod-compatible format)
        ↓
Mid-Product.xlsx (bridge file with extracted historical actuals)
        ↓
[STEP 3] FinMod Projections (infer assumptions and project future years)
        ↓
Final.xlsx (historical actuals + AI-inferred projections)
```

## Quick Start

### Basic Usage

```bash
python unified_pipeline.py \
  --html path/to/10k_filing.html \
  --company "Company Name"
```

This generates:
- `Mid-Product.xlsx` - Extracted financial data from the 10-K
- `Final.xlsx` - Final projections with assumptions

### Advanced Options

```bash
python unified_pipeline.py \
  --html path/to/10k_filing.html \
  --company "Company Name" \
  --mid-product custom_mid_output.xlsx \
  --final custom_final_output.xlsx \
  --use-llm  # Enable LLM for better label mapping (slower, requires Ollama)
```

## What Each Step Does

### Step 1: HTML Extraction (AutoModel)

**Input:** 10-K HTML filing  
**Output:** `automodel/data/interim/IS_tidy_mapped_best_llm.csv`

Extracting financial data from 10-K filings by:
1. **Table Detection:** Automatically identifies the consolidated income statement table among 50+ tables using heuristics
2. **Data Tidying:** Normalizes row/column structure, detects years and values
3. **Scale Inference:** Detects if numbers are in millions, billions, etc.
4. **COA Mapping:** Maps raw line item labels to standardized Chart of Accounts (Revenue, COGS, R&D, etc.)

**Output CSV columns:**
- `label_raw` - Original text from the 10-K
- `year` - Fiscal year (e.g., 2023, 2024)
- `value` - Numeric value (already scaled to actual amounts)
- `coa` - Mapped Chart of Accounts category

### Step 2: Mid-Product Generation

**Input:** Extracted CSV + finmod template  
**Output:** `Mid-Product.xlsx`

Creates a bridge Excel file that:
- Takes extracted CSV data
- Populates the finmod template structure
- Aggregates multiple COA items if they map to same template line
- Preserves all historical years of actuals

**File structure:**
- Row 1: Company name header
- Row 4: Year headers (2023, 2024, 2025, 2026, ...)
- Rows 5+: Financial data (Revenue, COGS, SG&A, R&D, EBITDA, etc.)

### Step 3: FinMod Projections

**Input:** Mid-Product.xlsx  
**Output:** `Final.xlsx`

AI-powered financial modeling:
1. **Assumption Inference:** Calculates margins and growth rates from historical actuals
   - Revenue CAGR (Compound Annual Growth Rate)
   - COGS as % of revenue
   - Operating expenses as % of revenue
   - etc.
2. **Projection:** Extends assumptions forward to future years (2026-2031)
3. **Output:** Excel file with:
   - Historical actuals (2023-2025)
   - AI-inferred assumptions
   - Projected values (2026-2031)
   - Calculated margins and growth percentages

## File Structure

```
auto_model_project/
├── unified_pipeline.py           # Main orchestration script (THIS FILE)
├── mid_product_converter.py       # Converter utility
├── Mid-Product.xlsx              # Output: extracted data in finmod format
├── Final.xlsx                    # Output: final projections
│
├── automodel/                    # Financial data extraction module
│   ├── src/
│   │   ├── extract/is_tidy.py   # Table tidying logic
│   │   ├── map/map_to_coa.py    # Label mapping to Chart of Accounts
│   │   ├── ingest/              # Document ingestion
│   │   ├── llm/                 # LLM integrations (optional)
│   │   └── excel/               # Excel generation utilities
│   ├── configs/
│   │   ├── coa.yaml            # Chart of Accounts definitions
│   │   └── mappings.yaml       # Label → COA mappings
│   └── data/
│       ├── samples/            # Sample 10-K files
│       └── interim/            # Intermediate CSVs
│
└── final-project_finmod-main/   # Financial projection module
    ├── src/finmod/
    │   ├── modeler.py          # Projection engine
    │   └── main.py            # Entry point
    └── Inputs_Historical/
        └── Baseline IS.xlsx    # Template (used by both modules)
```

## Examples

### Apple 10-K Example

```bash
python unified_pipeline.py \
  --html automodel/data/samples/apple_10k_2025.html \
  --company "Apple Inc."
```

**Output:**
- Extracts: Revenue, COGS, R&D, SG&A, Operating Income, Net Income for 2023-2025
- Infers: ~1% revenue growth, ~55% COGS margin, ~6.5% SG&A margin, etc.
- Projects: 2026-2031 financials based on historical trends

### Custom 10-K File

```bash
python unified_pipeline.py \
  --html ~/Downloads/company_10k_2024.html \
  --company "My Company" \
  --mid-product my_extracted_data.xlsx \
  --final my_projections.xlsx
```

## Configuration

### LLM-Based Label Mapping (Optional)

By default, the pipeline uses rule-based mapping for COA labels (fast, no external dependencies).

To enable LLM-based mapping for better accuracy:

```bash
python unified_pipeline.py \
  --html path/to/10k.html \
  --use-llm
```

**Requirements:**
- Ollama installed and running: `ollama serve`
- Model downloaded: `ollama pull mistral:7b-instruct`
- Takes 5-10x longer but catches more label variations

### Custom Mappings

Edit `automodel/configs/mappings.yaml` to add custom label → COA mappings:

```yaml
"net sales": Revenue
"total revenue": Revenue
"cost of revenue": COGS
"sg&a expenses": General & Administrative
# ... etc
```

## Output Interpretation

### Mid-Product.xlsx

Shows historical extracted financial data in a clean template:

| Line Item     | 2023      | 2024      | 2025      |
|---------------|-----------|-----------|-----------|
| Revenue       | 383.3B    | 383.3B    | 391.0B    |
| COGS          | (214.1B)  | (214.1B)  | (210.4B)  |
| Gross Profit  | 169.1B    | 169.1B    | 180.7B    |
| SG&A          | (24.9B)   | (24.9B)   | (26.1B)   |
| R&D           | (29.9B)   | (29.9B)   | (31.4B)   |
| EBITDA        | 205.6B    | 205.6B    | 197.5B    |

### Final.xlsx

Shows actuals plus projections with inferred assumptions:

**Assumptions Sheet:**
- Revenue CAGR: 1.01%
- COGS: 55.18% of revenue
- SG&A: 6.56% of revenue
- R&D: 7.88% of revenue

**Projections Sheet:**
| Line Item     | 2023      | 2024      | 2025      | 2026      | 2027      |
|---------------|-----------|-----------|-----------|-----------|-----------|
| Revenue       | 383.3B    | 383.3B    | 391.0B    | **395.0B**| **398.9B**|
| COGS          | (214.1B)  | (214.1B)  | (210.4B)  | **(217.9B)**| **(220.1B)**|
| Gross Profit  | 169.1B    | 169.1B    | 180.7B    | **177.0B**| **178.8B**|

*Bolded = projected values*

## Troubleshooting

### "No tables found in HTML"

The input file is not a valid HTML 10-K. Check that:
- File is actually HTML (not PDF converted to HTML)
- File contains financial tables (most SEC filings do)
- Try downloading directly from SEC.gov instead of copying/pasting

### "FinMod: Need at least two actual periods to infer growth"

The extraction didn't find enough historical years. Usually means:
- Only 1 year of data was extracted
- Check Mid-Product.xlsx - does it have multiple years populated?
- Check Summary tab in extraction output - does it show multiple years?

**Solution:**
- Ensure your 10-K has at least 2-3 years of historical data in its income statement
- Check that year columns were detected correctly (F, G columns should have 2024, 2025)

### Columns not populated in Mid-Product

The extracted CSV has the data, but it's not showing in the Excel. Usually:
- Years in CSV don't match template years (check data: column dates)
- Template structure changed
- COA mapping didn't match

**Debug:**
```bash
cat automodel/data/interim/IS_tidy_mapped_best_llm.csv | head -20
```

Check if you see the expected years (2023, 2024, 2025) and COA categories (Revenue, COGS, etc.)

## Advanced Usage

### Running Only Step 1 (Extraction)

```python
from unified_pipeline import step1_extract_from_html
from pathlib import Path

csv_path = step1_extract_from_html(Path("my_10k.html"), skip_llm=True)
print(f"Data extracted to: {csv_path}")
```

### Running Only Step 2 (Mid-Product Creation)

```python
from unified_pipeline import step2_create_mid_product
from pathlib import Path

step2_create_mid_product(
    csv_path=Path("automodel/data/interim/IS_tidy_mapped_best_llm.csv"),
    template_path=Path("final-project_finmod-main/Inputs_Historical/Baseline IS.xlsx"),
    output_path=Path("My-Mid-Product.xlsx"),
    company_name="My Company"
)
```

### Running Only Step 3 (Projections)

```python
from unified_pipeline import step3_run_finmod_projections
from pathlib import Path

step3_run_finmod_projections(
    mid_product_path=Path("Mid-Product.xlsx"),
    output_path=Path("My-Final.xlsx")
)
```

## Performance

- **Step 1 (Extraction):** 2-5 seconds for typical 10-K HTML (~2MB)
- **Step 2 (Mid-Product):** < 1 second
- **Step 3 (Projections):** < 1 second
- **With LLM enabled:** Add 30-120 seconds depending on model and number of unmapped labels

**Total time:** ~5-10 seconds (or 2-5 minutes with LLM)

## Supported Companies

The pipeline works with any company that files 10-Ks with the SEC, including:
- All S&P 500 companies
- Large-cap US companies
- Many international companies with SEC filings

**Note:** Company-specific adjustments may be needed for:
- Highly complex business structures (multiple segments)
- Unusual account names
- Non-standard income statement structures

## Limitations

1. **Income Statement Only:** Currently extracts P&L only (Revenue, Expenses, Income). Does not extract Balance Sheet or Cash Flow.

2. **Consolidated Only:** Extracts consolidated figures, not segment breakdowns.

3. **Historical Trend Based:** Projections assume past trends continue. Does not account for:
   - Strategic changes
   - Market disruptions
   - One-time items

4. **Deterministic:** Uses fixed percentage assumptions, not probabilistic forecasting.

## Next Steps

After generating Final.xlsx:
1. Review assumptions for reasonableness
2. Adjust for known future changes (product launches, cost cuts, etc.)
3. Build DCF models or other valuation analyses
4. Compare vs. analyst estimates and market guidance

## Support

For issues or questions:
1. Check Troubleshooting section above
2. Review debug output in terminal
3. Check Mid-Product.xlsx to ensure data was extracted
4. Verify 10-K HTML structure matches expectations

## License

This pipeline combines two modules:
- `automodel/` - Custom extraction and mapping (Yale course project)
- `final-project_finmod-main/` - FinMod financial modeling (Yale course project)

Both for educational use.

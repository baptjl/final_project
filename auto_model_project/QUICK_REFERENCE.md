# Quick Reference Card

## ⚡ 30-Second Quick Start

```bash
cd "/Users/baptistejoffe/Documents/Yale classes/Introduction to AI Application/Assignements/Final Project/auto_model_project"

source .venv/bin/activate
python unified_pipeline.py --html your_10k.html --company "Company Name"
```

**Output:**
- `Mid-Product.xlsx` - Extracted historical financials
- `Final.xlsx` - Projections with AI-inferred assumptions

---

## 📋 File Guide

| File | Purpose | When to Use |
|------|---------|------------|
| `unified_pipeline.py` | Main script - orchestrates all 3 steps | Always - this is the primary tool |
| `mid_product_converter.py` | Step 2 only - standalone converter | Only if you already have extracted CSV |
| `UNIFIED_PIPELINE.md` | Complete documentation | Detailed reference, troubleshooting |
| `PIPELINE_SUMMARY.md` | Overview & technical details | Understanding architecture |
| `Mid-Product.xlsx` | Output - extracted data | Review extracted numbers |
| `Final.xlsx` | Output - projections | Use for analysis, DCF models |

---

## 🎯 Common Tasks

### Extract & Project a 10-K
```bash
python unified_pipeline.py --html your_10k.html --company "Company"
```

### Use Custom Output Paths
```bash
python unified_pipeline.py \
  --html 10k.html \
  --company "Company" \
  --mid-product extracted.xlsx \
  --final projections.xlsx
```

### Enable LLM-Based Label Mapping (Better but Slower)
```bash
# First, start Ollama in another terminal:
# ollama serve

python unified_pipeline.py \
  --html 10k.html \
  --company "Company" \
  --use-llm
```

### Convert Just Extracted CSV to Excel
```bash
python mid_product_converter.py
# Reads: automodel/data/interim/IS_tidy_mapped_best_llm.csv
# Outputs: Mid-Product.xlsx
```

---

## 📊 What Gets Output

### Mid-Product.xlsx (Historical Data)
Shows extracted income statement with:
- Multiple years of actuals (2023, 2024, 2025)
- Revenue, COGS, Gross Profit, Operating Expenses, Net Income
- All numbers normalized to actual amounts

**Use for:** Verifying extraction accuracy

### Final.xlsx (Projections)
Contains:
- **Assumptions Sheet:** Inferred growth rates and margins
- **Projections Sheet:** Historical actuals + projected years (2026-2031)

**Example Assumptions:**
- Revenue CAGR: 1.01%
- COGS: 55.18% of revenue
- SG&A: 6.56% of revenue
- R&D: 7.88% of revenue

**Use for:** DCF models, scenario planning, valuation

---

## ✅ What Actually Happens

### Step 1: Extraction (2-5 seconds)
```
HTML → Extract all tables → Detect income statement table
    → Tidy data → Detect years and values
    → Map labels to Chart of Accounts
    → Output CSV with all line items
```

### Step 2: Mid-Product Generation (< 1 second)
```
CSV → Aggregate by COA category
    → Populate Excel template
    → Preserve all years and line items
    → Output finmod-compatible Excel
```

### Step 3: FinMod Projections (< 1 second)
```
Excel → Read historical actuals
     → Infer assumptions (growth, margins)
     → Project future years
     → Output with assumptions + projections
```

**Total Time:** ~5-10 seconds (or 2-5 min with --use-llm)

---

## 🔍 Debugging Checklist

| Issue | Check |
|-------|-------|
| No tables found | Is it real HTML? Try direct SEC download |
| Only 1 year extracted | Does 10-K have 2+ years of data? |
| Wrong numbers | Check Mid-Product.xlsx - is data there? |
| Missing line items | Some lines may not map - check mappings.yaml |
| FinMod fails | Check Mid-Product has 2+ years in columns |
| Very slow | Try removing --use-llm flag |

---

## 📚 Documentation

- **Quick Start:** This file
- **Full Guide:** `UNIFIED_PIPELINE.md` 
- **Architecture:** `PIPELINE_SUMMARY.md`

---

## 🏗️ Project Structure

```
auto_model_project/
├── unified_pipeline.py          ← MAIN SCRIPT
├── mid_product_converter.py
├── UNIFIED_PIPELINE.md
├── PIPELINE_SUMMARY.md
├── Mid-Product.xlsx             ← OUTPUT 1
├── Final.xlsx                   ← OUTPUT 2
├── automodel/                   ← Extraction module
│   ├── src/extract/is_tidy.py
│   ├── src/map/map_to_coa.py
│   ├── configs/mappings.yaml
│   └── data/samples/
│       └── apple_10k_2025.html
└── final-project_finmod-main/   ← Projection module
    ├── src/finmod/modeler.py
    └── Inputs_Historical/
        └── Baseline IS.xlsx
```

---

## 💡 Pro Tips

1. **Validate extraction first:** Open Mid-Product.xlsx before checking Final.xlsx

2. **Adjust assumptions if needed:** Edit assumptions in Final.xlsx and recalculate

3. **Save variations:** Use `--mid-product` and `--final` flags for different scenarios

4. **Batch process:** Loop over multiple 10-K files:
   ```bash
   for file in *.html; do
     company=$(basename "$file" .html)
     python unified_pipeline.py --html "$file" --company "$company"
   done
   ```

5. **Integration:** Import functions for programmatic use:
   ```python
   from unified_pipeline import main
   main(html_path="file.html", company_name="Company")
   ```

---

## 🎯 Success Metrics

✅ Extraction finds correct table automatically  
✅ All historical years populated in Mid-Product  
✅ Final.xlsx shows assumptions and projections  
✅ Numbers make sense (no extreme growth rates)  
✅ Takes < 10 seconds to run (< 5 min with LLM)  

---

**Last Updated:** November 29, 2025  
**Status:** ✅ Production Ready
